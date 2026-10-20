import type { BacktestResult, BenchmarkResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { benchmarkLabel, STRATEGY_LABELS, strategyColor } from '../strategyMetadata';
import PlotWrapper from './PlotWrapper';

interface Props {
  backtests: BacktestResult[];
  benchmark?: BenchmarkResult | null;
  theme: ColorTheme;
}

export default function DrawdownChart({ backtests, benchmark, theme }: Props) {
  const data: Plotly.Data[] = backtests.map((bt) => ({
    x: bt.equity_curve.map((p) => p.date),
    y: bt.equity_curve.map((p) => p.drawdown * 100),
    fill: 'tozeroy',
    type: 'scatter',
    mode: 'lines',
    name: STRATEGY_LABELS[bt.strategy],
    line: { color: strategyColor(bt.strategy, theme.colors), width: 1.5 },
    fillcolor: strategyColor(bt.strategy, theme.colors) + '30',
    hovertemplate: '%{x}<br>Drawdown: %{y:.2f}%<extra>%{fullData.name}</extra>',
  }));
  if (benchmark) data.push({
    x: benchmark.equity_curve.map((p) => p.date),
    y: benchmark.equity_curve.map((p) => p.drawdown * 100),
    type: 'scatter',
    mode: 'lines',
    name: benchmarkLabel(benchmark.ticker),
    line: { color: theme.text, width: 2.5, dash: 'dash' },
    hovertemplate: '%{x}<br>Drawdown: %{y:.2f}%<extra>%{fullData.name}</extra>',
  });

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
