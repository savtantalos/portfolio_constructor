import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from portfolio_backend.analytics import _backtest, _backtest_metrics, _weights, analyze
from portfolio_backend.errors import PortfolioError
from portfolio_backend.models import (
    AnalysisRequest,
    AnalyticsResult,
    BacktestConfig,
    BacktestMetrics,
    EquityPoint,
    RebalanceEvent,
    Strategy,
)


def prices_from_returns(returns):
    """Compound asset returns from 100 into a business-day price frame."""
    returns = np.asarray(returns)
    values = np.vstack([np.ones(returns.shape[1]), np.cumprod(1 + returns, axis=0)]) * 100
    return pd.DataFrame(
        values,
        index=pd.bdate_range("2020-01-01", periods=len(values)),
        columns=[f"A{i}" for i in range(returns.shape[1])],
    )


def synthetic_prices(count=180, assets=3, seed=17):
    """Generate seeded prices with asset-specific normal return means and scales."""
    rng = np.random.default_rng(seed)
    return prices_from_returns(
        rng.normal(
            np.linspace(0.0003, 0.002, assets),
            np.linspace(0.005, 0.02, assets),
            size=(count - 1, assets),
        )
    )


def request_for(prices, **kwargs):
    """Build a matching analysis request with small sample counts and overridable defaults."""
    options = dict(
        tickers=prices.columns.tolist(),
        start_date=prices.index[0].date(),
        end_date=prices.index[-1].date(),
        backtest=BacktestConfig(enabled=False),
        monte_carlo_samples=12,
        frontier_points=7,
        risk_free_rate=0,
    )
    options.update(kwargs)
    return AnalysisRequest(**options)


def assert_feasible(points, lower, upper):
    """Assert finite, fully invested weights within the given bounds and tolerance."""
    for point in points:
        weights = np.array(list(point.weights.values()))
        assert np.isfinite(weights).all()
        assert weights.sum() == pytest.approx(1, abs=1e-7)
        assert weights.min() >= lower - 1e-7
        assert weights.max() <= upper + 1e-7


def test_deterministic_bounded_analysis_and_efficient_frontier():
    """Bounded results repeat exactly, with feasible weights and correct frontier endpoints."""
    prices = synthetic_prices()
    request = request_for(prices, min_weight=0.15, max_weight=0.55)
    result = analyze(prices, request)
    assert result == analyze(prices, request)
    assert len(result.portfolios) == 3
    assert len(result.monte_carlo) == 12
    assert len(result.efficient_frontier) == 7
    assert_feasible(result.portfolios + result.monte_carlo + result.efficient_frontier, 0.15, 0.55)
    minimum = next(p for p in result.portfolios if p.strategy == Strategy.MINIMUM_VARIANCE)
    assert result.efficient_frontier[0].metrics.annual_volatility == pytest.approx(
        minimum.metrics.annual_volatility
    )
    means = prices.pct_change().iloc[1:].mean().to_numpy() * 252
    expected_maximum = np.sort(means) @ np.array([0.15, 0.30, 0.55])
    assert result.efficient_frontier[-1].metrics.expected_annual_return == pytest.approx(
        expected_maximum
    )
    assert all(
        p.metrics.expected_annual_return >= minimum.metrics.expected_annual_return - 1e-7
        for p in result.efficient_frontier
    )
    assert np.diff([p.metrics.annual_volatility for p in result.efficient_frontier]).min() >= -1e-7
    for portfolio in result.portfolios:
        assert sum(portfolio.risk_contributions.values()) == pytest.approx(1)


def test_arithmetic_means_and_shrunk_covariance():
    """Equal-weight metrics use annualized arithmetic means and Ledoit-Wolf covariance."""
    from sklearn.covariance import LedoitWolf

    prices = synthetic_prices()
    result = analyze(prices, request_for(prices, strategies=[Strategy.EQUAL_WEIGHT]))
    returns = prices.pct_change().iloc[1:].to_numpy()
    weights = np.full(3, 1 / 3)
    metrics = result.portfolios[0].metrics
    assert metrics.expected_annual_return == pytest.approx(returns.mean(axis=0).mean() * 252)
    covariance = LedoitWolf().fit(returns).covariance_ * 252
    assert metrics.annual_volatility == pytest.approx(np.sqrt(weights @ covariance @ weights))


def test_flat_prices_undefined_metrics_and_correlation():
    """Flat prices yield zero risk, undefined ratios and correlations, and no Sharpe portfolio."""
    prices = prices_from_returns(np.zeros((90, 3)))
    result = analyze(prices, request_for(prices))
    assert len(result.portfolios) == 2
    assert len(result.efficient_frontier) == 1
    for portfolio in result.portfolios:
        assert portfolio.metrics.annual_volatility == 0
        assert portfolio.metrics.sharpe_ratio is None
        assert list(portfolio.risk_contributions.values()) == [0, 0, 0]
    assert all(value is None for row in result.correlation.values() for value in row.values())
    assert any("no feasible" in warning for warning in result.warnings)


def test_duplicate_and_constant_assets_have_stable_covariance():
    """Duplicate and constant assets retain feasible portfolios and meaningful correlation nulls."""
    rng = np.random.default_rng(42)
    shared = rng.normal(0.002, 0.01, 150)
    prices = prices_from_returns(np.column_stack([shared, shared, np.zeros(150)]))
    result = analyze(prices, request_for(prices))
    assert_feasible(result.portfolios + result.efficient_frontier, 0, 1)
    assert result.correlation["A0"]["A1"] == pytest.approx(1)
    assert result.correlation["A2"]["A2"] is None


def test_maximum_sharpe_checks_feasible_excess_not_best_individual_asset():
    """Omit maximum Sharpe when bounds preclude positive excess despite a profitable asset."""
    prices = prices_from_returns(np.tile([0.001, -0.002], (90, 1)))
    request = request_for(prices, min_weight=0.4, max_weight=0.6)
    result = analyze(prices, request)
    assert {p.strategy for p in result.portfolios} == {
        Strategy.EQUAL_WEIGHT,
        Strategy.MINIMUM_VARIANCE,
    }
    assert any("positive estimated excess" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "minimum,maximum", [(0.3333332, 0.3333335), (1 / 3, 1 / 3), (1 / 3, 0.8), (0, 1 / 3)]
)
def test_tight_and_degenerate_bounds(minimum, maximum):
    """Nearly fixed and fixed weights remain feasible without reducing the sample count."""
    prices = synthetic_prices()
    request = request_for(prices, min_weight=minimum, max_weight=maximum, monte_carlo_samples=30)
    result = analyze(prices, request)
    assert len(result.monte_carlo) == 30
    assert_feasible(
        result.portfolios + result.monte_carlo + result.efficient_frontier, minimum, maximum
    )


def test_zero_requested_samples_and_frontier_points():
    """Zero requested counts produce empty Monte Carlo and frontier results."""
    prices = synthetic_prices()
    result = analyze(prices, request_for(prices, monte_carlo_samples=0, frontier_points=0))
    assert result.monte_carlo == []
    assert result.efficient_frontier == []


@pytest.mark.parametrize(
    "corruption",
    ["short", "reverse", "duplicate", "missing", "zero", "negative", "infinite", "columns"],
)
def test_invalid_prices_raise_domain_errors(corruption):
    """Reject short, misindexed, mismatched, or invalid-valued prices with a domain error."""
    prices = synthetic_prices()
    request = request_for(prices)
    if corruption == "short":
        prices = prices.iloc[:60]
    elif corruption == "reverse":
        prices = prices.iloc[::-1]
    elif corruption == "duplicate":
        prices.index = pd.DatetimeIndex([prices.index[0]] + prices.index[:-1].tolist())
    elif corruption == "columns":
        prices = prices.rename(columns={"A0": "WRONG"})
    else:
        prices.iloc[2, 0] = {"missing": np.nan, "zero": 0, "negative": -1, "infinite": np.inf}[
            corruption
        ]
    with pytest.raises(PortfolioError, match=".") as error:
        analyze(prices, request)
    assert error.value.code == "invalid_prices"


def test_insufficient_backtest_history_is_not_silently_skipped():
    """A 60-day lookback requires 63 prices rather than silently omitting the backtest."""
    prices = synthetic_prices(count=62)
    request = request_for(prices, backtest=BacktestConfig(lookback_days=60))
    with pytest.raises(PortfolioError, match="63 price observations") as error:
        analyze(prices, request)
    assert error.value.code == "insufficient_history"


def test_backtest_execution_lag_and_no_future_leakage():
    """Lagged rebalances use only training prices; future changes leave prior results intact."""
    prices = synthetic_prices(count=105)
    request = request_for(
        prices,
        strategies=[Strategy.MINIMUM_VARIANCE],
        backtest=BacktestConfig(lookback_days=60, rebalance_every=10, transaction_cost_bps=0),
        frontier_points=0,
        monte_carlo_samples=0,
    )
    original = analyze(prices, request).backtests[0]
    modified = prices.copy()
    modified.iloc[61:, 0] *= 1.5
    changed = analyze(modified, request).backtests[0]
    assert original.rebalances[0].date == prices.index[61].date()
    assert original.rebalances[0].weights == changed.rebalances[0].weights
    assert original.equity_curve[:2] == changed.equity_curve[:2]
    later = prices.copy()
    later.iloc[85:, 1] *= 1.3
    later_result = analyze(later, request).backtests[0]
    assert [p for p in original.equity_curve if p.date < prices.index[85].date()] == [
        p for p in later_result.equity_curve if p.date < prices.index[85].date()
    ]
    assert [p for p in original.rebalances if p.date <= prices.index[85].date()] == [
        p for p in later_result.rebalances if p.date <= prices.index[85].date()
    ]
    training = prices.iloc[:61]
    training_result = analyze(
        training,
        request_for(
            training,
            strategies=[Strategy.MINIMUM_VARIANCE],
            monte_carlo_samples=0,
            frontier_points=0,
        ),
    )
    assert original.rebalances[0].weights == training_result.portfolios[0].weights


def test_drifting_holdings_and_exact_full_notional_rebalance_costs():
    """Drifting holdings incur exact traded-notional costs and yield consistent realized metrics."""
    returns = np.zeros((65, 2))
    returns[61] = [0.2, 0]
    returns[62] = [0.1, 0]
    prices = prices_from_returns(returns)
    request = request_for(
        prices,
        strategies=[Strategy.EQUAL_WEIGHT],
        monte_carlo_samples=0,
        frontier_points=0,
        backtest=BacktestConfig(lookback_days=60, rebalance_every=2, transaction_cost_bps=100),
    )
    result = analyze(prices, request).backtests[0]
    assert result.equity_curve[0].value == 1
    assert result.equity_curve[1].value == pytest.approx(0.99)
    assert result.rebalances[0].turnover == 1
    assert result.rebalances[0].transaction_cost == pytest.approx(0.01)
    assert result.equity_curve[2].value == pytest.approx(0.99 * 1.1)
    before_holdings = np.array([0.495 * 1.2 * 1.1, 0.495])
    after = result.equity_curve[3].value
    traded = np.abs(after * 0.5 - before_holdings).sum()
    assert after == pytest.approx(before_holdings.sum() - 0.01 * traded)
    assert result.rebalances[1].transaction_cost == pytest.approx(0.01 * traded)
    assert result.rebalances[1].turnover == pytest.approx(traded / before_holdings.sum())
    assert result.metrics.total_transaction_cost == pytest.approx(
        sum(p.transaction_cost for p in result.rebalances)
    )
    assert result.metrics.max_drawdown == pytest.approx(-0.01)
    elapsed = (result.equity_curve[-1].date - result.equity_curve[0].date).days
    assert result.metrics.cagr == pytest.approx(
        result.equity_curve[-1].value ** (365.25 / elapsed) - 1
    )
    nav = np.array([p.value for p in result.equity_curve])
    realized = nav[1:] / nav[:-1] - 1
    assert result.metrics.annual_volatility == pytest.approx(realized.std(ddof=1) * np.sqrt(252))


def test_flat_zero_cost_backtest_has_undefined_sharpe():
    """Flat, cost-free holdings have zero growth, volatility, and drawdown but undefined Sharpe."""
    prices = prices_from_returns(np.zeros((70, 2)))
    request = request_for(
        prices,
        strategies=[Strategy.EQUAL_WEIGHT],
        backtest=BacktestConfig(lookback_days=60, transaction_cost_bps=0),
    )
    result = analyze(prices, request).backtests[0]
    assert result.metrics.sharpe_ratio is None
    assert result.metrics.cagr == 0
    assert result.metrics.annual_volatility == 0
    assert result.metrics.max_drawdown == 0


def test_failed_rolling_sharpe_omits_only_that_backtest():
    """Negative rolling excess returns omit the Sharpe backtest with a warning,
    preserving others.
    """
    returns = np.tile([0.002, 0.003], (155, 1))
    returns[65:] = [-0.003, -0.002]
    prices = prices_from_returns(returns)
    request = request_for(prices, backtest=BacktestConfig(lookback_days=60, rebalance_every=10))
    result = analyze(prices, request)
    assert {p.strategy for p in result.backtests} == {
        Strategy.EQUAL_WEIGHT,
        Strategy.MINIMUM_VARIANCE,
    }
    assert any("backtest omitted" in warning for warning in result.warnings)


def test_maximum_sharpe_matches_dense_two_asset_search():
    """Optimized Sharpe is at least the dense feasible two-asset grid maximum within tolerance."""
    from sklearn.covariance import LedoitWolf

    prices = synthetic_prices(assets=2)
    request = request_for(
        prices,
        strategies=[Strategy.MAXIMUM_SHARPE],
        min_weight=0.1,
        max_weight=0.9,
        frontier_points=0,
    )
    result = analyze(prices, request)
    returns = prices.pct_change().iloc[1:].to_numpy()
    means = returns.mean(axis=0) * 252
    covariance = LedoitWolf().fit(returns).covariance_ * 252
    first = np.linspace(0.1, 0.9, 10001)
    weights = np.column_stack([first, 1 - first])
    sharpes = (weights @ means) / np.sqrt(np.einsum("ij,jk,ik->i", weights, covariance, weights))
    assert result.portfolios[0].metrics.sharpe_ratio >= sharpes.max() - 1e-7


def test_sampler_changes_with_seed_but_optimized_portfolios_do_not():
    """Changing the random seed changes sampled portfolios but not optimized results."""
    prices = synthetic_prices()
    first = analyze(prices, request_for(prices, random_seed=42))
    second = analyze(prices, request_for(prices, random_seed=43))
    assert first.portfolios == second.portfolios
    assert first.monte_carlo != second.monte_carlo


def test_optimizer_failure_is_not_returned_as_fake_success(monkeypatch):
    """A failed solver raises optimization_failed even when its returned weights are feasible."""
    from types import SimpleNamespace

    import portfolio_backend.analytics as analytics

    monkeypatch.setattr(
        analytics,
        "minimize",
        lambda *a, **kw: SimpleNamespace(success=False, x=np.ones(3) / 3, message="test failure"),
    )
    prices = synthetic_prices()
    with pytest.raises(PortfolioError, match="test failure") as error:
        analyze(prices, request_for(prices, strategies=[Strategy.MINIMUM_VARIANCE]))
    assert error.value.code == "optimization_failed"


def test_optimizer_success_with_invalid_weights_is_rejected(monkeypatch):
    """A solver success flag cannot bypass validation of infeasible returned weights."""
    from types import SimpleNamespace

    import portfolio_backend.analytics as analytics

    monkeypatch.setattr(
        analytics,
        "minimize",
        lambda *a, **kw: SimpleNamespace(
            success=True, x=np.array([1.2, -0.2, 0]), message="success"
        ),
    )
    prices = synthetic_prices()
    with pytest.raises(PortfolioError, match="infeasible"):
        analyze(prices, request_for(prices, strategies=[Strategy.MINIMUM_VARIANCE]))


@pytest.mark.parametrize("failure", [ValueError, RuntimeError, FloatingPointError, OverflowError])
def test_transaction_cost_solver_numeric_failure_is_a_domain_error(monkeypatch, failure):
    import portfolio_backend.analytics as analytics

    def fail(*args, **kwargs):
        raise failure("test cost failure")

    monkeypatch.setattr(analytics, "brentq", fail)
    prices = synthetic_prices(count=65)
    request = request_for(
        prices,
        strategies=[Strategy.EQUAL_WEIGHT],
        frontier_points=0,
        monte_carlo_samples=0,
        backtest=BacktestConfig(lookback_days=60, rebalance_every=1, transaction_cost_bps=10),
    )
    with pytest.raises(PortfolioError, match="Transaction cost solver failed") as error:
        analyze(prices, request)
    assert error.value.code == "backtest_failed"
    assert isinstance(error.value.__cause__, failure)


@pytest.mark.parametrize("wealth", [np.nan, np.inf, 0, -1])
def test_transaction_cost_solver_invalid_wealth_is_a_domain_error(monkeypatch, wealth):
    import portfolio_backend.analytics as analytics

    monkeypatch.setattr(analytics, "brentq", lambda *args, **kwargs: wealth)
    with pytest.raises(PortfolioError, match="nonpositive or nonfinite wealth") as error:
        analytics._post_fee_wealth(np.array([0.5, 0.5]), np.array([0.5, 0.5]), 0.01)
    assert error.value.code == "backtest_failed"


def test_backtest_extreme_annualization_is_a_domain_error():
    returns = np.zeros((62, 2))
    returns[-1] = 1000
    prices = prices_from_returns(returns)
    request = request_for(
        prices,
        strategies=[Strategy.EQUAL_WEIGHT],
        frontier_points=0,
        monte_carlo_samples=0,
        backtest=BacktestConfig(lookback_days=60, transaction_cost_bps=0),
    )
    with pytest.raises(PortfolioError, match="CAGR became nonfinite") as error:
        analyze(prices, request)
    assert error.value.code == "backtest_failed"


def test_flat_maximum_sharpe_with_negative_risk_free_rate_and_one_rebalance():
    prices = prices_from_returns(np.zeros((65, 2)))
    request = request_for(
        prices,
        strategies=[Strategy.MAXIMUM_SHARPE],
        risk_free_rate=-0.01,
        backtest=BacktestConfig(lookback_days=60, rebalance_every=252, transaction_cost_bps=0),
    )
    result = analyze(prices, request)
    assert len(result.portfolios) == 1
    assert result.portfolios[0].metrics.sharpe_ratio is None
    assert_feasible(result.portfolios, 0, 1)
    backtest = result.backtests[0]
    assert len(backtest.rebalances) == 1
    assert all(point.value == pytest.approx(1) for point in backtest.equity_curve)
    assert backtest.metrics.cagr == 0
    assert backtest.metrics.sharpe_ratio is None


def test_sampler_retries_zero_directions_without_losing_samples(monkeypatch):
    from types import SimpleNamespace

    import portfolio_backend.analytics as analytics

    rng = np.random.default_rng(42)
    calls = 0

    def normal(size):
        nonlocal calls
        calls += 1
        if calls == 1:
            return np.ones(size)
        if calls == 2:
            return rng.normal(size=size) * 1e-20
        return rng.normal(size=size)

    monkeypatch.setattr(
        analytics.np.random,
        "default_rng",
        lambda seed: SimpleNamespace(normal=normal, uniform=rng.uniform),
    )
    prices = prices_from_returns(np.zeros((65, 3)))
    result = analyze(prices, request_for(prices, min_weight=0.1, max_weight=0.6))
    assert len(result.monte_carlo) == 12
    assert_feasible(result.monte_carlo, 0.1, 0.6)


def test_original_default_strategies_and_legacy_result_fields():
    prices = synthetic_prices()
    request = request_for(prices)
    assert request.strategies == [
        Strategy.EQUAL_WEIGHT,
        Strategy.MINIMUM_VARIANCE,
        Strategy.MAXIMUM_SHARPE,
    ]
    assert request.benchmark_ticker is None
    result = analyze(prices, request)
    assert result.benchmark is None
    legacy = result.model_dump(exclude={"benchmark"})
    assert AnalyticsResult.model_validate(legacy).benchmark is None
    metrics = BacktestMetrics(
        total_return=0,
        cagr=0,
        annual_volatility=0,
        sharpe_ratio=None,
        max_drawdown=0,
        total_turnover=0,
        total_transaction_cost=0,
    )
    for field in (
        "sortino_ratio", "calmar_ratio", "max_drawdown_duration_days", "tracking_error",
        "information_ratio", "excess_total_return",
    ):
        assert getattr(metrics, field) is None


def test_benchmark_request_normalizes_and_requires_backtest():
    prices = synthetic_prices()
    request = request_for(
        prices, benchmark_ticker="  ^gspc ", backtest=BacktestConfig(lookback_days=60)
    )
    assert request.benchmark_ticker == "^GSPC"
    with pytest.raises(ValidationError, match="requires an enabled backtest"):
        request_for(prices, benchmark_ticker="SPY")
    for symbol in ("", "A B", "bad/symbol", ".SPY", "X" * 33, 123):
        with pytest.raises(ValidationError):
            request_for(
                prices, benchmark_ticker=symbol, backtest=BacktestConfig(lookback_days=60)
            )


@pytest.mark.parametrize(
    "strategy", [Strategy.INVERSE_VOLATILITY, Strategy.EQUAL_RISK_CONTRIBUTION]
)
def test_diagonal_risk_allocations_match_inverse_standard_deviations(strategy):
    prices = synthetic_prices()
    request = request_for(prices, strategies=[strategy])
    covariance = np.diag([0.01, 0.04, 0.16])
    weights = _weights(strategy, np.zeros(3), covariance, request)
    expected = np.array([1, 0.5, 0.25]) / 1.75
    np.testing.assert_allclose(weights, expected, atol=1e-7)
    contributions = weights * (covariance @ weights)
    np.testing.assert_allclose(contributions / contributions.sum(), np.full(3, 1 / 3), atol=1e-7)


def test_inverse_volatility_capping_preserves_free_asset_proportions():
    prices = synthetic_prices()
    request = request_for(prices, min_weight=0.1, max_weight=0.5)
    weights = _weights(
        Strategy.INVERSE_VOLATILITY, np.zeros(3), np.diag([0.01, 0.04, 0.16]), request
    )
    np.testing.assert_allclose(weights, [0.5, 1 / 3, 1 / 6], atol=1e-8)
    covariance = np.diag([0.01, 0.04, 100])
    weights = _weights(Strategy.INVERSE_VOLATILITY, np.zeros(3), covariance, request)
    np.testing.assert_allclose(weights, [0.5, 0.4, 0.1], atol=1e-8)


def test_equal_risk_contribution_uses_off_diagonal_covariance():
    prices = synthetic_prices()
    request = request_for(prices)
    covariance = np.array([[0.04, 0.012, 0.005], [0.012, 0.09, 0.024], [0.005, 0.024, 0.16]])
    erc = _weights(Strategy.EQUAL_RISK_CONTRIBUTION, np.zeros(3), covariance, request)
    inverse = _weights(Strategy.INVERSE_VOLATILITY, np.zeros(3), covariance, request)
    contributions = erc * (covariance @ erc)
    np.testing.assert_allclose(contributions / contributions.sum(), np.full(3, 1 / 3), atol=2e-6)
    assert not np.allclose(erc, inverse, atol=1e-4)
    inverse_diagonal = _weights(
        Strategy.INVERSE_VOLATILITY, np.zeros(3), np.diag(np.diag(covariance)), request
    )
    np.testing.assert_allclose(inverse, inverse_diagonal)


@pytest.mark.parametrize(
    "strategy", [Strategy.INVERSE_VOLATILITY, Strategy.EQUAL_RISK_CONTRIBUTION]
)
@pytest.mark.parametrize("minimum,maximum", [(0.32, 0.35), (1 / 3, 1 / 3), (0, 1 / 3), (1 / 3, 1)])
def test_new_risk_strategies_respect_tight_bounds(strategy, minimum, maximum):
    prices = synthetic_prices()
    request = request_for(
        prices, strategies=[strategy], min_weight=minimum, max_weight=maximum,
        monte_carlo_samples=0, frontier_points=0,
    )
    result = analyze(prices, request)
    assert_feasible(result.portfolios, minimum, maximum)
    if strategy == Strategy.EQUAL_RISK_CONTRIBUTION:
        assert any(
            "weight bounds may prevent equal risk contributions" in w for w in result.warnings
        )


@pytest.mark.parametrize(
    "strategy", [Strategy.INVERSE_VOLATILITY, Strategy.EQUAL_RISK_CONTRIBUTION]
)
@pytest.mark.parametrize("maximum", [0.5, 1])
def test_new_risk_strategies_stable_with_zero_variance(strategy, maximum):
    prices = prices_from_returns(np.zeros((70, 3)))
    request = request_for(
        prices, strategies=[strategy], max_weight=maximum,
        backtest=BacktestConfig(lookback_days=60, transaction_cost_bps=0),
        monte_carlo_samples=0, frontier_points=0,
    )
    result = analyze(prices, request)
    np.testing.assert_allclose(list(result.portfolios[0].weights.values()), np.full(3, 1 / 3))
    assert list(result.portfolios[0].risk_contributions.values()) == [0, 0, 0]
    assert result.backtests[0].metrics.total_return == 0
    mixed = _weights(strategy, np.zeros(3), np.diag([0, 0.04, 0.09]), request)
    assert np.isfinite(mixed).all()
    assert mixed.sum() == pytest.approx(1)
    assert mixed.min() >= 0
    assert mixed.max() <= maximum + 1e-8
    assert mixed[0] == pytest.approx(maximum, abs=1e-6)


def test_bounded_equal_risk_contribution_matches_dense_objective_search():
    prices = synthetic_prices(assets=2)
    request = request_for(prices, min_weight=0.45, max_weight=0.55)
    covariance = np.array([[0.01, 0.005], [0.005, 0.09]])
    weights = _weights(Strategy.EQUAL_RISK_CONTRIBUTION, np.zeros(2), covariance, request)
    grid_first = np.linspace(0.45, 0.55, 10001)
    grid = np.column_stack([grid_first, 1 - grid_first])
    contributions = grid * (grid @ covariance)
    differences = contributions - contributions.mean(axis=1, keepdims=True)
    objectives = np.sum(differences**2, axis=1)
    actual = weights * (covariance @ weights)
    assert np.sum((actual - actual.mean()) ** 2) <= objectives.min() + 1e-10
    assert weights[0] == pytest.approx(0.55, abs=1e-7)


def test_equal_risk_contribution_zero_risk_hedge_is_stable():
    prices = synthetic_prices(assets=2)
    weights = _weights(
        Strategy.EQUAL_RISK_CONTRIBUTION,
        np.zeros(2),
        np.array([[1, -1], [-1, 1]]),
        request_for(prices),
    )
    np.testing.assert_allclose(weights, [0.5, 0.5])


def test_buy_and_hold_has_one_entry_then_drifts_with_only_entry_cost(monkeypatch):
    import portfolio_backend.analytics as analytics

    returns = np.zeros((66, 2))
    returns[60] = [0.5, 0.7]
    returns[61] = [0.2, 0]
    returns[62] = [0.1, -0.1]
    prices = prices_from_returns(returns)
    request = request_for(
        prices, strategies=[Strategy.BUY_AND_HOLD], min_weight=0.5, max_weight=0.5,
        backtest=BacktestConfig(lookback_days=60, rebalance_every=1, transaction_cost_bps=100),
        monte_carlo_samples=0, frontier_points=0,
    )
    result = analyze(prices, request)
    assert result.portfolios[0].weights == {"A0": 0.5, "A1": 0.5}
    backtest = result.backtests[0]
    assert len(backtest.rebalances) == 1
    event = backtest.rebalances[0]
    assert event.date == prices.index[61].date()
    assert event.weights == {"A0": 0.5, "A1": 0.5}
    assert event.turnover == 1
    assert event.transaction_cost == pytest.approx(0.01)
    assert [p.value for p in backtest.equity_curve[:4]] == pytest.approx(
        [1, 0.99, 0.99 * 1.1, 0.495 * (1.2 * 1.1 + 0.9)]
    )
    assert backtest.metrics.total_turnover == 1
    assert backtest.metrics.total_transaction_cost == pytest.approx(0.01)

    def fail(*args, **kwargs):
        raise AssertionError("Buy-and-hold must not fit rolling estimators")

    monkeypatch.setattr(analytics, "_estimate", fail)
    direct = _backtest(returns, prices.index, Strategy.BUY_AND_HOLD, request)
    np.testing.assert_allclose(
        [p.value for p in direct.equity_curve], [p.value for p in backtest.equity_curve]
    )


@pytest.mark.parametrize(
    "strategy",
    [Strategy.BUY_AND_HOLD, Strategy.INVERSE_VOLATILITY, Strategy.EQUAL_RISK_CONTRIBUTION],
)
def test_new_strategies_lag_training_and_exclude_future_prices(strategy):
    prices = synthetic_prices(count=105)
    request = request_for(
        prices, strategies=[strategy],
        backtest=BacktestConfig(lookback_days=60, rebalance_every=10, transaction_cost_bps=10),
        monte_carlo_samples=0, frontier_points=0,
    )
    original = analyze(prices, request).backtests[0]
    training = prices.iloc[:61]
    fitted = analyze(training, request_for(
        training, strategies=[strategy], monte_carlo_samples=0, frontier_points=0,
    ))
    assert original.rebalances[0].weights == fitted.portfolios[0].weights
    changed = prices.copy()
    changed.iloc[61:, 0] *= 1.5
    altered = analyze(changed, request).backtests[0]
    assert original.rebalances[0] == altered.rebalances[0]
    assert original.equity_curve[:2] == altered.equity_curve[:2]
    changed = prices.copy()
    changed.iloc[85:, 1] *= 1.2
    altered = analyze(changed, request).backtests[0]
    cutoff = prices.index[85].date()
    assert [p for p in original.equity_curve if p.date < cutoff] == [
        p for p in altered.equity_curve if p.date < cutoff
    ]
    assert [e for e in original.rebalances if e.date <= cutoff] == [
        e for e in altered.rebalances if e.date <= cutoff
    ]


def equity_from_values(values, dates):
    peaks = np.maximum.accumulate(values)
    return [
        EquityPoint(date=pd.Timestamp(day).date(), value=value, drawdown=value / peak - 1)
        for day, value, peak in zip(dates, values, peaks, strict=True)
    ]


def test_realized_metrics_match_hand_calculation_and_calendar_recovery_duration():
    values = [1, 1.1, 0.99, 1.05, 1.1, 1.2, 1.08]
    dates = ["2020-01-01", "2020-01-02", "2020-01-05", "2020-01-07", "2020-01-11",
             "2020-01-12", "2020-01-20"]
    equity = equity_from_values(values, dates)
    events = [RebalanceEvent(
        date=equity[1].date, weights={"A0": 1}, turnover=1, transaction_cost=0.01
    )]
    metrics = _backtest_metrics(equity, events, 0.0252)
    returns = np.array([0.1, -0.1, 1.05 / 0.99 - 1, 1.1 / 1.05 - 1, 1.2 / 1.1 - 1, -0.1])
    excess = returns - 0.0001
    downside = np.sqrt(np.sum(np.minimum(excess, 0) ** 2) / 6) * np.sqrt(252)
    cagr = 1.08 ** (365.25 / 19) - 1
    assert metrics.total_return == pytest.approx(0.08)
    assert metrics.cagr == pytest.approx(cagr)
    assert metrics.annual_volatility == pytest.approx(returns.std(ddof=1) * np.sqrt(252))
    assert metrics.sortino_ratio == pytest.approx(excess.mean() * 252 / downside)
    assert metrics.sharpe_ratio == pytest.approx(excess.mean() * 252 / metrics.annual_volatility)
    assert metrics.calmar_ratio == pytest.approx(cagr / 0.1)
    assert metrics.max_drawdown == pytest.approx(-0.1)
    assert metrics.max_drawdown_duration_days == 9
    assert metrics.total_turnover == 1
    assert metrics.total_transaction_cost == 0.01
    assert metrics.tracking_error is None
    assert metrics.information_ratio is None
    assert metrics.excess_total_return is None


@pytest.mark.parametrize(
    "values,dates,duration",
    [
        ([1, 0.9, 0.8], ["2020-01-01", "2020-01-03", "2020-01-20"], 19),
        ([1, 1, 0.9, 1], ["2020-01-01", "2020-01-05", "2020-01-06", "2020-01-10"], 5),
        ([1, 1, 1.1], ["2020-01-01", "2020-01-03", "2020-01-20"], 0),
    ],
)
def test_drawdown_duration_counts_peak_to_recovery_or_end(values, dates, duration):
    metrics = _backtest_metrics(equity_from_values(values, dates), [], 0)
    assert metrics.max_drawdown_duration_days == duration


def test_ratio_zero_denominators_and_identical_benchmark_returns():
    dates = pd.date_range("2020-01-01", periods=4)
    equity = equity_from_values([1, 1, 1, 1], dates)
    metrics = _backtest_metrics(equity, [], 0, equity)
    assert metrics.sortino_ratio is None
    assert metrics.calmar_ratio is None
    assert metrics.sharpe_ratio is None
    assert metrics.information_ratio is None
    assert metrics.tracking_error == 0
    assert metrics.excess_total_return == 0
    assert metrics.max_drawdown_duration_days == 0
    positive = equity_from_values([1, 1.01, 1.03, 1.04], dates)
    positive_metrics = _backtest_metrics(positive, [], 0)
    assert positive_metrics.sortino_ratio is None
    assert positive_metrics.calmar_ratio is None


def test_benchmark_buy_and_hold_entry_cost_dates_and_relative_metrics():
    returns = np.zeros((66, 2))
    returns[61:] = [[0.02, -0.01], [-0.03, 0.01], [0.04, 0], [0, 0.03], [0.01, 0]]
    prices = prices_from_returns(returns)
    benchmark_returns = np.zeros((66, 1))
    benchmark_returns[60] = 0.9
    benchmark_returns[61:, 0] = [0.01, -0.02, 0.02, -0.01, 0.01]
    benchmark_prices = prices_from_returns(benchmark_returns).iloc[:, 0]
    request = request_for(
        prices, strategies=[Strategy.BUY_AND_HOLD, Strategy.EQUAL_WEIGHT], benchmark_ticker="SPY",
        min_weight=0.5, max_weight=0.5,
        backtest=BacktestConfig(lookback_days=60, rebalance_every=1, transaction_cost_bps=100),
        monte_carlo_samples=0, frontier_points=0,
    )
    result = analyze(prices, request, benchmark_prices)
    benchmark = result.benchmark
    assert benchmark.ticker == "SPY"
    assert len(benchmark.rebalances) == 1
    assert benchmark.rebalances[0].date == prices.index[61].date()
    assert benchmark.rebalances[0].weights == {"SPY": 1}
    assert benchmark.rebalances[0].turnover == 1
    assert benchmark.rebalances[0].transaction_cost == pytest.approx(0.01)
    assert benchmark.metrics.total_transaction_cost == pytest.approx(0.01)
    assert benchmark.metrics.total_turnover == 1
    expected_nav = np.r_[1, 0.99, 0.99 * np.cumprod(1 + benchmark_returns[61:, 0])]
    np.testing.assert_allclose([p.value for p in benchmark.equity_curve], expected_nav)
    assert benchmark.metrics.tracking_error is None
    assert benchmark.metrics.information_ratio is None
    assert benchmark.metrics.excess_total_return is None
    net_benchmark = expected_nav[1:] / expected_nav[:-1] - 1
    for backtest in result.backtests:
        assert [p.date for p in backtest.equity_curve] == [p.date for p in benchmark.equity_curve]
        nav = np.array([p.value for p in backtest.equity_curve])
        active = nav[1:] / nav[:-1] - 1 - net_benchmark
        tracking = active.std(ddof=1) * np.sqrt(252)
        assert backtest.metrics.tracking_error == pytest.approx(tracking)
        assert backtest.metrics.information_ratio == pytest.approx(active.mean() * 252 / tracking)
        assert backtest.metrics.excess_total_return == pytest.approx(nav[-1] - expected_nav[-1])
    changed = benchmark_prices.copy()
    changed.iloc[64:] *= 1.2
    later = analyze(prices, request, changed)
    assert later.benchmark.rebalances == benchmark.rebalances
    assert later.benchmark.equity_curve[:4] == benchmark.equity_curve[:4]
    assert later.backtests[0].equity_curve == result.backtests[0].equity_curve


@pytest.mark.parametrize(
    "corruption",
    ["missing", "short", "extra", "reverse", "duplicate", "shift", "nat", "string_dates",
     "nan", "infinite", "zero", "negative", "nonnumeric"],
)
def test_benchmark_prices_require_exact_dates_and_finite_positive_values(corruption):
    prices = synthetic_prices(count=75)
    benchmark = prices.iloc[:, 0].copy()
    request = request_for(
        prices, strategies=[Strategy.BUY_AND_HOLD], benchmark_ticker="SPY",
        backtest=BacktestConfig(lookback_days=60), monte_carlo_samples=0, frontier_points=0,
    )
    if corruption == "missing":
        benchmark = None
    elif corruption == "short":
        benchmark = benchmark.iloc[1:]
    elif corruption == "extra":
        benchmark.loc[benchmark.index[-1] + pd.Timedelta(days=1)] = 100
    elif corruption == "reverse":
        benchmark = benchmark.iloc[::-1]
    elif corruption == "duplicate":
        benchmark.index = pd.DatetimeIndex([benchmark.index[0]] + benchmark.index[:-1].tolist())
    elif corruption == "shift":
        benchmark.index += pd.Timedelta(hours=1)
    elif corruption == "nat":
        benchmark.index = pd.DatetimeIndex([pd.NaT] + benchmark.index[1:].tolist())
    elif corruption == "string_dates":
        benchmark.index = benchmark.index.strftime("%Y-%m-%d")
    elif corruption == "nonnumeric":
        benchmark = benchmark.astype(object)
        benchmark.iloc[5] = "not a number"
    else:
        invalid_values = {"nan": np.nan, "infinite": np.inf, "zero": 0, "negative": -1}
        benchmark.iloc[5] = invalid_values[corruption]
    with pytest.raises(PortfolioError, match="[Bb]enchmark") as error:
        analyze(prices, request, benchmark)
    assert error.value.code == "invalid_benchmark"


def test_benchmark_is_optional_and_can_be_a_portfolio_ticker():
    prices = prices_from_returns(np.zeros((70, 2)))
    options = dict(
        strategies=[Strategy.BUY_AND_HOLD], monte_carlo_samples=0, frontier_points=0,
        backtest=BacktestConfig(lookback_days=60, transaction_cost_bps=0),
    )
    result = analyze(prices, request_for(prices, **options))
    assert result.benchmark is None
    assert result.backtests[0].metrics.tracking_error is None
    assert result.backtests[0].metrics.information_ratio is None
    assert result.backtests[0].metrics.excess_total_return is None
    request = request_for(prices, benchmark_ticker="A0", **options)
    same = analyze(prices, request, prices["A0"])
    assert same.benchmark.ticker == "A0"
    assert same.backtests[0].metrics.tracking_error == 0
    assert same.backtests[0].metrics.information_ratio is None
    assert same.backtests[0].metrics.excess_total_return == 0


def test_relative_metrics_reject_misaligned_equity_dates():
    equity = equity_from_values([1, 0.99, 1.01], pd.date_range("2020-01-01", periods=3))
    shifted = equity_from_values([1, 0.99, 1.01], pd.date_range("2020-01-02", periods=3))
    with pytest.raises(PortfolioError, match="dates must match"):
        _backtest_metrics(equity, [], 0, shifted)


def scenario_request(prices, horizon_days=42, block_days=5, paths=200, **kwargs):
    """Build a request with scenarios enabled and small path counts."""
    from portfolio_backend.models import ScenarioConfig
    options = dict(
        monte_carlo_samples=0,
        frontier_points=0,
        scenario=ScenarioConfig(
            enabled=True, horizon_days=horizon_days, block_days=block_days,
            paths=paths,
        ),
    )
    options.update(kwargs)
    return request_for(prices, **options)


def test_scenarios_disabled_by_default():
    result = analyze(synthetic_prices(), request_for(synthetic_prices()))
    assert result.scenarios is None


def test_scenarios_are_seeded_and_ordered():
    prices = synthetic_prices(count=120)
    request = scenario_request(prices)
    first = analyze(prices, request)
    second = analyze(prices, request)
    assert first.scenarios is not None and len(first.scenarios) == len(request.strategies)
    for one, two in zip(first.scenarios, second.scenarios, strict=True):
        assert one.fan_paths == two.fan_paths
        assert one.percentiles == two.percentiles
    for scenario in first.scenarios:
        assert len(scenario.fan_paths) == 5
        for path in scenario.fan_paths:
            assert len(path.dates) == len(path.values) == 42
        low = scenario.percentiles[0.05]
        mid = scenario.percentiles[0.5]
        high = scenario.percentiles[0.95]
        assert low.terminal_return <= mid.terminal_return <= high.terminal_return
        assert low.terminal_wealth <= mid.terminal_wealth <= high.terminal_wealth
        stats = scenario.summary_statistics
        assert stats.terminal_return_5pct <= stats.terminal_return_95pct
        assert stats.max_drawdown_worst_5pct <= 0
        assert stats.terminal_wealth_mean > 0
    assert any("scenario" in warning.lower() or "bootstrap" in warning.lower()
               for warning in first.warnings)


def test_scenario_dates_follow_last_observation():
    prices = synthetic_prices(count=80)
    result = analyze(prices, scenario_request(prices, horizon_days=30))
    for scenario in result.scenarios:
        first_date = pd.Timestamp(scenario.fan_paths[0].dates[0])
        last_date = pd.Timestamp(scenario.fan_paths[0].dates[-1])
        assert first_date == prices.index[-1] + pd.Timedelta(days=1)
        assert last_date == prices.index[-1] + pd.Timedelta(days=30)


def test_scenarios_on_flat_prices_stay_at_one():
    prices = prices_from_returns(np.zeros((70, 2)))
    result = analyze(prices, scenario_request(prices))
    for scenario in result.scenarios:
        for path in scenario.fan_paths:
            assert path.values == pytest.approx([1.0] * 42)
        assert scenario.summary_statistics.terminal_wealth_mean == pytest.approx(1)


def test_scenario_block_days_require_history():
    from portfolio_backend.models import ScenarioConfig
    prices = synthetic_prices(count=61)
    request = request_for(
        prices,
        scenario=ScenarioConfig(enabled=True, block_days=63, horizon_days=21),
    )
    with pytest.raises(PortfolioError, match="[Ss]cenario") as error:
        analyze(prices, request)
    assert error.value.code == "insufficient_history"


def test_scenario_weights_match_fitted_allocations():
    prices = synthetic_prices(count=90)
    request = scenario_request(
        prices, strategies=[Strategy.EQUAL_WEIGHT, Strategy.INVERSE_VOLATILITY],
    )
    result = analyze(prices, request)
    weights_by_strategy = {p.strategy: p.weights for p in result.portfolios}
    for scenario in result.scenarios:
        assert scenario.weights == weights_by_strategy[scenario.strategy]


def test_scenario_percentile_validation():
    from portfolio_backend.models import ScenarioConfig
    with pytest.raises(ValidationError):
        ScenarioConfig(percentile_levels=[1.5])
    config = ScenarioConfig(percentile_levels=[0.9, 0.1, 0.1])
    assert config.percentile_levels == [0.1, 0.9]
