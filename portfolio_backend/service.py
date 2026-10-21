import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from portfolio_backend import __version__
from portfolio_backend.analytics import analyze
from portfolio_backend.config import Settings
from portfolio_backend.database import AnalysisRepository
from portfolio_backend.errors import PortfolioError
from portfolio_backend.market_types import MarketDataProvider
from portfolio_backend.models import (
    AnalysisRequest,
    AnalysisResponse,
    DataSummary,
    PriceSnapshot,
)

ASSUMPTIONS = [
    "Research tool, not an investment recommendation or a guarantee of future performance.",
    "Long-only, fully invested fractional allocations; no leverage, shorting, taxes, "
    "or whole-share rounding.",
    "Daily dividend- and split-adjusted closing prices; distributions are not added again.",
    "All instruments must share the base currency. FX and currency-subunit conversion "
    "are unsupported.",
    "252 trading observations per year; missing-date alignment can affect this approximation.",
    "Weight bounds apply to target allocations at rebalances, not to weights drifting "
    "between them.",
    "Backtest costs model proportional traded-notional fees only, not market impact or "
    "execution slippage.",
    "Backtests are conditional on today's selected asset list and can contain "
    "selection/survivorship bias.",
    "The data-provider license must permit your intended use, storage, and display of market data.",
]


def perform_analysis(
    payload: AnalysisRequest,
    *,
    market_data: MarketDataProvider,
    repository: AnalysisRepository,
    settings: Settings,
) -> AnalysisResponse:
    """Fetch prices, run the analytics engine, and persist the analysis and snapshot.

    Args:
        payload: Validated assets, date window, allocation, and backtest settings.
        market_data: Provider used to fetch adjusted price history.
        repository: Storage that receives the result and its canonical snapshot.
        settings: Configuration supplying the backtest rebalance budget.

    Returns:
        The saved analysis, including a UUID, UTC timestamp, data provenance,
        combined warnings, and SHA-256 hash of the canonical price snapshot.

    Raises:
        PortfolioError: For excess rebalance budgets or data/analysis errors.
        SQLAlchemyError: If persistence fails.

    Notes:
        Callers are responsible for concurrency limiting. Provider access may
        perform network I/O or update caches.
    """
    symbols = list(payload.tickers)
    if payload.benchmark_ticker and payload.benchmark_ticker not in symbols:
        symbols.append(payload.benchmark_ticker)
    dataset = market_data.history(
        symbols, payload.start_date, payload.end_date, payload.base_currency
    )
    observations = len(dataset.prices)
    if payload.backtest.enabled:
        periods = max(0, observations - payload.backtest.lookback_days - 1)
        rebalances = (
            periods + payload.backtest.rebalance_every - 1
        ) // payload.backtest.rebalance_every
        if rebalances > settings.max_backtest_rebalances:
            raise PortfolioError(
                "backtest_budget_exceeded",
                "This analysis exceeds the backtest rebalance budget. "
                "Increase rebalance_every, shorten the historical window, "
                "or disable backtesting.",
            )
    ordered_prices = dataset.prices.loc[:, payload.tickers]
    benchmark_prices = (
        dataset.prices[payload.benchmark_ticker] if payload.benchmark_ticker else None
    )
    results = analyze(ordered_prices, payload, benchmark_prices)
    results.warnings = dataset.warnings + results.warnings
    if payload.benchmark_ticker:
        results.warnings.append(
            "Portfolio and benchmark use common adjusted-price dates without filling. "
            "Selecting a benchmark can shorten the analysis and training history; "
            "all comparisons use the same net evaluation dates and entry fee. "
            "No terminal liquidation fee is charged."
        )

    def snapshot_for(tickers: list[str]) -> tuple[dict, DataSummary]:
        prices = dataset.prices.loc[:, tickers]
        snapshot = PriceSnapshot(
            tickers=tickers,
            dates=[value.date() for value in prices.index],
            prices=prices.to_numpy(dtype=float).tolist(),
        ).model_dump(mode="json")
        snapshot_hash = hashlib.sha256(json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return snapshot, DataSummary(
            provider=dataset.provider,
            fetched_at=dataset.fetched_at,
            requested_start=payload.start_date,
            requested_end=payload.end_date,
            effective_start=prices.index[0].date(),
            effective_end=prices.index[-1].date(),
            price_observations=observations,
            return_observations=observations - 1,
            currency=payload.base_currency,
            adjustment=dataset.adjustment,
            snapshot_sha256=snapshot_hash,
            instruments=[i for ticker in tickers for i in dataset.instruments
                         if i.symbol == ticker],
        )

    snapshot, data = snapshot_for(payload.tickers)
    benchmark_snapshot, benchmark_data = (
        snapshot_for([payload.benchmark_ticker]) if payload.benchmark_ticker
        else (None, None)
    )
    result = AnalysisResponse(
        id=str(uuid4()),
        created_at=datetime.now(UTC),
        engine_version=__version__,
        request=payload,
        data=data,
        results=results,
        assumptions=ASSUMPTIONS,
        benchmark_snapshot=benchmark_snapshot,
        benchmark_data=benchmark_data,
    )
    repository.save(result, snapshot)
    return result
