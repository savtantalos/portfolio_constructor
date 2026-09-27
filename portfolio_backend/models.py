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
    strategies: list[Strategy] = Field(default_factory=lambda: list(Strategy), min_length=1)
    min_weight: float = Field(default=0, ge=0, le=1)
    max_weight: float = Field(default=1, gt=0, le=1)
    risk_free_rate: float = Field(default=0.02, gt=-1, le=1)
    monte_carlo_samples: int = Field(default=1000, ge=0, le=5000)
    frontier_points: int = Field(default=20, ge=0, le=50)
    random_seed: int = Field(default=42, ge=0, le=2**32 - 1)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)

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


class BacktestResult(StrictModel):
    """One strategy's walk-forward metrics, wealth history, and execution records."""

    strategy: Strategy
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    rebalances: list[RebalanceEvent]


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
    warnings: list[str]


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


class AnalysisSummary(StrictModel):
    """Lightweight saved-analysis metadata for paginated listing responses."""

    id: str
    created_at: datetime
    tickers: list[str]
    start_date: date
    end_date: date


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
