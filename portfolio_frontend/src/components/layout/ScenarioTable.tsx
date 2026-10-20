import type { ScenarioResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { STRATEGY_LABELS, strategyColor } from '../strategyMetadata';

interface Props {
  scenarios: ScenarioResult[];
  theme: ColorTheme;
}

function pct(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(2)}%`;
}

function wealth(value: number): string {
  return Number.isFinite(value) ? value.toFixed(3) : '—';
}

export default function ScenarioTable({ scenarios, theme }: Props) {
  const levels = [...new Set(scenarios.flatMap((s) => s.fan_paths.map((p) => p.percentile)))].sort((a, b) => a - b);
  return (
    <section className="research-panel" aria-labelledby="scenario-summary-heading">
      <div className="panel-heading"><h2 id="scenario-summary-heading">Scenario summary</h2></div>
      <p className="research-note">Block-bootstrap resamples of historical return blocks applied to each fitted allocation. Outcomes are conditional on the sample, not forecasts.</p>
      <div className="data-table-scroll" role="region" aria-label="Scenario cross-path statistics">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Strategy</th>
              <th scope="col">Mean wealth</th>
              <th scope="col">Median wealth</th>
              <th scope="col">5th pct return</th>
              <th scope="col">95th pct return</th>
              <th scope="col">Worst 5% drawdown</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s) => (
              <tr key={s.strategy}>
                <th scope="row">
                  <span className="strategy-swatch" aria-hidden="true" style={{ borderBottom: `3px solid ${strategyColor(s.strategy, theme.colors)}` }}>{'\u00a0\u00a0\u00a0'}</span>{' '}
                  {STRATEGY_LABELS[s.strategy]}
                </th>
                <td className="numeric-cell">{wealth(s.summary_statistics.terminal_wealth_mean)}</td>
                <td className="numeric-cell">{wealth(s.summary_statistics.terminal_wealth_median)}</td>
                <td className="numeric-cell">{pct(s.summary_statistics.terminal_return_5pct)}</td>
                <td className="numeric-cell">{pct(s.summary_statistics.terminal_return_95pct)}</td>
                <td className="numeric-cell">{pct(s.summary_statistics.max_drawdown_worst_5pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="data-table-scroll" role="region" aria-label="Scenario terminal metrics by percentile">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Strategy</th>
              <th scope="col">Percentile</th>
              <th scope="col">Terminal return</th>
              <th scope="col">Terminal wealth</th>
              <th scope="col">Max drawdown</th>
              <th scope="col">CAGR</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.flatMap((s) =>
              levels.filter((level) => s.percentiles[String(level)]).map((level) => {
                const metrics = s.percentiles[String(level)];
                return (
                  <tr key={`${s.strategy}-${level}`}>
                    <th scope="row">{STRATEGY_LABELS[s.strategy]}</th>
                    <td className="numeric-cell">{Math.round(level * 100)}%</td>
                    <td className="numeric-cell">{pct(metrics.terminal_return)}</td>
                    <td className="numeric-cell">{wealth(metrics.terminal_wealth)}</td>
                    <td className="numeric-cell">{pct(metrics.max_drawdown)}</td>
                    <td className="numeric-cell">{pct(metrics.cagr)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
