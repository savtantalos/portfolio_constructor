import math
import re
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from threading import RLock

import numpy as np
import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError, YFTickerMissingError

from portfolio_backend.errors import PortfolioError
from portfolio_backend.market_types import MarketDataProvider, MarketDataset
from portfolio_backend.models import Instrument

_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.^=_-]{0,31}$")
_SUPPORTED_TYPES = {"EQUITY", "ETF"}


def _text(value: object) -> str | None:
    """Return a stripped nonempty string, or None for blank/non-string values."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _copy_dataset(dataset: MarketDataset) -> MarketDataset:
    """Deep-copy a dataset, including price axes, to isolate cached state."""
    copied = deepcopy(dataset)
    copied.prices.index = dataset.prices.index.copy(deep=True)
    copied.prices.columns = dataset.prices.columns.copy(deep=True)
    return copied


def _upstream_error(error: Exception, symbol: str | None = None) -> PortfolioError:
    """Translate an upstream exception into a client-facing PortfolioError.

    Args:
        error: Yahoo Finance or data-processing exception to classify.
        symbol: Optional ticker used in missing-history diagnostics.

    Returns:
        An error object, not raised here, distinguishing rate limits, missing
        history, timeouts, malformed data, and other upstream failures.
    """
    if isinstance(error, YFRateLimitError):
        return PortfolioError(
            "market_data_rate_limited",
            "Yahoo Finance is temporarily rate limiting requests. Please retry later.",
            503,
        )
    if isinstance(error, YFTickerMissingError):
        return PortfolioError(
            "market_data_unavailable",
            f"No usable Yahoo Finance history for {symbol}. Check the symbol and requested dates.",
        )
    if isinstance(error, TimeoutError):
        return PortfolioError(
            "market_data_timeout", "Yahoo Finance timed out. Please retry later.", 503
        )
    if isinstance(error, KeyError | TypeError | ValueError):
        return PortfolioError(
            "invalid_market_data",
            "Yahoo Finance returned malformed market data. Try another symbol or retry later.",
        )
    return PortfolioError(
        "market_data_upstream_error",
        "Yahoo Finance could not complete the market data request. Please retry later.",
        502,
    )


class YahooFinanceProvider(MarketDataProvider):
    """Fetch equity/ETF metadata and common-date adjusted Yahoo Finance prices.

    History requires exact agreement with the requested currency, without FX
    or currency-subunit conversion or price filling. A lock-protected TTL/LRU
    cache stores history datasets and isolates callers through deep copies.
    """

    def __init__(
        self,
        cache_ttl_seconds: float = 3600,
        cache_max_entries: int = 128,
        timeout_seconds: float = 15,
    ) -> None:
        """Configure history caching and Yahoo Finance request timeouts.

        Args:
            cache_ttl_seconds: Nonnegative cache lifetime in monotonic seconds;
                zero disables storage.
            cache_max_entries: Nonnegative maximum cached datasets; zero
                disables storage. Least-recently-used entries are evicted.
            timeout_seconds: Finite positive timeout in seconds passed to
                Yahoo Finance search and history requests.

        Raises:
            ValueError: If a cache limit or timeout fails validation.
        """
        if not math.isfinite(cache_ttl_seconds) or cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must be finite and nonnegative")
        if not isinstance(cache_max_entries, int) or cache_max_entries < 0:
            raise ValueError("cache_max_entries must be a nonnegative integer")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_max_entries = cache_max_entries
        self.timeout_seconds = timeout_seconds
        self._cache: OrderedDict[
            tuple[tuple[str, ...], date, date, str], tuple[float, MarketDataset]
        ] = OrderedDict()
        self._cache_lock = RLock()

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        """Search Yahoo Finance for distinct supported equity and ETF symbols.

        Args:
            query: Nonempty search text, stripped before submission.
            limit: Maximum result count, an integer from 1 through 100.

        Returns:
            Up to limit instruments in provider order, excluding malformed,
            duplicate, or unsupported quotes. Optional metadata may be absent.

        Raises:
            PortfolioError: If inputs are invalid, the provider request fails,
                or the search response is not a list.
        """
        query = _text(query)
        if query is None or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise PortfolioError(
                "invalid_search", "Provide a nonempty search query and a limit between 1 and 100."
            )
        try:
            quotes = yf.Search(
                query,
                max_results=limit,
                news_count=0,
                timeout=self.timeout_seconds,
                raise_errors=True,
            ).quotes
        except Exception as error:
            raise _upstream_error(error) from None
        if not isinstance(quotes, list):
            raise PortfolioError(
                "invalid_market_data", "Yahoo Finance returned malformed search results."
            )
        instruments = []
        seen = set()
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            symbol = _text(quote.get("symbol"))
            instrument_type = _text(quote.get("quoteType"))
            if (
                symbol is None
                or not _SYMBOL.fullmatch(symbol)
                or instrument_type not in _SUPPORTED_TYPES
                or symbol in seen
            ):
                continue
            seen.add(symbol)
            instruments.append(
                Instrument(
                    symbol=symbol,
                    name=_text(quote.get("longname")) or _text(quote.get("shortname")),
                    exchange=_text(quote.get("exchDisp")) or _text(quote.get("exchange")),
                    currency=_text(quote.get("currency")),
                    instrument_type=instrument_type,
                )
            )
            if len(instruments) == limit:
                break
        return instruments

    def history(
        self, tickers: list[str], start: date, end: date, base_currency: str
    ) -> MarketDataset:
        if (
            not tickers
            or any(
                not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) for symbol in tickers
            )
            or len(set(tickers)) != len(tickers)
        ):
            raise PortfolioError(
                "invalid_tickers", "Provide unique, valid Yahoo Finance ticker symbols."
            )
        if (
            not isinstance(start, date)
            or not isinstance(end, date)
            or isinstance(start, datetime)
            or isinstance(end, datetime)
            or start >= end
            or end == date.max
        ):
            raise PortfolioError(
                "invalid_dates", "Provide a start date before the inclusive end date."
            )
        if not isinstance(base_currency, str) or not re.fullmatch(r"[A-Z]{3}", base_currency):
            raise PortfolioError(
                "invalid_currency", "Provide a three-letter uppercase base currency."
            )
        key = (tuple(tickers), start, end, base_currency)
        with self._cache_lock:
            self._expire_cache()
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return _copy_dataset(cached[1])

        series = []
        instruments = []
        warnings = []
        for symbol in tickers:
            try:
                client = yf.Ticker(symbol)
                frame = client.history(
                    start=start,
                    end=end + timedelta(days=1),
                    auto_adjust=False,
                    actions=False,
                    raise_errors=True,
                    timeout=self.timeout_seconds,
                )
                history = getattr(client, "_price_history", None)
                metadata = getattr(history, "_history_metadata", None)
                if not isinstance(metadata, dict) or not metadata:
                    metadata = client.get_history_metadata()
            except Exception as error:
                raise _upstream_error(error, symbol) from None
            instrument = self._instrument(symbol, metadata, base_currency)
            prices = self._prices(symbol, frame, start, end)
            if prices.index[0].date() > start:
                warnings.append(
                    f"{symbol}: available history starts on {prices.index[0].date()}, "
                    f"after requested {start}. A late IPO, exchange holidays, or missing "
                    "provider history may shorten the historical range; "
                    "no earlier prices were filled."
                )
            if prices.index[-1].date() < end:
                warnings.append(
                    f"{symbol}: available history ends on {prices.index[-1].date()}, "
                    f"before requested {end}; the historical range is shortened."
                )
            series.append(prices)
            instruments.append(instrument)

        combined = pd.concat(series, axis=1).sort_index()
        prices = combined.dropna(how="any")
        dropped = len(combined) - len(prices)
        if dropped:
            warnings.append(
                f"Dropped {dropped} dates with missing prices for one or more tickers "
                "when aligning common trading dates. No prices were forward-filled."
            )
        if len(prices) < 61:
            raise PortfolioError(
                "insufficient_history",
                f"Only {len(prices)} common adjusted closing prices are available. "
                "At least 61 prices (60 returns) are required; extend the dates "
                "or remove short-history instruments.",
            )
        effective_start = prices.index[0].date()
        effective_end = prices.index[-1].date()
        if effective_start > start or effective_end < end:
            warnings.append(
                f"The effective historical range is shortened to {effective_start} through "
                f"{effective_end}, versus requested {start} through {end}."
            )
        dataset = MarketDataset(
            prices=prices,
            instruments=instruments,
            fetched_at=datetime.now(UTC),
            warnings=warnings,
        )
        if self.cache_ttl_seconds > 0 and self.cache_max_entries > 0:
            with self._cache_lock:
                self._expire_cache()
                self._cache[key] = (
                    time.monotonic() + self.cache_ttl_seconds,
                    _copy_dataset(dataset),
                )
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_max_entries:
                    self._cache.popitem(last=False)
        return dataset

    def _expire_cache(self) -> None:
        now = time.monotonic()
        for key, (expires_at, _) in list(self._cache.items()):
            if expires_at <= now:
                del self._cache[key]

    @staticmethod
    def _instrument(symbol: str, metadata: object, base_currency: str) -> Instrument:
        if not isinstance(metadata, dict):
            raise PortfolioError(
                "missing_market_metadata",
                f"Yahoo Finance did not supply metadata for {symbol}. "
                "Choose another symbol or retry later.",
            )
        currency = _text(metadata.get("currency"))
        if currency is None:
            raise PortfolioError(
                "missing_currency",
                f"Yahoo Finance did not identify the price currency for {symbol}. "
                "Currency cannot be assumed; choose another symbol or retry later.",
            )
        if currency != base_currency:
            raise PortfolioError(
                "currency_mismatch",
                f"{symbol} is quoted in {currency}, not {base_currency}. Select instruments in the "
                "base currency; FX and currency-subunit conversion are not supported.",
            )
        instrument_type = _text(metadata.get("instrumentType")) or _text(metadata.get("quoteType"))
        if instrument_type not in _SUPPORTED_TYPES:
            raise PortfolioError(
                "unsupported_instrument",
                f"{symbol} could not be confirmed as an equity or ETF. "
                "Select a supported equity or ETF with available Yahoo Finance "
                "instrument metadata.",
            )
        return Instrument(
            symbol=symbol,
            name=_text(metadata.get("longName")) or _text(metadata.get("shortName")),
            exchange=_text(metadata.get("fullExchangeName")) or _text(metadata.get("exchangeName")),
            currency=currency,
            instrument_type=instrument_type,
        )

    @staticmethod
    def _prices(symbol: str, frame: object, start: date, end: date) -> pd.Series:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise PortfolioError(
                "market_data_unavailable",
                f"No price history is available for {symbol}. "
                "Check the symbol and requested dates.",
            )
        if (
            isinstance(frame.columns, pd.MultiIndex)
            or "Adj Close" not in frame.columns
            or not frame.columns.is_unique
        ):
            raise PortfolioError(
                "missing_adjusted_prices",
                f"Yahoo Finance did not provide adjusted closing prices for {symbol}. Unadjusted "
                "prices cannot be used; choose another symbol or retry later.",
            )
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
            raise PortfolioError("invalid_market_data", f"{symbol} has invalid historical dates.")
        prices = frame["Adj Close"].copy()
        prices.index = prices.index.tz_localize(None).normalize()
        prices = prices.loc[(prices.index.date >= start) & (prices.index.date <= end)].sort_index()
        if prices.empty:
            raise PortfolioError(
                "market_data_unavailable",
                f"{symbol} has no adjusted prices within the requested dates.",
            )
        if not prices.index.is_unique:
            raise PortfolioError(
                "invalid_market_data", f"{symbol} has duplicate daily price dates."
            )
        try:
            if prices.map(
                lambda value: isinstance(value, bool | np.bool_ | complex | np.complexfloating)
            ).any():
                raise ValueError
            prices = pd.to_numeric(prices, errors="raise").astype(float)
            valid = np.isfinite(prices.to_numpy()).all() and (prices > 0).all()
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise PortfolioError(
                "invalid_market_data",
                f"{symbol} has invalid adjusted closing prices. "
                "All prices must be numeric, finite, and strictly positive; "
                "choose another symbol or retry later.",
            )
        return prices.rename(symbol)
