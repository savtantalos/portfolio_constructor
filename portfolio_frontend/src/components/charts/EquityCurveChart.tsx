import type { BacktestResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';

interface Props {
  backtests: BacktestResult[];
  theme: ColorTheme;
}

const STRATEGY_LABELS: Record<string, string> = {
  equal_weight: 'Equal Weight',
  minimum_variance: 'Min Variance',
  maximum_sharpe: 'Max Sharpe',
};

export default function EquityCurveChart({ backtests, theme }: Props) {
  const data: Plotly.Data[] = backtests.map((bt, i) => ({
    x: bt.equity_curve.map((p) => p.date),
    y: bt.equity_curve.map((p) => p.value),
    mode: 'lines',
    type: 'scatter',
    name: STRATEGY_LABELS[bt.strategy] || bt.strategy,
    line: { color: theme.colors[i % theme.colors.length], width: 2 },
    hovertemplate: '%{x}<br>NAV: %{y:.4f}<extra></extra>',
  }));

  return (
    <PlotWrapper
      data={data}
      title="Backtest Equity Curves"
      theme={theme}
      xTitle="Date"
      yTitle="Normalized Wealth"
      height={450}
    />
  );
}
