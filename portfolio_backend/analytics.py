from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize
from sklearn.covariance import LedoitWolf

from .errors import PortfolioError
from .models import (
    AnalysisRequest,
    AnalyticsResult,
    BacktestMetrics,
    BacktestResult,
    EquityPoint,
    PortfolioPoint,
    PortfolioResult,
    RebalanceEvent,
    RiskMetrics,
    Strategy,
)

_TOL = 1e-7


def _validate(prices: pd.DataFrame, request: AnalysisRequest) -> np.ndarray:
    """Validate daily prices and compute arithmetic returns in ticker order.

    Args:
        prices: Positive price frame of shape (T, N) with unique, increasing
            daily datetime observations and exactly the requested tickers.
        request: Analysis configuration, including any rolling-history needs.

    Returns:
        Decimal simple returns of shape (T - 1, N), ordered by request.tickers.

    Raises:
        PortfolioError: If prices are invalid, fewer than 61 observations exist,
            or an enabled backtest lacks lookback, lag, and realization history.
    """
    if not isinstance(prices, pd.DataFrame) or len(prices) < 61:
        raise PortfolioError(
            "invalid_prices", "At least 61 complete daily price observations are required."
        )
    if (
        not isinstance(prices.index, pd.DatetimeIndex)
        or prices.index.hasnans
        or not prices.index.is_monotonic_increasing
        or not prices.index.is_unique
        or not prices.index.normalize().is_unique
    ):
        raise PortfolioError(
            "invalid_prices",
            "Prices must have unique, strictly increasing daily datetime observations.",
        )
    if not prices.columns.is_unique or set(prices.columns) != set(request.tickers):
        raise PortfolioError(
            "invalid_prices", "Price columns must match the requested tickers exactly."
        )
    try:
        values = prices.loc[:, request.tickers].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise PortfolioError("invalid_prices", "Prices must be numeric.") from exc
    if not np.isfinite(values).all() or (values <= 0).any():
        raise PortfolioError(
            "invalid_prices",
            "Prices must be finite and strictly positive, without missing observations.",
        )
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        returns = values[1:] / values[:-1] - 1
    if not np.isfinite(returns).all():
        raise PortfolioError(
            "invalid_prices", "Price ratios must produce finite arithmetic returns."
        )
    if request.backtest.enabled and len(prices) < request.backtest.lookback_days + 3:
        raise PortfolioError(
            "insufficient_history",
            f"Backtesting with lookback_days={request.backtest.lookback_days} requires at least "
            f"{request.backtest.lookback_days + 3} price observations: lookback returns, "
            "one execution-lag "
            "observation, and at least one subsequent realized return.",
        )
    return returns


def _estimate(returns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Estimate annual arithmetic means and Ledoit-Wolf covariance.

    Args:
        returns: Daily decimal simple returns of shape (observations, assets).

    Returns:
        Mean vector of shape (assets,) and symmetric covariance matrix of
        shape (assets, assets), each scaled by 252 trading observations/year.

    Raises:
        PortfolioError: If moment estimation fails or yields nonfinite values.
    """
    returns = np.ascontiguousarray(returns, dtype=float)
    try:
        with np.errstate(over="raise", invalid="raise"):
            mu = returns.mean(axis=0) * 252
            covariance = LedoitWolf().fit(returns).covariance_ * 252
    except (ValueError, FloatingPointError, OverflowError) as exc:
        raise PortfolioError(
            "invalid_prices", "Returns are too large for stable finite moment estimates."
        ) from exc
    if not np.isfinite(mu).all() or not np.isfinite(covariance).all():
        raise PortfolioError("invalid_prices", "Returns are too large for finite moment estimates.")
    return mu, covariance / 2 + covariance.T / 2


def _valid_weights(weights: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> bool:
    """Check finite asset weights, unit sum, and elementwise bounds within _TOL."""
    return bool(
        np.isfinite(weights).all()
        and abs(weights.sum() - 1) <= _TOL
        and np.all(weights >= lower - _TOL)
        and np.all(weights <= upper + _TOL)
    )


def _solve(
    objective: Callable,
    gradient: Callable,
    initial: np.ndarray,
    bounds: list[tuple[float, float]],
    constraints: list[dict],
    label: str,
) -> np.ndarray:
    """Run a gradient-supplied constrained SLSQP minimization.

    Args:
        objective: Scalar objective evaluated on the optimization vector.
        gradient: Objective gradient with the same shape as that vector.
        initial: One-dimensional starting vector.
        bounds: Per-variable lower and upper bounds accepted by SciPy.
        constraints: SciPy equality/inequality constraint dictionaries.
        label: Problem name used in error messages.

    Returns:
        Finite solution vector; callers separately check financial feasibility.

    Raises:
        PortfolioError: If optimization raises a numeric error, fails to
            converge successfully, or returns nonfinite coordinates.
    """
    try:
        result = minimize(
            objective,
            initial,
            jac=gradient,
            bounds=bounds,
            constraints=constraints,
            method="SLSQP",
            options={"ftol": 1e-12, "maxiter": 1000},
        )
    except (ValueError, ArithmeticError) as exc:
        raise PortfolioError(
            "optimization_failed",
            f"{label} optimizer could not solve the constrained problem: {exc}",
        ) from exc
    if not result.success or not np.isfinite(result.x).all():
        raise PortfolioError(
            "optimization_failed", f"{label} optimization failed: {result.message}"
        )
    return result.x


def _max_return(
    mu: np.ndarray, lower: np.ndarray, upper: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Greedily maximize linear return over a feasible bounded weight simplex.

    Args:
        mu: Expected returns or excess returns of shape (assets,).
        lower: Feasible per-asset minimum weight fractions.
        upper: Feasible per-asset maximum weight fractions.

    Returns:
        Maximizing weights and lower/upper bounds defining the maximizing
        face, each of shape (assets,). Tied marginal assets share remaining
        capital in proportion to their available capacity.
    """
    weights = lower.copy()
    face_lower = lower.copy()
    face_upper = upper.copy()
    remaining = 1 - weights.sum()
    for value in np.unique(mu)[::-1]:
        group = np.flatnonzero(mu == value)
        capacity = float((upper[group] - lower[group]).sum())
        if remaining >= capacity:
            weights[group] = upper[group]
            face_lower[group] = upper[group]
            remaining -= capacity
        elif remaining > 0:
            weights[group] += remaining * (upper[group] - lower[group]) / capacity
            remaining = 0
        else:
            face_upper[group] = lower[group]
    return weights, face_lower, face_upper


def _minimum_variance(
    covariance: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    initial: np.ndarray,
    mu: np.ndarray | None = None,
    target: float | None = None,
) -> np.ndarray:
    """Minimize portfolio variance subject to bounds and an optional return floor.

    Args:
        covariance: Annual return covariance of shape (N, N).
        lower: Minimum weight fractions of shape (N,).
        upper: Maximum weight fractions of shape (N,).
        initial: Feasible starting allocation of shape (N,).
        mu: Annual arithmetic return vector, required when target is supplied.
        target: Optional minimum annual portfolio return, expressed as a decimal.

    Returns:
        Fully invested asset weights of shape (N,).

    Raises:
        PortfolioError: If optimization fails or the result violates bounds,
            unit-sum weights, or the return floor beyond numerical tolerance.
    """
    if (
        np.max(upper - lower) < 1e-12
        or min(1 - lower.sum(), upper.sum() - 1) <= 1e-12
        or (np.max(np.abs(covariance)) == 0 and target is None)
    ):
        weights = initial.copy()
    else:
        scaled = covariance / max(float(np.max(np.abs(covariance))), 1e-30)
        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(len(w))}
        ]
        if target is not None:
            scale = max(float(np.ptp(mu)), abs(target), 1e-8)
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w: (mu @ w - target) / scale,
                    "jac": lambda w: mu / scale,
                }
            )
        weights = _solve(
            lambda w: float(w @ scaled @ w),
            lambda w: 2 * scaled @ w,
            initial,
            list(zip(lower, upper, strict=False)),
            constraints,
            "Minimum variance",
        )
    if not _valid_weights(weights, lower, upper) or (
        target is not None and mu @ weights < target - _TOL
    ):
        raise PortfolioError(
            "optimization_failed", "Minimum variance optimizer returned an infeasible portfolio."
        )
    return weights


def _weights(
    strategy: Strategy, mu: np.ndarray, covariance: np.ndarray, request: AnalysisRequest
) -> np.ndarray:
    """Construct equal-weight, minimum-variance, or maximum-Sharpe allocations.

    Maximum Sharpe uses a positive-excess-return quadratic transformation,
    then normalizes the solution to fully invested weights.

    Args:
        strategy: Allocation rule to apply.
        mu: Annual arithmetic decimal returns of shape (N,).
        covariance: Annual return covariance of shape (N, N).
        request: Validated weight bounds and annual decimal risk-free rate.

    Returns:
        Asset weight fractions of shape (N,) in requested ticker order.

    Raises:
        PortfolioError: If no feasible positive excess return exists for
            maximum Sharpe, or optimization fails or produces infeasible weights.
    """
    count = len(mu)
    equal = np.full(count, 1 / count)
    lower = np.full(count, request.min_weight, dtype=float)
    upper = np.full(count, request.max_weight, dtype=float)
    if strategy == Strategy.EQUAL_WEIGHT:
        return equal
    if strategy == Strategy.MINIMUM_VARIANCE:
        return _minimum_variance(covariance, lower, upper, equal)
    excess = mu - request.risk_free_rate
    best, _, _ = _max_return(excess, lower, upper)
    positive_excess = float(excess @ best)
    if positive_excess <= 1e-12:
        raise PortfolioError(
            "no_positive_excess_return",
            "Maximum Sharpe omitted: no feasible portfolio has positive estimated excess return "
            "under the weight bounds.",
        )
    if np.max(upper - lower) < 1e-12 or min(1 - lower.sum(), upper.sum() - 1) <= 1e-12:
        return equal
    scaled_excess = excess / positive_excess
    scaled_covariance = covariance / max(float(np.max(np.abs(covariance))), 1e-30)
    count_identity = np.eye(count)
    lower_matrix = count_identity - lower[:, None]
    upper_matrix = upper[:, None] - count_identity
    transformed = _solve(
        lambda y: float(y @ scaled_covariance @ y),
        lambda y: 2 * scaled_covariance @ y,
        best,
        [(0, None)] * count,
        [
            {"type": "eq", "fun": lambda y: scaled_excess @ y - 1, "jac": lambda y: scaled_excess},
            {"type": "ineq", "fun": lambda y: lower_matrix @ y, "jac": lambda y: lower_matrix},
            {"type": "ineq", "fun": lambda y: upper_matrix @ y, "jac": lambda y: upper_matrix},
        ],
        "Maximum Sharpe",
    )
    if transformed.sum() <= 0 or abs(scaled_excess @ transformed - 1) > _TOL:
        raise PortfolioError(
            "optimization_failed",
            "Maximum Sharpe optimizer returned an infeasible transformed portfolio.",
        )
    weights = transformed / transformed.sum()
    if not _valid_weights(weights, lower, upper) or excess @ weights <= 0:
        raise PortfolioError(
            "optimization_failed", "Maximum Sharpe optimizer returned an infeasible portfolio."
        )
    return weights


def _point(
    weights: np.ndarray, mu: np.ndarray, covariance: np.ndarray, request: AnalysisRequest
) -> PortfolioPoint:
    """Package ticker weights and annual decimal return/volatility estimates.

    The weight and mean vectors have shape (N,) and annual covariance has
    shape (N, N), all in request ticker order. Sharpe uses the annual decimal
    risk-free rate and is None when volatility is at most 1e-12.
    """
    variance = max(float(weights @ covariance @ weights), 0)
    volatility = float(np.sqrt(variance))
    expected = float(mu @ weights)
    return PortfolioPoint(
        weights=dict(zip(request.tickers, weights.tolist(), strict=False)),
        metrics=RiskMetrics(
            expected_annual_return=expected,
            annual_volatility=volatility,
            sharpe_ratio=(expected - request.risk_free_rate) / volatility
            if volatility > 1e-12
            else None,
        ),
    )


def _frontier(
    mu: np.ndarray, covariance: np.ndarray, request: AnalysisRequest
) -> list[PortfolioPoint]:
    """Trace the bounded efficient frontier from minimum variance to maximum return.

    Args:
        mu: Annual arithmetic decimal returns of shape (N,).
        covariance: Annual return covariance of shape (N, N).
        request: Weight bounds, ticker order, risk-free rate, and point count.

    Returns:
        Portfolios at evenly spaced return floors, with minimum variance on
        the maximum-return face as the endpoint. Returns no points when
        disabled and one point for a collapsed return range or count of one.

    Raises:
        PortfolioError: If a required constrained optimization fails.
    """
    if request.frontier_points == 0:
        return []
    lower = np.full(len(mu), request.min_weight, dtype=float)
    upper = np.full(len(mu), request.max_weight, dtype=float)
    start = _minimum_variance(covariance, lower, upper, np.full(len(mu), 1 / len(mu)))
    extreme, face_lower, face_upper = _max_return(mu, lower, upper)
    low, high = float(mu @ start), float(mu @ extreme)
    if high - low <= 1e-12 or request.frontier_points == 1:
        return [_point(start, mu, covariance, request)]
    points = [_point(start, mu, covariance, request)]
    for target in np.linspace(low, high, request.frontier_points)[1:-1]:
        fraction = (target - low) / (high - low)
        initial = start * (1 - fraction) + extreme * fraction
        weights = _minimum_variance(covariance, lower, upper, initial, mu, float(target))
        points.append(_point(weights, mu, covariance, request))
    endpoint = _minimum_variance(covariance, face_lower, face_upper, extreme)
    points.append(_point(endpoint, mu, covariance, request))
    return points


def _sample(request: AnalysisRequest) -> list[np.ndarray]:
    """Draw seeded hit-and-run allocations within the bounded unit simplex.

    Args:
        request: Validated asset count, weight bounds, sample count, and seed.

    Returns:
        Weight vectors of shape (assets,). Uses 20 * assets burn-in steps
        and 3 * assets thinning; finite-chain draws remain correlated and
        are not guaranteed independent uniform samples. Degenerate bounds
        repeat the sole allocation; a zero sample count returns an empty list.

    Raises:
        PortfolioError: If numerical errors yield an empty step interval or
            infeasible sampled weights.
    """
    count = len(request.tickers)
    samples = request.monte_carlo_samples
    if samples == 0:
        return []
    current = np.full(count, 1 / count)
    lower, upper = request.min_weight, request.max_weight
    if min(1 - count * lower, count * upper - 1) <= 1e-12:
        return [current.copy() for _ in range(samples)]
    rng = np.random.default_rng(request.random_seed)
    result = []
    burn_in, thinning = 20 * count, 3 * count
    for step in range(burn_in + samples * thinning):
        norm = 0.0
        while norm <= 1e-15:
            direction = rng.normal(size=count)
            direction -= direction.mean()
            norm = float(np.linalg.norm(direction))
        direction /= norm
        positive, negative = direction > 1e-15, direction < -1e-15
        minimum = max(
            float(np.max((lower - current[positive]) / direction[positive])),
            float(np.max((upper - current[negative]) / direction[negative])),
        )
        maximum = min(
            float(np.min((upper - current[positive]) / direction[positive])),
            float(np.min((lower - current[negative]) / direction[negative])),
        )
        if maximum < minimum:
            raise PortfolioError(
                "sampling_failed", "Numerical failure while sampling the bounded weight simplex."
            )
        current = current + rng.uniform(minimum, maximum) * direction
        current += (1 - current.sum()) / count
        if step >= burn_in and (step - burn_in) % thinning == 0:
            if not _valid_weights(current, np.full(count, lower), np.full(count, upper)):
                raise PortfolioError("sampling_failed", "Sampler produced an infeasible portfolio.")
            result.append(current.copy())
    return result


def _post_fee_wealth(holdings: np.ndarray, target: np.ndarray, fee_rate: float) -> float:
    before = float(holdings.sum())
    if not np.isfinite(before) or before <= 0:
        raise PortfolioError("backtest_failed", "Backtest wealth became nonpositive or nonfinite.")
    if not fee_rate:
        return before
    try:
        after = brentq(
            lambda wealth: wealth + fee_rate * np.abs(wealth * target - holdings).sum() - before,
            0,
            before,
            xtol=1e-14,
        )
    except (ValueError, RuntimeError, ArithmeticError) as exc:
        raise PortfolioError("backtest_failed", f"Transaction cost solver failed: {exc}") from exc
    if not np.isfinite(after) or after <= 0:
        raise PortfolioError(
            "backtest_failed", "Transaction cost solver returned nonpositive or nonfinite wealth."
        )
    return float(after)


def _backtest(
    returns: np.ndarray,
    dates: pd.DatetimeIndex,
    strategy: Strategy,
    request: AnalysisRequest,
) -> BacktestResult:
    """Simulate rolling allocations with lagged close execution and trading fees.

    At execution date dates[i], estimation uses lookback returns ending at
    dates[i - 1], excluding the return into the execution close. Initial
    wealth is cash until entry; target holdings earn only subsequent returns
    and drift between rebalances counted in trading observations.

    Args:
        returns: Decimal simple returns of shape (T - 1, N); row j spans
            dates[j] to dates[j + 1], in requested ticker order.
        dates: The T price observation dates.
        strategy: Allocation rule refitted at each rebalance.
        request: Lookback, rebalance interval, transaction costs in basis
            points, weight bounds, and annual decimal risk-free rate.

    Returns:
        Net equity, rebalance records, and realized metrics. NAV and costs
        are in initial-wealth units with NAV starting at one. Entry turnover
        is one; later turnover is full traded notional/pretrade NAV and fees
        solve self-financing post-fee target holdings. CAGR uses calendar
        days/365.25; volatility uses sample daily standard deviation times
        sqrt(252), and Sharpe subtracts risk_free_rate/252 from daily returns.
        Drawdown is a nonpositive fraction of the running peak.

    Raises:
        PortfolioError: If estimation or allocation fails, or simulated
            wealth becomes nonpositive or nonfinite.
    """
    config = request.backtest
    first = config.lookback_days + 1
    fee_rate = config.transaction_cost_bps / 10000
    holdings = np.zeros(len(request.tickers))
    values = [1.0]
    equity = [EquityPoint(date=dates[first - 1].date(), value=1, drawdown=0)]
    events = []
    peak = 1.0
    for index in range(first, len(dates)):
        if index > first:
            holdings *= 1 + returns[index - 1]
        if (index - first) % config.rebalance_every == 0:
            history = returns[index - config.lookback_days - 1 : index - 1]
            mu, covariance = _estimate(history)
            target = _weights(strategy, mu, covariance, request)
            if index == first:
                turnover, cost, after = 1.0, fee_rate, 1 - fee_rate
            else:
                before = float(holdings.sum())
                after = _post_fee_wealth(holdings, target, fee_rate)
                notional = float(np.abs(after * target - holdings).sum())
                turnover = notional / before
                cost = fee_rate * notional
            holdings = after * target
            events.append(
                RebalanceEvent(
                    date=dates[index].date(),
                    weights=dict(zip(request.tickers, target.tolist(), strict=False)),
                    turnover=turnover,
                    transaction_cost=cost,
                )
            )
        value = float(holdings.sum())
        if not np.isfinite(value) or value <= 0:
            raise PortfolioError(
                "backtest_failed", "Backtest wealth became nonpositive or nonfinite."
            )
        peak = max(peak, value)
        values.append(value)
        equity.append(EquityPoint(date=dates[index].date(), value=value, drawdown=value / peak - 1))
    net_returns = np.asarray(values[1:]) / np.asarray(values[:-1]) - 1
    standard_deviation = float(np.std(net_returns, ddof=1))
    volatility = standard_deviation * np.sqrt(252)
    elapsed = (equity[-1].date - equity[0].date).days
    with np.errstate(over="ignore", invalid="ignore"):
        cagr = float(np.expm1(np.log(values[-1]) * 365.25 / elapsed))
    if not np.isfinite(cagr):
        raise PortfolioError("backtest_failed", "Backtest CAGR became nonfinite.")
    return BacktestResult(
        strategy=strategy,
        metrics=BacktestMetrics(
            total_return=values[-1] - 1,
            cagr=cagr,
            annual_volatility=float(volatility),
            sharpe_ratio=float(
                (net_returns.mean() - request.risk_free_rate / 252) * 252 / volatility
            )
            if volatility > 1e-12
            else None,
            max_drawdown=min(point.drawdown for point in equity),
            total_turnover=sum(event.turnover for event in events),
            total_transaction_cost=sum(event.transaction_cost for event in events),
        ),
        equity_curve=equity,
        rebalances=events,
    )


def analyze(prices: pd.DataFrame, request: AnalysisRequest) -> AnalyticsResult:
    """Analyze historical portfolio allocations and optional lagged backtests.

    Args:
        prices: Complete positive daily price frame of shape (T, N), with
            increasing unique dates and exactly the requested ticker columns.
            Adjusted prices in a common currency are expected from the caller.
        request: Validated strategies, fractional weight bounds, annual
            decimal risk-free rate, sampling, frontier, and backtest settings.

    Returns:
        In-sample portfolios, frontier, sampled portfolios, daily-return
        correlations, optional backtests, and warnings. Means and Ledoit-Wolf
        covariance use 252 observations/year. Risk contributions are signed
        fractions of portfolio variance, or zero for negligible variance;
        undefined correlations and zero-volatility Sharpe ratios are None.
        Backtests fit only history preceding each execution close. In-sample
        maximum Sharpe is omitted with a warning if no positive excess return
        is feasible; any rolling PortfolioError omits that strategy's backtest.

    Raises:
        PortfolioError: If prices/history are invalid, estimation or sampling
            fails, or a non-omitted optimization/backtest fails.
    """
    returns = _validate(prices, request)
    mu, covariance = _estimate(returns)
    warnings = [
        "Estimates use arithmetic daily returns, annual arithmetic means and Ledoit-Wolf "
        "covariance scaled by 252; risk contributions are fractions of portfolio variance "
        "(zero for zero variance).",
        "Historical estimates and the constrained efficient frontier are in-sample estimates, "
        "not forecasts or guaranteed outcomes.",
    ]
    portfolios = []
    for strategy in request.strategies:
        try:
            weights = _weights(strategy, mu, covariance, request)
        except PortfolioError as exc:
            if strategy == Strategy.MAXIMUM_SHARPE and exc.code == "no_positive_excess_return":
                warnings.append(exc.message)
                continue
            raise
        point = _point(weights, mu, covariance, request)
        variance = float(weights @ covariance @ weights)
        contributions = (
            weights * (covariance @ weights) / variance
            if variance > 1e-24
            else np.zeros(len(weights))
        )
        portfolios.append(
            PortfolioResult(
                **point.model_dump(),
                strategy=strategy,
                risk_contributions=dict(zip(request.tickers, contributions.tolist(), strict=False)),
            )
        )
    frontier = _frontier(mu, covariance, request)
    samples = [_point(weights, mu, covariance, request) for weights in _sample(request)]
    if samples:
        warnings.append(
            "Monte Carlo uses seeded hit-and-run sampling of the bounded simplex with finite "
            "burn-in and thinning; samples remain correlated and are not guaranteed independent "
            "uniform draws or true optimized portfolios. Degenerate bounds repeat the sole "
            "feasible allocation."
        )
    correlation_frame = pd.DataFrame(returns, columns=request.tickers).corr()
    correlation = {
        ticker: {
            other: float(correlation_frame.loc[ticker, other])
            if pd.notna(correlation_frame.loc[ticker, other])
            else None
            for other in request.tickers
        }
        for ticker in request.tickers
    }
    backtests = []
    if request.backtest.enabled:
        warnings.append(
            "Backtests fit rolling lookback returns through the observation before execution "
            "close, then earn subsequent returns; holdings drift between trading-observation "
            "rebalances. NAV starts at 1 on the preceding close and remains cash until entry. "
            "Entry turnover is 1 and its fee is charged on initial capital before investing the "
            "remainder. Subsequent fees solve self-financing post-fee target holdings using full "
            "traded notional, not half turnover; turnover divides notional by pretrade NAV and "
            "costs are in initial-wealth units. CAGR uses actual calendar days/365.25; realized "
            "volatility uses sample daily standard deviation times sqrt(252), and Sharpe subtracts "
            "annual risk-free rate/252 from daily net returns."
        )
        for strategy in request.strategies:
            try:
                backtests.append(_backtest(returns, prices.index, strategy, request))
            except PortfolioError as exc:
                if strategy == Strategy.MAXIMUM_SHARPE:
                    warnings.append(
                        "Maximum Sharpe backtest omitted because a rolling window failed: "
                        f"{exc.message}"
                    )
                    continue
                raise
    return AnalyticsResult(
        portfolios=portfolios,
        monte_carlo=samples,
        efficient_frontier=frontier,
        correlation=correlation,
        backtests=backtests,
        warnings=warnings,
    )
