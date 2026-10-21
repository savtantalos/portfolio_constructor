from datetime import UTC, date, datetime
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Reject unknown fields and non-finite numbers while allowing type coercion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Strategy(str, Enum):
    """Portfolio allocation strategies accepted by the API and analytics engine."""

    EQUAL_WEIGHT = "equal_weight"
    MINIMUM_VARIANCE = "minimum_variance"
    MAXIMUM_SHARPE = "maximum_sharpe"
    BUY_AND_HOLD = "buy_and_hold"
    INVERSE_VOLATILITY = "inverse_volatility"
    EQUAL_RISK_CONTRIBUTION = "equal_risk_contribution"


class ScenarioConfig(StrictModel):
    """Configure block-bootstrap forward scenario simulation.

    Block bootstrapping resamples consecutive blocks of daily returns with
    replacement, preserving cross-asset dependence within each block. Paths
    are projected forward from the last observed price date for horizon_days
    calendar days.
    """

    enabled: bool = False
    horizon_days: int = Field(default=252, ge=21, le=1260)
    block_days: int = Field(default=5, ge=1, le=63)
    paths: int = Field(default=1000, ge=100, le=5000)
    percentile_levels: list[float] = Field(default=[0.05, 0.25, 0.5, 0.75, 0.95])
    random_seed: int | None = None

    @field_validator("percentile_levels")
    @classmethod
    def validate_percentile_levels(cls, value: list[float]) -> list[float]:
        for level in value:
            if not (0 <= level <= 1):
                raise ValueError(f"Each percentile level must be in [0, 1], got {level}")
        return sorted(set(value))


class BacktestConfig(StrictModel):
    """Configure rolling training, rebalance frequency, and trading fees.

    Lookback and rebalance intervals count return observations, not calendar
    days. Transaction costs are basis points of the full traded notional.
    """

    enabled: bool = True
    lookback_days: int = Field(default=252, ge=60, le=1260)
    rebalance_every: int = Field(default=21, ge=1, le=252)
    transaction_cost_bps: float = Field(default=10, ge=0, le=500)


class AnalysisRequest(StrictModel):
    """Validated inputs for long-only, fully invested portfolio analysis.

    Dates bound the requested historical window inclusively. Weight bounds
    apply to each asset's target allocation; rates and weights are fractions,
    not percentages. The risk-free rate is annual. Sampling uses random_seed
    for reproducibility, and backtest settings control walk-forward evaluation.
    """

    tickers: list[Annotated[str, Field(pattern=r"^[A-Z0-9^][A-Z0-9.^=_-]{0,31}$")]] = Field(
        min_length=2, max_length=30
    )
    start_date: date
    end_date: date
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    strategies: list[Strategy] = Field(
        default_factory=lambda: [
            Strategy.EQUAL_WEIGHT,
            Strategy.MINIMUM_VARIANCE,
            Strategy.MAXIMUM_SHARPE,
        ],
        min_length=1,
    )
    benchmark_ticker: Annotated[str, Field(pattern=r"^[A-Z0-9^][A-Z0-9.^=_-]{0,31}$")] | None = None
    min_weight: float = Field(default=0, ge=0, le=1)
    max_weight: float = Field(default=1, gt=0, le=1)
    risk_free_rate: float = Field(default=0.02, gt=-1, le=1)
    monte_carlo_samples: int = Field(default=1000, ge=0, le=5000)
    frontier_points: int = Field(default=20, ge=0, le=50)
    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    random_seed: int = Field(default=42, ge=0, le=2**32 - 1)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)

    @field_validator("benchmark_ticker", mode="before")
    @classmethod
    def normalize_benchmark_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("tickers", mode="before")
    @classmethod
    def normalize_tickers(cls, value: object) -> object:
        """Strip and uppercase list strings before validating ticker constraints.

        Leave other input types unchanged for Pydantic's normal validation.
        """
        if isinstance(value, list):
            return [item.strip().upper() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("base_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        """Normalize a string currency before checking its three-letter format.

        Leave non-string inputs unchanged for Pydantic's type validation.
        """
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        """Check cross-field constraints after individual fields are validated.

        Returns:
            This request if identifiers, dates, and allocation bounds are valid.

        Raises:
            ValueError: If tickers or strategies repeat, dates are unordered,
                future-dated or span over 20 years, or weight bounds cannot
                produce a fully invested portfolio within numerical tolerance.
        """
        if self.benchmark_ticker is not None and not self.backtest.enabled:
            raise ValueError("benchmark_ticker requires an enabled backtest")
        if len(set(self.tickers)) != len(self.tickers):
            raise ValueError("Tickers must be unique")
        if len(set(self.strategies)) != len(self.strategies):
            raise ValueError("Strategies must be unique")
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if self.end_date > datetime.now(UTC).date():
            raise ValueError("end_date cannot be in the future")
        if (self.end_date - self.start_date).days > 366 * 20:
            raise ValueError("The maximum historical window is 20 years")
        count = len(self.tickers)
        if self.min_weight > self.max_weight:
            raise ValueError("min_weight cannot exceed max_weight")
        if count * self.min_weight > 1 + 1e-10 or count * self.max_weight < 1 - 1e-10:
            raise ValueError("Weight bounds are infeasible for the number of assets")
        return self


class Instrument(StrictModel):
    """Provider symbol and optional descriptive, exchange, and currency metadata."""

    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    instrument_type: str | None = None


class RiskMetrics(StrictModel):
    """Annualized arithmetic return, volatility, and optional Sharpe estimate.

    Return and volatility are fractions. Sharpe is None when volatility is too
    small for a meaningful ratio; these are in-sample estimates, not forecasts.
    """

    expected_annual_return: float
    annual_volatility: float
    sharpe_ratio: float | None


class PortfolioPoint(StrictModel):
    """Ticker-indexed fractional allocations and their estimated risk metrics."""

    weights: dict[str, float]
    metrics: RiskMetrics


class PortfolioResult(PortfolioPoint):
    """Strategy allocation with each asset's fraction of total portfolio variance.

    Risk contributions sum to one for nonzero variance and are zero when the
    engine treats portfolio variance as negligible.
    """

    strategy: Strategy
    risk_contributions: dict[str, float]


class EquityPoint(StrictModel):
    """Dated backtest wealth and fractional drawdown from its running peak.

    Wealth starts at one; drawdown is zero at a peak and negative below it.
    """

    date: date
    value: float
    drawdown: float


class RebalanceEvent(StrictModel):
    """Executed target weights, turnover, and fee for one backtest rebalance.

    Turnover is full traded notional divided by pre-trade wealth, not half that
    amount. Transaction cost is an absolute deduction in normalized wealth units.
    """

    date: date
    weights: dict[str, float]
    turnover: float
    transaction_cost: float


class BacktestMetrics(StrictModel):
    """Realized performance and accumulated turnover and fees after trading costs.

    Returns, CAGR, volatility, and drawdown are fractions; maximum drawdown is
    nonpositive. Total transaction cost sums fees in normalized wealth units.
    """

    total_return: float
    cagr: float
    annual_volatility: float
    sharpe_ratio: float | None
    max_drawdown: float
    total_turnover: float
    total_transaction_cost: float
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown_duration_days: int | None = None
    tracking_error: float | None = None
    information_ratio: float | None = None
    excess_total_return: float | None = None


class BacktestResult(StrictModel):
    """One strategy's walk-forward metrics, wealth history, and execution records."""

    strategy: Strategy
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    rebalances: list[RebalanceEvent]


class EstimationSnapshot(StrictModel):
    tickers: list[str]
    expected_annual_returns: list[float]
    optimizer_covariance_annual: list[list[float]]
    annualization_factor: Literal[252] = 252
    mean_estimator: Literal["arithmetic_daily_mean"] = "arithmetic_daily_mean"
    covariance_estimator: Literal["LedoitWolf"] = "LedoitWolf"


class BenchmarkResult(StrictModel):
    ticker: str
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    rebalances: list[RebalanceEvent]


class ScenarioPercentileMetrics(StrictModel):
    """Metrics at a single percentile level across simulated paths."""

    terminal_return: float
    max_drawdown: float
    terminal_wealth: float
    cagr: float | None


class ScenarioFanPath(StrictModel):
    """One percentile trace through the scenario fan chart."""

    percentile: float
    dates: list[str]
    values: list[float]


class ScenarioSummaryStatistics(StrictModel):
    """Cross-path summary statistics for a single portfolio's scenarios."""

    terminal_wealth_mean: float
    terminal_wealth_median: float
    max_drawdown_worst_5pct: float
    terminal_return_5pct: float
    terminal_return_95pct: float


class ScenarioResult(StrictModel):
    """Block-bootstrap scenario output for one portfolio strategy."""

    strategy: Strategy
    weights: dict[str, float]
    percentiles: dict[float, ScenarioPercentileMetrics]
    fan_paths: list[ScenarioFanPath]
    summary_statistics: ScenarioSummaryStatistics


class AnalyticsResult(StrictModel):
    """Allocations, sampled portfolios, frontier, correlations, and backtests.

    Undefined correlations are None. Warnings describe estimation limitations
    and any strategies or results the engine could not produce.
    """

    portfolios: list[PortfolioResult]
    monte_carlo: list[PortfolioPoint]
    efficient_frontier: list[PortfolioPoint]
    correlation: dict[str, dict[str, float | None]]
    backtests: list[BacktestResult]
    benchmark: BenchmarkResult | None = None
    scenarios: list[ScenarioResult] | None = None
    warnings: list[str]
    estimation: EstimationSnapshot | None = None


class AnalysisDataset(StrictModel):
    id: str
    title: str
    category: Literal["Market data", "Risk & estimates", "Portfolios", "Backtests"]
    description: str
    columns: list[str]
    rows: list[list[str | int | float | None]]


class AnalysisData(StrictModel):
    datasets: list[AnalysisDataset]
    notes: list[str]


class PriceSnapshot(StrictModel):
    """Serializable adjusted-price matrix used to reproduce an analysis.

    Producers arrange rows by dates and columns by tickers. This model validates
    field types but does not enforce matrix dimensions or ordering.
    """

    tickers: list[str]
    dates: list[date]
    prices: list[list[float]]


class DataSummary(StrictModel):
    """Market-data provenance, requested and effective windows, and sample sizes.

    The snapshot SHA-256 identifies the canonical serialized price snapshot;
    adjustment records the provider's price-adjustment convention.
    """

    provider: str
    fetched_at: datetime
    requested_start: date
    requested_end: date
    effective_start: date
    effective_end: date
    price_observations: int
    return_observations: int
    currency: str
    adjustment: str
    snapshot_sha256: str
    instruments: list[Instrument]


class AnalysisResponse(StrictModel):
    """Stored analysis with its identity, inputs, provenance, results, and caveats."""

    id: str
    created_at: datetime
    engine_version: str
    request: AnalysisRequest
    data: DataSummary
    results: AnalyticsResult
    assumptions: list[str]
    benchmark_snapshot: PriceSnapshot | None = None
    benchmark_data: DataSummary | None = None


class AnalysisSummary(StrictModel):
    """Lightweight saved-analysis metadata for paginated listing responses."""

    id: str
    created_at: datetime
    tickers: list[str]
    start_date: date
    end_date: date


class ChatMessage(StrictModel):
    """One stored conversation turn as provider-shaped content blocks.

    Content blocks are `text`, `tool_use`, or `tool_result` dictionaries so a
    conversation can be replayed to the model and rendered by the UI.
    """

    id: int
    role: Literal["user", "assistant"]
    content: list[dict]
    created_at: datetime


class ConversationCreate(StrictModel):
    """Optional saved-analysis link for a new conversation."""

    analysis_id: str | None = Field(default=None, min_length=36, max_length=36)


class ConversationSummary(StrictModel):
    """Conversation identity, optional analysis link, and derived title."""

    id: str
    analysis_id: str | None
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    """Conversation summary with its messages in chronological order."""

    messages: list[ChatMessage]


class ChatContext(StrictModel):
    """What the user is looking at when sending a message."""

    analysis_id: str | None = Field(default=None, min_length=36, max_length=36)
    path: str | None = Field(default=None, max_length=200)


class ChatSendRequest(StrictModel):
    """A new user message plus the UI context it was sent from."""

    content: str = Field(min_length=1, max_length=8000)
    context: ChatContext = Field(default_factory=ChatContext)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message cannot be blank")
        return stripped


class AssistantStatus(StrictModel):
    """Whether the assistant is configured and which model it would use."""

    enabled: bool
    model: str


class ErrorDetail(StrictModel):
    """Machine-readable failure code and a human-readable public explanation."""

    code: str
    message: str


class ErrorResponse(StrictModel):
    """JSON envelope for handled domain and database errors."""

    error: ErrorDetail


class HealthResponse(StrictModel):
    """Service liveness and engine version, without dependency-health guarantees."""

    status: Literal["ok"] = "ok"
    version: str
