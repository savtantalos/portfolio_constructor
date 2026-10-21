import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeBenchmarkTicker, startDateForYears, validateConfiguration } from './analysisConfiguration.ts';

const today = '2025-06-15';
const validRequest = {
  tickers: ['VTI', 'VXUS', 'BND'],
  start_date: '2022-06-15',
  end_date: today,
  base_currency: 'USD',
  strategies: ['equal_weight', 'minimum_variance', 'maximum_sharpe'],
  min_weight: 0,
  max_weight: 1,
  risk_free_rate: 0.02,
  monte_carlo_samples: 1000,
  frontier_points: 20,
  random_seed: 42,
  backtest: { enabled: true, lookback_days: 252, rebalance_every: 21, transaction_cost_bps: 10 },
};
const errorsFor = (overrides) => validateConfiguration({ ...validRequest, ...overrides }, today);

test('default configuration is valid', () => {
  assert.deepEqual(errorsFor({}), []);
});

test('benchmark normalization trims, uppercases, clears blanks and omits disabled benchmarks', () => {
  assert.equal(normalizeBenchmarkTicker('  spy  ', true), 'SPY');
  assert.equal(normalizeBenchmarkTicker(' ^gspc ', true), '^GSPC');
  for (const value of [undefined, null, '', '   ']) {
    assert.equal(normalizeBenchmarkTicker(value, true), null);
  }
  for (const value of ['SPY', 'invalid / symbol', '', null, undefined]) {
    assert.equal(normalizeBenchmarkTicker(value, false), null);
  }
});

test('benchmark validation mirrors the API symbol pattern and backtest requirement', () => {
  for (const benchmark_ticker of [null, undefined, 'SPY', '^GSPC', 'BRK-B', 'BRK.B', 'EURUSD=X', 'A_B', '123', 'A'.repeat(32)]) {
    assert.deepEqual(errorsFor({ benchmark_ticker }), []);
  }
  for (const benchmark_ticker of ['', 'spy', ' SPY', 'SP Y', 'A/B', '-SPY', '.SPY', '=X', '_X', 'A'.repeat(33)]) {
    assert.match(errorsFor({ benchmark_ticker }).join(' '), /Benchmark symbol/);
  }
  const backtest = { ...validRequest.backtest, enabled: false };
  assert.match(errorsFor({ benchmark_ticker: 'SPY', backtest }).join(' '), /Enable backtesting/);
  assert.deepEqual(errorsFor({ benchmark_ticker: null, backtest }), []);
  assert.deepEqual(errorsFor({ benchmark_ticker: normalizeBenchmarkTicker(' spy ', true) }), []);
});

test('shortcuts anchor to the selected end date in UTC', () => {
  assert.equal(startDateForYears('2020-07-12', 1), '2019-07-12');
  assert.equal(startDateForYears('2020-07-12', 3), '2017-07-12');
  assert.equal(startDateForYears('2020-07-12', 5), '2015-07-12');
});

test('shortcuts clamp leap days and reject invalid end dates', () => {
  assert.equal(startDateForYears('2024-02-29', 1), '2023-02-28');
  assert.equal(startDateForYears('2024-02-29', 4), '2020-02-29');
  for (const value of ['', 'bad date', '2025-02-29', '2025-04-31', '0000-01-01']) {
    assert.equal(startDateForYears(value, 1), null);
  }
  assert.equal(startDateForYears('0001-06-15', 1), null);
});

test('asset and strategy counts must be within API bounds', () => {
  assert.match(errorsFor({ tickers: ['VTI'] }).join(' '), /2 and 30/);
  assert.match(errorsFor({ tickers: Array.from({ length: 31 }, (_, i) => `A${i}`) }).join(' '), /2 and 30/);
  assert.match(errorsFor({ strategies: [] }).join(' '), /at least one strategy/);
});

test('dates must exist, be ordered, and not end in the future', () => {
  assert.match(errorsFor({ start_date: '' }).join(' '), /valid start date/);
  assert.match(errorsFor({ end_date: '2025-02-29' }).join(' '), /valid start date/);
  assert.match(errorsFor({ start_date: today }).join(' '), /before end date/);
  assert.match(errorsFor({ start_date: '2025-06-16' }).join(' '), /before end date/);
  assert.match(errorsFor({ end_date: '2025-06-16' }).join(' '), /future/);
});

test('historical window matches the API limit of 366 times 20 days', () => {
  const end = new Date(`${today}T00:00:00Z`);
  const dateAtDistance = (days) => new Date(end.getTime() - days * 86400000).toISOString().slice(0, 10);
  assert.deepEqual(errorsFor({ start_date: dateAtDistance(366 * 20) }), []);
  assert.match(errorsFor({ start_date: dateAtDistance(366 * 20 + 1) }).join(' '), /20 years/);
});

test('bounds must be ordered and feasible for the selected basket', () => {
  assert.match(errorsFor({ min_weight: 0.4, max_weight: 0.3 }).join(' '), /cannot exceed/);
  assert.match(errorsFor({ min_weight: 0.34 }).join(' '), /cannot fully allocate 3 assets/);
  assert.match(errorsFor({ max_weight: 0.33 }).join(' '), /cannot fully allocate 3 assets/);
  assert.deepEqual(errorsFor({ min_weight: 1 / 3, max_weight: 1 / 3 }), []);
  assert.deepEqual(errorsFor({ min_weight: 1 / 3 + 1e-12 }), []);
  assert.deepEqual(errorsFor({ max_weight: 1 / 3 - 1e-12 }), []);
  assert.deepEqual(errorsFor({ tickers: ['SPY', 'AGG'], min_weight: 0.5, max_weight: 0.5 }), []);
});

test('floating-point bounds match the API rather than input step restrictions', () => {
  assert.deepEqual(errorsFor({ risk_free_rate: -0.999, min_weight: 0.001, max_weight: 0.999 }), []);
  assert.match(errorsFor({ risk_free_rate: -1 }).join(' '), /risk-free rate/);
  assert.match(errorsFor({ max_weight: 0 }).join(' '), /Maximum weight/);
  assert.match(errorsFor({ min_weight: -0.1 }).join(' '), /Minimum weight/);
});

test('nonfinite, fractional integer, and out-of-range numeric settings are rejected', () => {
  for (const key of ['min_weight', 'max_weight', 'risk_free_rate', 'monte_carlo_samples', 'frontier_points']) {
    for (const value of [NaN, Infinity, -Infinity]) assert.ok(errorsFor({ [key]: value }).length > 0);
  }
  assert.match(errorsFor({ monte_carlo_samples: 0.5 }).join(' '), /whole number/);
  assert.match(errorsFor({ monte_carlo_samples: 5001 }).join(' '), /Monte Carlo/);
  assert.match(errorsFor({ frontier_points: 51 }).join(' '), /Frontier/);
  assert.deepEqual(errorsFor({ monte_carlo_samples: 0, frontier_points: 0 }), []);
});

test('backtest configuration is validated even while disabled, without mutation', () => {
  const backtest = { enabled: false, lookback_days: 59, rebalance_every: 253, transaction_cost_bps: 501 };
  const snapshot = structuredClone(backtest);
  const errors = errorsFor({ backtest }).join(' ');
  assert.match(errors, /lookback/);
  assert.match(errors, /Rebalance/);
  assert.match(errors, /Transaction cost/);
  assert.deepEqual(backtest, snapshot);
  assert.deepEqual(errorsFor({ backtest: { ...validRequest.backtest, enabled: false, transaction_cost_bps: 0.25 } }), []);
});
