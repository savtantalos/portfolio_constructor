import assert from 'node:assert/strict';
import test from 'node:test';
import { benchmarkLabel, STRATEGY_LABELS, STRATEGY_OPTIONS, strategyColor } from './strategyMetadata.ts';

test('all six strategies have distinct readable labels and descriptions', () => {
  const strategies = ['equal_weight', 'minimum_variance', 'maximum_sharpe', 'buy_and_hold', 'inverse_volatility', 'equal_risk_contribution'];
  assert.deepEqual(STRATEGY_OPTIONS.map(({ value }) => value), strategies);
  assert.equal(new Set(Object.values(STRATEGY_LABELS)).size, 6);
  for (const strategy of strategies) {
    assert.ok(!STRATEGY_LABELS[strategy].includes('_'));
    const option = STRATEGY_OPTIONS.find(({ value }) => value === strategy);
    assert.equal(option.label, STRATEGY_LABELS[strategy]);
    assert.ok(option.description.length > 0);
  }
  assert.match(STRATEGY_OPTIONS[3].description, /Equal weights at entry.*without rebalancing/);
  assert.match(STRATEGY_OPTIONS[4].description, /covariance diagonal/);
  assert.match(STRATEGY_OPTIONS[5].description, /full covariance.*approximate/);
});

test('strategy colors remain stable across subsets and reorderings', () => {
  const colors = ['red', 'blue', 'green', 'purple', 'orange', 'cyan'];
  assert.deepEqual(STRATEGY_OPTIONS.map(({ value }) => strategyColor(value, colors)), colors);
  assert.deepEqual(['equal_risk_contribution', 'minimum_variance', 'buy_and_hold'].map((value) => strategyColor(value, colors)), ['cyan', 'blue', 'purple']);
  assert.equal(strategyColor('maximum_sharpe', ['red', 'blue']), 'red');
  assert.equal(strategyColor('equal_weight', []), '#808080');
});

test('benchmark is named separately from the basket buy and hold strategy', () => {
  assert.equal(benchmarkLabel('SPY'), 'SPY buy & hold');
  assert.notEqual(benchmarkLabel('SPY'), STRATEGY_LABELS.buy_and_hold);
});
