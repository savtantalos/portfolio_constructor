import assert from 'node:assert/strict';
import test from 'node:test';
import { BACKTEST_METRICS, backtestComparisonRows, formatBacktestMetric } from './backtestComparison.ts';

const metrics = { total_return: 0.12, cagr: 0.1, annual_volatility: 0.15, sharpe_ratio: 0.6, max_drawdown: -0.1, total_turnover: 2.5, total_transaction_cost: 0.0025 };
const backtest = (strategy) => ({ strategy, metrics, equity_curve: [], rebalances: [] });

test('comparison includes all backtests without needing in-sample portfolios and appends benchmark separately', () => {
  const backtests = [backtest('buy_and_hold'), backtest('equal_risk_contribution')];
  const benchmark = { ticker: 'SPY', metrics: { ...metrics, total_return: 0.09 }, equity_curve: [], rebalances: [] };
  const original = structuredClone({ backtests, benchmark });
  const rows = backtestComparisonRows(backtests, benchmark, ['a', 'b', 'c', 'd', 'e', 'f'], 'white');
  assert.deepEqual(rows.map(({ label }) => label), ['Buy & Hold', 'Equal Risk Contribution', 'SPY buy & hold']);
  assert.deepEqual(rows.map(({ color }) => color), ['d', 'f', 'white']);
  assert.deepEqual(rows.map(({ isBenchmark }) => isBenchmark), [false, false, true]);
  assert.equal(rows[0].metrics, metrics);
  assert.equal(rows[2].metrics, benchmark.metrics);
  assert.deepEqual({ backtests, benchmark }, original);
  assert.equal(backtestComparisonRows([], benchmark, [], 'white').length, 1);
  assert.equal(backtestComparisonRows(backtests, undefined, [], 'white').length, 2);
  assert.deepEqual(backtestComparisonRows([], null, [], 'white'), []);
});

test('metric formatting distinguishes percentages, percentage point differences and absolute costs', () => {
  assert.equal(formatBacktestMetric(0.12, 'percent'), '12.00%');
  assert.equal(formatBacktestMetric(-0.1, 'percent'), '-10.00%');
  assert.equal(formatBacktestMetric(0.03, 'percentage_points'), '3.00 pp');
  assert.equal(formatBacktestMetric(-0.03, 'percentage_points'), '-3.00 pp');
  assert.equal(formatBacktestMetric(1.234, 'ratio'), '1.23');
  assert.equal(formatBacktestMetric(103, 'days'), '103 days');
  assert.equal(formatBacktestMetric(2.5, 'turnover'), '2.50×');
  assert.equal(formatBacktestMetric(0.0025, 'wealth'), '0.0025');
});

test('missing legacy and undefined metrics render a dash while valid zero metrics remain visible', () => {
  assert.equal(BACKTEST_METRICS.length, 13);
  for (const { key, unit } of BACKTEST_METRICS) {
    for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
      assert.equal(formatBacktestMetric(value, unit), '—');
    }
    assert.notEqual(formatBacktestMetric(0, unit), '—');
    if (!(key in metrics)) assert.equal(formatBacktestMetric(metrics[key], unit), '—');
  }
});
