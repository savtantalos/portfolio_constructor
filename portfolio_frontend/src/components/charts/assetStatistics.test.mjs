import assert from 'node:assert/strict';
import test from 'node:test';
import { calculateAssetStatistics } from './assetStatistics.ts';

const snapshot = (prices, tickers = ['AAA']) => ({
  tickers,
  dates: prices.map((_, i) => `2025-01-${String(i + 1).padStart(2, '0')}`),
  prices,
});
const closeTo = (actual, expected) => {
  assert.equal(typeof actual, 'number');
  assert.ok(Math.abs(actual - expected) < 1e-12, `${actual} != ${expected}`);
};

test('returns are decimal ratios, start at zero, and retain ticker/date order', () => {
  const input = snapshot([[100, 200], [110, 180], [99, 198]], ['AAA', 'BBB']);
  const original = structuredClone(input);
  const series = calculateAssetStatistics(input, 2);
  assert.deepEqual(series.map((asset) => asset.ticker), ['AAA', 'BBB']);
  assert.deepEqual(series[0].prices, [100, 110, 99]);
  assert.equal(series[0].cumulativeReturns[0], 0);
  closeTo(series[0].cumulativeReturns[1], 0.1);
  closeTo(series[0].cumulativeReturns[2], -0.01);
  closeTo(series[1].cumulativeReturns[1], -0.1);
  closeTo(series[1].cumulativeReturns[2], -0.01);
  assert.equal(series[0].dailyReturns[0], null);
  closeTo(series[0].dailyReturns[1], 0.1);
  closeTo(series[0].dailyReturns[2], -0.1);
  assert.deepEqual(input, original);
});

test('volatility uses sample variance, sqrt(252), and a full trailing window', () => {
  const [asset] = calculateAssetStatistics(snapshot([[100], [110], [99], [99]]), 2);
  assert.deepEqual(asset.rollingVolatility.slice(0, 2), [null, null]);
  closeTo(asset.rollingVolatility[2], Math.sqrt(0.02 * 252));
  closeTo(asset.rollingVolatility[3], Math.sqrt(0.005 * 252));
});

test('the first 21-return window needs 22 prices and does not use future data', () => {
  const prices = Array.from({ length: 25 }, (_, i) => [100 * (1 + i / 100)]);
  const [full] = calculateAssetStatistics(snapshot(prices), 21);
  const [prefix] = calculateAssetStatistics(snapshot(prices.slice(0, 22)), 21);
  assert.deepEqual(full.rollingVolatility.slice(0, 21), Array(21).fill(null));
  assert.equal(typeof full.rollingVolatility[21], 'number');
  assert.deepEqual(full.rollingVolatility.slice(0, 22), prefix.rollingVolatility);
  const [tooShort] = calculateAssetStatistics(snapshot(prices), 63);
  assert.deepEqual(tooShort.rollingVolatility, Array(25).fill(null));
});

test('flat prices and constant daily returns produce zero volatility', () => {
  const [flat, constant] = calculateAssetStatistics(snapshot([[100, 1], [100, 2], [100, 4], [100, 8]], ['FLAT', 'CONSTANT']), 2);
  assert.deepEqual(flat.cumulativeReturns, [0, 0, 0, 0]);
  assert.deepEqual(flat.rollingVolatility, [null, null, 0, 0]);
  assert.deepEqual(constant.rollingVolatility, [null, null, 0, 0]);
});

test('empty and single-observation snapshots are handled without fabricated returns', () => {
  assert.deepEqual(calculateAssetStatistics(snapshot([], []), 21), []);
  const [empty] = calculateAssetStatistics(snapshot([]), 21);
  assert.deepEqual(empty.dailyReturns, []);
  const [single] = calculateAssetStatistics(snapshot([[100]]), 21);
  assert.deepEqual(single.cumulativeReturns, [0]);
  assert.deepEqual(single.dailyReturns, [null]);
  assert.deepEqual(single.rollingVolatility, [null]);
});

test('invalid prices create gaps instead of infinities or filled observations', () => {
  const [asset] = calculateAssetStatistics(snapshot([[100], [0], [110], [121], [121]]), 2);
  assert.deepEqual(asset.dailyReturns.slice(0, 3), [null, null, null]);
  assert.deepEqual(asset.rollingVolatility.slice(0, 4), [null, null, null, null]);
  closeTo(asset.rollingVolatility[4], Math.sqrt(0.005 * 252));
  assert.equal(asset.cumulativeReturns[1], null);
  for (const invalid of [NaN, Infinity, -1, undefined]) {
    const [bad] = calculateAssetStatistics(snapshot([[invalid], [100], [110]]), 2);
    assert.deepEqual(bad.cumulativeReturns, [null, null, null]);
    assert.equal(bad.dailyReturns[1], null);
    assert.equal(bad.rollingVolatility[2], null);
  }
});

test('invalid volatility windows are rejected', () => {
  for (const window of [0, 1, -1, 2.5, NaN, Infinity]) {
    assert.throws(() => calculateAssetStatistics(snapshot([[100]]), window), RangeError);
  }
});
