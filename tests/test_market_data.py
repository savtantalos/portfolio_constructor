from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from yfinance.exceptions import YFPricesMissingError, YFRateLimitError, YFTzMissingError

import portfolio_backend.market_data as market_data
from portfolio_backend.errors import PortfolioError
from portfolio_backend.market_data import YahooFinanceProvider

START = date(2024, 1, 1)
END = date(2024, 4, 19)
DATES = pd.bdate_range(START, END, tz="America/New_York")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail any Yahoo ticker or search construction not explicitly mocked by a test."""
    monkeypatch.setattr(
        market_data.yf, "Ticker", Mock(side_effect=AssertionError("Unexpected Ticker"))
    )
    monkeypatch.setattr(
        market_data.yf, "Search", Mock(side_effect=AssertionError("Unexpected Search"))
    )


@pytest.fixture
def mock_history(monkeypatch):
    """Provide an installer for configurable Yahoo history and metadata mocks."""

    def install(frames=None, metadata=None, errors=None, raw_metadata=False):
        """Patch ticker creation and return its mock factory and per-symbol client registry."""
        frames = frames or {}
        metadata = metadata or {}
        errors = errors or {}
        clients = {}

        def ticker(symbol):
            frame = frames.get(symbol, price_frame())
            meta = metadata.get(symbol, {"currency": "USD", "instrumentType": "EQUITY"})
            client = Mock(spec=["history", "get_history_metadata", "_price_history"])
            client.history.return_value = frame
            if symbol in errors:
                client.history.side_effect = errors[symbol]
            client.get_history_metadata.return_value = meta
            client._price_history = (
                SimpleNamespace(_history_metadata=meta) if raw_metadata else None
            )
            clients[symbol] = client
            return client

        factory = Mock(side_effect=ticker)
        monkeypatch.setattr(market_data.yf, "Ticker", factory)
        return factory, clients

    return install


def price_frame(index=DATES):
    return pd.DataFrame(
        {"Adj Close": np.arange(len(index), dtype=float) + 50, "Close": np.full(len(index), 500.0)},
        index=index,
    )


def load(provider=None, tickers=None, start=START, end=END, currency="USD"):
    return (provider or YahooFinanceProvider()).history(tickers or ["AAA"], start, end, currency)


def test_adjusted_prices_inclusive_end_and_metadata_without_info(mock_history):
    factory, clients = mock_history(
        metadata={"AAA": {"currency": "USD", "instrumentType": "ETF", "longName": "Alpha Fund"}}
    )
    dataset = load(YahooFinanceProvider(timeout_seconds=7))
    factory.assert_called_once_with("AAA")
    clients["AAA"].history.assert_called_once_with(
        start=START,
        end=END + timedelta(days=1),
        auto_adjust=False,
        actions=False,
        raise_errors=True,
        timeout=7,
    )
    clients["AAA"].get_history_metadata.assert_called_once_with()
    assert dataset.prices.iloc[0, 0] == 50
    assert dataset.prices.iloc[-1, 0] == 129
    assert dataset.prices.index[-1].date() == END
    assert dataset.prices.index.tz is None
    assert dataset.instruments[0].instrument_type == "ETF"
    assert dataset.instruments[0].name == "Alpha Fund"
    assert dataset.fetched_at.tzinfo is not None
    assert dataset.provider == "yahoo_finance"
    assert "splits" in dataset.adjustment
    assert dataset.warnings == []


def test_existing_chart_metadata_avoids_extra_metadata_network(mock_history):
    _, clients = mock_history(raw_metadata=True)
    load()
    clients["AAA"].get_history_metadata.assert_not_called()


def test_quote_type_metadata_compatibility(mock_history):
    mock_history(metadata={"AAA": {"currency": "USD", "quoteType": "EQUITY"}})
    assert load().instruments[0].instrument_type == "EQUITY"


@pytest.mark.parametrize("metadata", [None, {}, {"instrumentType": "EQUITY"}, {"currency": None}])
def test_missing_currency_or_metadata_is_not_assumed(mock_history, metadata):
    mock_history(metadata={"AAA": metadata})
    with pytest.raises(PortfolioError) as raised:
        load()
    assert raised.value.status_code == 422
    assert raised.value.code in {"missing_currency", "missing_market_metadata"}
    assert "AAA" in raised.value.message


@pytest.mark.parametrize("currency,base", [("EUR", "USD"), ("GBp", "GBP"), ("usd", "USD")])
def test_currency_is_strict_and_pence_is_not_pounds(mock_history, currency, base):
    mock_history(metadata={"AAA": {"currency": currency, "instrumentType": "EQUITY"}})
    with pytest.raises(PortfolioError, match="conversion") as raised:
        load(currency=base)
    assert raised.value.code == "currency_mismatch"
    assert raised.value.status_code == 422


@pytest.mark.parametrize(
    "instrument_type", [None, "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "FUTURE"]
)
def test_only_confirmed_equity_or_etf_is_supported(mock_history, instrument_type):
    mock_history(metadata={"AAA": {"currency": "USD", "instrumentType": instrument_type}})
    with pytest.raises(PortfolioError) as raised:
        load()
    assert raised.value.code == "unsupported_instrument"


def test_missing_adjusted_close_never_falls_back_to_close(mock_history):
    mock_history(frames={"AAA": price_frame().drop(columns="Adj Close")})
    with pytest.raises(PortfolioError, match="Unadjusted") as raised:
        load()
    assert raised.value.code == "missing_adjusted_prices"


def test_split_uses_adjusted_not_raw_returns(mock_history):
    frame = price_frame()
    frame["Adj Close"] = 50.0
    frame["Close"] = [100.0] * 40 + [50.0] * 40
    mock_history(frames={"AAA": frame})
    assert (load().prices.pct_change().dropna() == 0).all().all()


def test_dates_sorted_local_daily_and_clipped(mock_history):
    dates = pd.date_range("2023-12-30 23:30", "2024-04-21 23:30", tz="America/New_York")
    frame = price_frame(dates).iloc[::-1]
    mock_history(frames={"AAA": frame})
    prices = load().prices
    assert prices.index[0] == pd.Timestamp(START)
    assert prices.index[-1] == pd.Timestamp(END)
    assert prices.index.is_unique
    assert prices.index.is_monotonic_increasing
    assert prices.index.tz is None
    assert prices.index.equals(prices.index.normalize())


def test_common_dates_without_filling_and_late_ipo_warnings(mock_history):
    first = price_frame()
    second = price_frame().iloc[10:-2].drop(DATES[40])
    mock_history(frames={"AAA": first, "BBB": second})
    dataset = load(tickers=["BBB", "AAA"])
    assert dataset.prices.columns.tolist() == ["BBB", "AAA"]
    assert dataset.prices.index.equals(second.index.tz_localize(None))
    assert len(dataset.prices) == 67
    assert pd.Timestamp(DATES[40]).tz_localize(None) not in dataset.prices.index
    assert (
        dataset.prices.loc[DATES[41].tz_localize(None), "BBB"] == second.loc[DATES[41], "Adj Close"]
    )
    warnings = " ".join(dataset.warnings)
    assert "Dropped 13 dates" in warnings
    assert "No prices were forward-filled" in warnings
    assert "late IPO" in warnings
    assert "effective historical range is shortened" in warnings


@pytest.mark.parametrize("value", [0, -1, np.inf, -np.inf, np.nan, None, "bad", True, 2 + 1j])
def test_invalid_prices_are_rejected_not_filled(mock_history, value):
    frame = price_frame().astype({"Adj Close": object})
    frame.iloc[5, 0] = value
    mock_history(frames={"AAA": frame})
    with pytest.raises(PortfolioError) as raised:
        load()
    assert raised.value.code == "invalid_market_data"
    assert raised.value.status_code == 422


def test_numeric_strings_are_validated_and_converted(mock_history):
    frame = price_frame().astype({"Adj Close": str})
    mock_history(frames={"AAA": frame})
    assert load().prices.iloc[0, 0] == 50.0


@pytest.mark.parametrize("kind", ["duplicate", "duplicate_daily", "nat", "numeric_index"])
def test_invalid_dates_fail(mock_history, kind):
    frame = price_frame()
    if kind == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif kind == "duplicate_daily":
        extra = frame.iloc[:1].copy()
        extra.index += pd.Timedelta(hours=4)
        frame = pd.concat([frame, extra])
    elif kind == "nat":
        frame.index = pd.DatetimeIndex([pd.NaT, *frame.index[1:]])
    else:
        frame = frame.reset_index(drop=True)
    mock_history(frames={"AAA": frame})
    with pytest.raises(PortfolioError) as raised:
        load()
    assert raised.value.code == "invalid_market_data"


@pytest.mark.parametrize("count", [0, 60, 61])
def test_minimum_sixty_returns(mock_history, count):
    mock_history(frames={"AAA": price_frame().iloc[:count]})
    if count == 61:
        assert len(load().prices) == 61
    else:
        with pytest.raises(PortfolioError) as raised:
            load()
        assert raised.value.status_code == 422
        if count:
            assert raised.value.code == "insufficient_history"
            assert "60 returns" in raised.value.message


def test_insufficient_common_history_fails_entire_request(mock_history):
    mock_history(frames={"AAA": price_frame().iloc[:61], "BBB": price_frame().iloc[19:]})
    with pytest.raises(PortfolioError) as raised:
        load(tickers=["AAA", "BBB"])
    assert raised.value.code == "insufficient_history"


def test_invalid_symbol_is_never_silently_dropped(mock_history):
    factory, _ = mock_history(frames={"BAD": pd.DataFrame()})
    with pytest.raises(PortfolioError, match="BAD"):
        load(tickers=["AAA", "BAD"])
    assert factory.call_count == 2


@pytest.mark.parametrize(
    "error,status,code",
    [
        (YFRateLimitError(), 503, "market_data_rate_limited"),
        (TimeoutError("private endpoint and token"), 503, "market_data_timeout"),
        (ConnectionError("private endpoint and token"), 502, "market_data_upstream_error"),
        (RuntimeError("private endpoint and token"), 502, "market_data_upstream_error"),
        (YFPricesMissingError("AAA", "private endpoint and token"), 422, "market_data_unavailable"),
        (YFTzMissingError("AAA"), 422, "market_data_unavailable"),
        (KeyError("private endpoint and token"), 422, "invalid_market_data"),
    ],
)
def test_safe_upstream_errors(mock_history, error, status, code):
    mock_history(errors={"AAA": error})
    with pytest.raises(PortfolioError) as raised:
        load()
    assert raised.value.status_code == status
    assert raised.value.code == code
    assert "private" not in raised.value.message
    assert "token" not in raised.value.message


def test_metadata_failure_is_safe(monkeypatch):
    client = Mock()
    client.history.return_value = price_frame()
    client.get_history_metadata.side_effect = ConnectionError("secret")
    monkeypatch.setattr(market_data.yf, "Ticker", Mock(return_value=client))
    with pytest.raises(PortfolioError) as raised:
        load()
    assert raised.value.status_code == 502
    assert "secret" not in raised.value.message


def test_cache_defensive_copies_cover_prices_instruments_and_warnings(mock_history):
    factory, _ = mock_history(frames={"AAA": price_frame().iloc[1:]})
    provider = YahooFinanceProvider()
    first = load(provider)
    original = first.prices.iloc[0, 0]
    original_warnings = first.warnings.copy()
    first.prices.iloc[0, 0] = -99
    first.instruments[0].symbol = "MUTATED"
    first.warnings.append("MUTATED")
    original_date = first.prices.index[0]
    first.prices.index.values[0] = np.datetime64("2000-01-01")
    first.prices.columns.values[0] = "MUTATED"
    second = load(provider)
    assert second.prices.index[0] == original_date
    assert second.prices.columns.tolist() == ["AAA"]
    assert second.prices.iloc[0, 0] == original
    assert second.instruments[0].symbol == "AAA"
    assert second.warnings == original_warnings
    assert second.fetched_at == first.fetched_at
    second.prices.iloc[0, 0] = -88
    assert load(provider).prices.iloc[0, 0] == original
    factory.assert_called_once_with("AAA")


def test_cache_key_includes_order_dates_and_currency(mock_history):
    factory, _ = mock_history()
    provider = YahooFinanceProvider()
    assert load(provider, ["AAA", "BBB"]).prices.columns.tolist() == ["AAA", "BBB"]
    assert load(provider, ["BBB", "AAA"]).prices.columns.tolist() == ["BBB", "AAA"]
    load(provider, ["AAA", "BBB"], start=START - timedelta(days=1))
    load(provider, ["AAA", "BBB"], end=END + timedelta(days=1))
    assert factory.call_count == 8
    with pytest.raises(PortfolioError) as raised:
        load(provider, ["AAA", "BBB"], currency="EUR")
    assert raised.value.code == "currency_mismatch"
    assert factory.call_count == 9


def test_cache_ttl_expires(mock_history, monkeypatch):
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(market_data.time, "monotonic", clock)
    factory, _ = mock_history()
    provider = YahooFinanceProvider(cache_ttl_seconds=10)
    load(provider)
    clock.return_value = 109.0
    load(provider)
    assert factory.call_count == 1
    clock.return_value = 110.0
    load(provider)
    assert factory.call_count == 2


def test_cache_is_bounded_and_lru(mock_history):
    factory, _ = mock_history()
    provider = YahooFinanceProvider(cache_max_entries=2)
    load(provider, ["AAA"])
    load(provider, ["BBB"])
    load(provider, ["AAA"])
    load(provider, ["CCC"])
    load(provider, ["AAA"])
    assert factory.call_count == 3
    load(provider, ["BBB"])
    assert factory.call_count == 4
    assert len(provider._cache) == 2


@pytest.mark.parametrize("settings", [{"cache_ttl_seconds": 0}, {"cache_max_entries": 0}])
def test_cache_can_be_disabled(mock_history, settings):
    factory, _ = mock_history()
    provider = YahooFinanceProvider(**settings)
    load(provider)
    load(provider)
    assert factory.call_count == 2
    assert len(provider._cache) == 0


@pytest.mark.parametrize("failure", ["upstream", "invalid"])
def test_failures_are_not_cached(mock_history, failure):
    provider = YahooFinanceProvider()
    if failure == "upstream":
        mock_history(errors={"AAA": YFRateLimitError()})
    else:
        mock_history(frames={"AAA": price_frame().drop(columns="Adj Close")})
    with pytest.raises(PortfolioError):
        load(provider)
    assert len(provider._cache) == 0
    factory, _ = mock_history()
    load(provider)
    factory.assert_called_once_with("AAA")


def test_cache_thread_safety_and_independent_results(mock_history):
    mock_history()
    provider = YahooFinanceProvider(cache_max_entries=2)
    with ThreadPoolExecutor(max_workers=8) as executor:
        datasets = list(executor.map(lambda _: load(provider), range(32)))
    datasets[0].prices.iloc[0, 0] = -1
    assert all(dataset.prices.iloc[0, 0] == 50 for dataset in datasets[1:])
    assert len(provider._cache) <= 2


def test_search_filters_and_maps_quotes(monkeypatch):
    quotes = [
        {
            "symbol": "AAA",
            "quoteType": "EQUITY",
            "longname": "Alpha",
            "shortname": "A",
            "exchDisp": "NYSE",
        },
        {
            "symbol": "BBB",
            "quoteType": "ETF",
            "shortname": "Beta",
            "exchange": "NMS",
            "currency": "USD",
        },
        {"symbol": "AAA", "quoteType": "EQUITY"},
        {"symbol": "BTC-USD", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "EURUSD=X", "quoteType": "CURRENCY"},
        {"symbol": "^GSPC", "quoteType": "INDEX"},
        {"symbol": "FUND", "quoteType": "MUTUALFUND"},
        {"symbol": "UNKNOWN"},
        {"symbol": "BAD SPACE", "quoteType": "EQUITY"},
        {"quoteType": "ETF"},
        {"symbol": "", "quoteType": "ETF"},
        {"symbol": None, "quoteType": "ETF"},
        {"symbol": 5, "quoteType": "ETF"},
        None,
    ]
    search = Mock(return_value=SimpleNamespace(quotes=quotes))
    monkeypatch.setattr(market_data.yf, "Search", search)
    results = YahooFinanceProvider(timeout_seconds=8).search(" alpha ")
    search.assert_called_once_with(
        "alpha", max_results=10, news_count=0, timeout=8, raise_errors=True
    )
    assert [item.symbol for item in results] == ["AAA", "BBB"]
    assert results[0].name == "Alpha"
    assert results[0].exchange == "NYSE"
    assert results[0].currency is None
    assert results[1].name == "Beta"
    assert results[1].instrument_type == "ETF"
    assert results[1].currency == "USD"


def test_search_respects_limit_and_empty_results(monkeypatch):
    search = Mock(
        return_value=SimpleNamespace(
            quotes=[
                {"symbol": "AAA", "quoteType": "EQUITY"},
                {"symbol": "BBB", "quoteType": "ETF"},
            ]
        )
    )
    monkeypatch.setattr(market_data.yf, "Search", search)
    assert len(YahooFinanceProvider().search("a", limit=1)) == 1
    search.return_value.quotes = []
    assert YahooFinanceProvider().search("no match") == []


@pytest.mark.parametrize("error,status", [(YFRateLimitError(), 503), (RuntimeError("secret"), 502)])
def test_search_upstream_errors_are_safe(monkeypatch, error, status):
    monkeypatch.setattr(market_data.yf, "Search", Mock(side_effect=error))
    with pytest.raises(PortfolioError) as raised:
        YahooFinanceProvider().search("alpha")
    assert raised.value.status_code == status
    assert "secret" not in raised.value.message


def test_search_malformed_response(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Search", Mock(return_value=SimpleNamespace(quotes=None)))
    with pytest.raises(PortfolioError) as raised:
        YahooFinanceProvider().search("alpha")
    assert raised.value.code == "invalid_market_data"


@pytest.mark.parametrize("query,limit", [("", 10), ("  ", 10), ("a", 0), ("a", 101), ("a", 1.5)])
def test_search_input_validation(query, limit):
    with pytest.raises(PortfolioError) as raised:
        YahooFinanceProvider().search(query, limit)
    assert raised.value.code == "invalid_search"


@pytest.mark.parametrize(
    "tickers,start,end,currency,code",
    [
        ([], START, END, "USD", "invalid_tickers"),
        (["AAA", "AAA"], START, END, "USD", "invalid_tickers"),
        (["bad symbol"], START, END, "USD", "invalid_tickers"),
        (["AAA"], END, START, "USD", "invalid_dates"),
        (["AAA"], START, START, "USD", "invalid_dates"),
        (["AAA"], START, END, "US", "invalid_currency"),
    ],
)
def test_history_input_validation(tickers, start, end, currency, code):
    with pytest.raises(PortfolioError) as raised:
        YahooFinanceProvider().history(tickers, start, end, currency)
    assert raised.value.code == code


@pytest.mark.parametrize(
    "settings",
    [
        {"cache_ttl_seconds": -1},
        {"cache_ttl_seconds": float("inf")},
        {"cache_max_entries": -1},
        {"cache_max_entries": 1.5},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
    ],
)
def test_cache_and_timeout_configuration_validation(settings):
    with pytest.raises(ValueError):
        YahooFinanceProvider(**settings)
