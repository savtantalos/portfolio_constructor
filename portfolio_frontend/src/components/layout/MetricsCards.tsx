import type { PortfolioResult, BacktestResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';

interface Props {
  portfolios: PortfolioResult[];
  backtests: BacktestResult[];
  theme: ColorTheme;
}

const STRATEGY_LABELS: Record<string, string> = {
  equal_weight: 'Equal Weight',
  minimum_variance: 'Min Variance',
  maximum_sharpe: 'Max Sharpe',
};

function fmt(v: number | null, pct = true, decimals = 2): string {
  if (v === null) return '-';
  return pct ? `${(v * 100).toFixed(decimals)}%` : v.toFixed(decimals);
}

export default function MetricsCards({ portfolios, backtests, theme }: Props) {
  return (
    <div className="metrics-grid">
      {portfolios.map((p) => {
        const bt = backtests.find((b) => b.strategy === p.strategy);
        return (
          <div key={p.strategy} className="metric-card" style={{ borderColor: theme.colors[portfolios.indexOf(p) % theme.colors.length] }}>
            <h3 className="card-title">{STRATEGY_LABELS[p.strategy] || p.strategy}</h3>
            <div className="card-section">
              <span className="card-label">Expected Return</span>
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
  );
}
