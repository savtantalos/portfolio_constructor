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

export default function DrawdownChart({ backtests, theme }: Props) {
  const data: Plotly.Data[] = backtests.map((bt, i) => ({
    x: bt.equity_curve.map((p) => p.date),
    y: bt.equity_curve.map((p) => p.drawdown * 100),
    fill: 'tozeroy',
    type: 'scatter',
    mode: 'lines',
    name: STRATEGY_LABELS[bt.strategy] || bt.strategy,
    line: { color: theme.colors[i % theme.colors.length], width: 1.5 },
    fillcolor: theme.colors[i % theme.colors.length] + '30',
    hovertemplate: '%{x}<br>Drawdown: %{y:.2f}%<extra></extra>',
  }));

  return (
    <PlotWrapper
      data={data}
      title="Drawdown (%)"
      theme={theme}
      xTitle="Date"
      yTitle="Drawdown (%)"
      height={350}
    />
  );
}
