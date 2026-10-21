import type { PortfolioResult, BacktestResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { STRATEGY_LABELS, strategyColor } from '../strategyMetadata';

interface Props {
  portfolios: PortfolioResult[];
  backtests: BacktestResult[];
  theme: ColorTheme;
}

function fmt(v: number | null, pct = true, decimals = 2): string {
  if (v === null || !Number.isFinite(v)) return '—';
  return pct ? `${(v * 100).toFixed(decimals)}%` : v.toFixed(decimals);
}

export default function MetricsCards({ portfolios, backtests, theme }: Props) {
  const volatilities = portfolios.map((p) => p.metrics.annual_volatility).filter(Number.isFinite);
  const sharpes = portfolios.flatMap((p) => p.metrics.sharpe_ratio !== null && Number.isFinite(p.metrics.sharpe_ratio) ? [p.metrics.sharpe_ratio] : []);
  const lowestVolatility = volatilities.length ? Math.min(...volatilities) : null;
  const highestSharpe = sharpes.length ? Math.max(...sharpes) : null;
  const allocations = portfolios.flatMap((p) => Object.entries(p.weights)
    .filter(([, weight]) => Number.isFinite(weight))
    .map(([ticker, weight]) => ({ ticker, weight, strategy: p.strategy })));
  const largestAllocation = allocations.reduce<typeof allocations[number] | null>((largest, allocation) =>
    !largest || allocation.weight > largest.weight ? allocation : largest, null);
  const leaders = (metric: 'annual_volatility' | 'sharpe_ratio', value: number | null) => value === null
    ? 'Not available'
    : portfolios.filter((p) => p.metrics[metric] === value).map((p) => STRATEGY_LABELS[p.strategy]).join(' / ');

  return (
    <>
      <div className="section-heading">
        <div><span className="terminal-eyebrow">Research snapshot</span><h2>Strategy diagnostics</h2></div>
        <span className="research-badge">In-sample estimates</span>
      </div>
      <div className="research-snapshot">
        <div><span>Lowest annual volatility</span><strong>{fmt(lowestVolatility)}</strong><small>{leaders('annual_volatility', lowestVolatility)}</small></div>
        <div><span>Highest Sharpe ratio</span><strong>{fmt(highestSharpe, false)}</strong><small>{leaders('sharpe_ratio', highestSharpe)}</small></div>
        <div><span>Largest single allocation</span><strong>{largestAllocation ? `${largestAllocation.ticker} · ${fmt(largestAllocation.weight)}` : '—'}</strong><small>{largestAllocation ? `${STRATEGY_LABELS[largestAllocation.strategy]} · across computed portfolios` : 'Not available'}</small></div>
      </div>
      <p className="research-note">Estimated from the analysis sample, not a forecast. {backtests.length ? 'Walk-forward results below use only prior observations to fit each rebalance and include configured transaction costs.' : 'No walk-forward backtest results are available for this analysis.'}</p>
      <div className="metrics-grid">
      {portfolios.map((p) => {
        const bt = backtests.find((b) => b.strategy === p.strategy);
        return (
          <div key={p.strategy} className="metric-card" style={{ borderColor: strategyColor(p.strategy, theme.colors) }}>
            <h3 className="card-title">{STRATEGY_LABELS[p.strategy]}</h3>
            <p className="metric-group-label">In-sample · annualized</p>
            <div className="card-section">
              <span className="card-label">Estimated Return</span>
              <span className="card-value">{fmt(p.metrics.expected_annual_return)}</span>
            </div>
            <div className="card-section">
              <span className="card-label">Volatility</span>
              <span className="card-value">{fmt(p.metrics.annual_volatility)}</span>
            </div>
            <div className="card-section">
              <span className="card-label">Sharpe Ratio</span>
              <span className="card-value">{fmt(p.metrics.sharpe_ratio, false)}</span>
            </div>
            {bt && (
              <>
                <hr className="card-divider" />
                <p className="metric-group-label">Walk-forward backtest · after costs</p>
                <div className="card-section">
                  <span className="card-label">Backtest CAGR</span>
                  <span className="card-value" style={{ color: bt.metrics.cagr >= 0 ? theme.positive : theme.negative }}>
                    {fmt(bt.metrics.cagr)}
                  </span>
                </div>
                <div className="card-section">
                  <span className="card-label">Max Drawdown</span>
                  <span className="card-value" style={{ color: theme.negative }}>
                    {fmt(bt.metrics.max_drawdown)}
                  </span>
                </div>
                <div className="card-section">
                  <span className="card-label">Total Return</span>
                  <span className="card-value" style={{ color: bt.metrics.total_return >= 0 ? theme.positive : theme.negative }}>
                    {fmt(bt.metrics.total_return)}
                  </span>
                </div>
                <div className="card-section">
                  <span className="card-label">Backtest Sharpe</span>
                  <span className="card-value">{fmt(bt.metrics.sharpe_ratio, false)}</span>
                </div>
              </>
            )}
          </div>
        );
      })}
      </div>
    </>
  );
}
