import type { BacktestResult, BenchmarkResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { benchmarkLabel, STRATEGY_LABELS, strategyColor } from '../strategyMetadata';
import PlotWrapper from './PlotWrapper';

interface Props {
  backtests: BacktestResult[];
  benchmark?: BenchmarkResult | null;
  theme: ColorTheme;
}

export default function EquityCurveChart({ backtests, benchmark, theme }: Props) {
  const data: Plotly.Data[] = backtests.map((bt) => ({
    x: bt.equity_curve.map((p) => p.date),
    y: bt.equity_curve.map((p) => p.value),
    mode: 'lines',
    type: 'scatter',
    name: STRATEGY_LABELS[bt.strategy],
    line: { color: strategyColor(bt.strategy, theme.colors), width: 2 },
    hovertemplate: '%{x}<br>NAV: %{y:.4f}<extra>%{fullData.name}</extra>',
  }));
  if (benchmark) data.push({
    x: benchmark.equity_curve.map((p) => p.date),
    y: benchmark.equity_curve.map((p) => p.value),
    mode: 'lines',
    type: 'scatter',
    name: benchmarkLabel(benchmark.ticker),
    line: { color: theme.text, width: 2.5, dash: 'dash' },
    hovertemplate: '%{x}<br>NAV: %{y:.4f}<extra>%{fullData.name}</extra>',
  });

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
