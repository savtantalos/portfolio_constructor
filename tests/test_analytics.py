import numpy as np
import pandas as pd
import pytest

from portfolio_backend.analytics import analyze
from portfolio_backend.errors import PortfolioError
from portfolio_backend.models import AnalysisRequest, BacktestConfig, Strategy


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
