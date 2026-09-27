import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { delimiter, resolve } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(require.resolve('playwright', {
  paths: process.env.PATH.split(delimiter).map((entry) => resolve(entry, '..')),
}));
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
const dates = [];
for (let date = new Date('2024-01-02T00:00:00Z'); dates.length < 280; date.setUTCDate(date.getUTCDate() + 1)) {
  if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) dates.push(date.toISOString().slice(0, 10));
}
const prices = [[100, 50, 200]];
for (let i = 1; i < dates.length; i++) {
  prices.push([prices[i - 1][0] * (i % 2 ? 1.02 : 0.99), 50, prices[i - 1][2] * 1.001]);
}
const tickers = ['AAA', 'FLAT', 'GROWTH'];
const snapshots = {
  full: { tickers, dates, prices },
  short: { tickers, dates: dates.slice(0, 21), prices: prices.slice(0, 21) },
  empty: { tickers: [], dates: [], prices: [] },
};
let calls = 0;
await page.route('**/api/v1/**', async (route) => {
  calls++;
  assert.equal(route.request().method(), 'GET');
  const path = new URL(route.request().url()).pathname;
  const id = path.split('/')[4];
  const snapshot = snapshots[id];
  assert.ok(snapshot, `Unexpected API call: ${path}`);
  if (path.endsWith('/prices')) return route.fulfill({ json: snapshot });
  return route.fulfill({ json: {
    id, engine_version: 'test', request: { tickers, backtest: { enabled: false } },
    data: { effective_start: dates[0], effective_end: dates.at(-1), price_observations: snapshot.dates.length,
      provider: 'test', adjustment: 'adjusted', currency: 'EUR', snapshot_sha256: '1234567890abcdef' },
    results: { portfolios: [], backtests: [], warnings: [], monte_carlo: [], efficient_frontier: [], correlation: {} },
    assumptions: [],
  } });
});
const closeTo = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-12, `${actual} != ${expected}`);
const chartData = (section) => page.locator(`section[aria-label="Asset ${section}"] .js-plotly-plot`).evaluate((plot) => ({
  data: plot.data.map(({ x, y, name, line, visible, hovertemplate }) => ({ x, y, name, line, visible, hovertemplate })),
  yaxis: plot.layout.yaxis, title: plot.layout.title.text,
}));
const waitForChart = (section, title) => page.waitForFunction(({ section, title }) => {
  const plot = document.querySelector(`section[aria-label="Asset ${section}"] .js-plotly-plot`);
  return plot?.layout?.title.text === title;
}, { section, title });
const openTab = async (id) => {
  await page.goto(`http://127.0.0.1:5175/analysis/${id}`);
  await page.getByRole('button', { name: 'Returns & Volatility', exact: true }).click();
};
try {
  await openTab('full');
  await waitForChart('returns', 'Cumulative Return (%)');
  await waitForChart('volatility', '21-Day Rolling Annualized Volatility (%)');
  let returns = await chartData('returns');
  let volatility = await chartData('volatility');
  assert.equal(returns.yaxis.tickformat, '.1%');
  assert.deepEqual(returns.data.map((trace) => trace.name), tickers);
  for (const trace of returns.data) assert.equal(trace.y[0], 0);
  closeTo(returns.data[0].y[1], 0.02);
  closeTo(returns.data[0].y.at(-1), prices.at(-1)[0] / prices[0][0] - 1);
  assert.deepEqual(volatility.data[0].y.slice(0, 21), Array(21).fill(null));
  assert.equal(volatility.data[1].y[21], 0);
  assert.deepEqual(returns.data.map((trace) => trace.line.color), volatility.data.map((trace) => trace.line.color));
  const initialCalls = calls;
  await page.getByLabel('Return view').selectOption('daily');
  await waitForChart('returns', 'Daily Return (%)');
  returns = await chartData('returns');
  assert.equal(returns.data[0].y[0], null);
  closeTo(returns.data[0].y[1], 0.02);
  closeTo(returns.data[0].y[2], -0.01);
  for (const window of [63, 126, 252]) {
    await page.getByLabel('Volatility lookback').selectOption(String(window));
    await waitForChart('volatility', `${window}-Day Rolling Annualized Volatility (%)`);
    volatility = await chartData('volatility');
    assert.deepEqual(volatility.data[0].y.slice(0, window), Array(window).fill(null));
    const values = prices.slice(1, window + 1).map((row, i) => row[0] / prices[i][0] - 1);
    const mean = values.reduce((sum, value) => sum + value, 0) / window;
    const expected = Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (window - 1) * 252);
    closeTo(volatility.data[0].y[window], expected);
  }
  await page.getByRole('button', { name: 'Ocean', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('section[aria-label="Asset returns"] .js-plotly-plot')?.data[0].line.color === '#0077B6');
  assert.equal((await chartData('volatility')).data[0].line.color, '#0077B6');
  assert.equal(await page.getByLabel('Volatility lookback').inputValue(), '252');
  await page.locator('section[aria-label="Asset returns"] .legendtoggle').first().click();
  await page.waitForFunction(() => document.querySelector('section[aria-label="Asset returns"] .js-plotly-plot')?.data[0].visible === 'legendonly');
  await page.getByRole('button', { name: 'Show adjusted prices' }).click();
  await page.waitForFunction(() => document.querySelector('#adjusted-price-chart .js-plotly-plot')?.layout.title.text === 'Adjusted Closing Prices (EUR)');
  const raw = await page.locator('#adjusted-price-chart .js-plotly-plot').evaluate((plot) => plot.data[0]);
  assert.deepEqual(raw.y, prices.map((row) => row[0]));
  assert.ok(raw.hovertemplate.includes('EUR'));
  await page.getByRole('button', { name: 'Hide adjusted prices' }).click();
  assert.equal(await page.locator('#adjusted-price-chart').count(), 0);
  assert.equal(calls, initialCalls);
  console.log('PASS: cumulative/daily return data, date alignment, percent formatting, all lookbacks, sample volatility, theme colors, legend filtering, optional raw prices, no extra API requests');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  if (size.document > size.viewport + 1) console.log(await page.evaluate(() => [...document.querySelectorAll('.main-content, .page, .page-header, .page-actions, .tab-bar, .asset-charts, .asset-chart-section, .js-plotly-plot, .chart-controls, .config-grid, .theme-picker')].map((el) => ({ class: el.className, width: el.getBoundingClientRect().width, right: el.getBoundingClientRect().right, minWidth: getComputedStyle(el).minWidth }))));
  assert.ok(size.document <= size.viewport + 1, `Mobile horizontal overflow: ${JSON.stringify(size)}`);
  console.log('PASS: mobile viewport has no horizontal page overflow');

  await openTab('short');
  await page.getByRole('status').waitFor();
  assert.ok((await page.getByRole('status').innerText()).includes('at least 22'));
  await waitForChart('returns', 'Cumulative Return (%)');
  assert.equal(await page.locator('section[aria-label="Asset volatility"] .js-plotly-plot').count(), 0);
  await page.getByLabel('Volatility lookback').selectOption('252');
  assert.ok((await page.getByRole('status').innerText()).includes('at least 253'));
  await openTab('empty');
  await page.getByText('At least two saved price observations are needed to chart returns.').waitFor();
  assert.equal(await page.locator('.js-plotly-plot').count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: short and empty snapshots show helpful messages with no misleading volatility and no runtime errors');
} finally {
  await browser.close();
}
