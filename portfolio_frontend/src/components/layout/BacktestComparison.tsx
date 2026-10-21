import type { BacktestResult, BenchmarkResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { BACKTEST_METRICS, backtestComparisonRows, formatBacktestMetric } from '../backtestComparison';

interface Props {
  backtests: BacktestResult[];
  benchmark?: BenchmarkResult | null;
  theme: ColorTheme;
}

export default function BacktestComparison({ backtests, benchmark, theme }: Props) {
  const rows = backtestComparisonRows(backtests, benchmark, theme.colors, theme.text);
  return (
    <section className="research-panel backtest-comparison" aria-labelledby="backtest-comparison-heading">
      <div className="panel-heading"><h2 id="backtest-comparison-heading">Backtest comparison</h2></div>
      <p className="research-note">Realized results after costs, including every saved backtest even when its in-sample portfolio is unavailable. Buy &amp; Hold starts equally weighted and never rebalances.</p>
      {benchmark && <p className="research-note">{benchmark.ticker} buy &amp; hold is a separate benchmark, not an optimized strategy. It uses the same evaluation dates and entry fee rate. Selecting a benchmark can shorten the common data window.</p>}
      <div className="data-table-scroll" tabIndex={0} role="region" aria-label="Backtest metric comparison">
        <table className="data-table backtest-comparison-table" aria-describedby="backtest-metric-units">
          <caption className="sr-only">Net backtest results by strategy and optional benchmark</caption>
          <thead><tr><th scope="col">Strategy / benchmark</th>{BACKTEST_METRICS.map((metric) => <th key={metric.key} scope="col">{metric.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className={row.isBenchmark ? 'benchmark-row' : undefined}>
                <th scope="row"><span className="strategy-swatch" aria-hidden="true" style={{ borderBottom: `3px ${row.isBenchmark ? 'dashed' : 'solid'} ${row.color}` }}>{'\u00a0\u00a0\u00a0'}</span>{' '}{row.label}</th>
                {BACKTEST_METRICS.map((metric) => <td key={metric.key} className="numeric-cell">{formatBacktestMetric(row.metrics[metric.key], metric.unit)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p id="backtest-metric-units" className="data-table-note">CAGR, volatility and tracking error are annualized. Drawdown duration is calendar days, including any ongoing drawdown. Turnover sums full traded notional / pre-trade wealth (not half-turnover); costs sum fees in normalized wealth units, starting from 1. Excess net return is the strategy’s cumulative net return minus the benchmark’s, in percentage points (pp), not a return ratio. Tracking error and information ratio are relative to the benchmark. A dash means unavailable or undefined, including metrics absent from older runs.</p>
    </section>
  );
}
