import type { BacktestMetrics, BacktestResult, BenchmarkResult } from '../api/types';
import { benchmarkLabel, STRATEGY_LABELS, strategyColor } from './strategyMetadata.ts';

type MetricUnit = 'percent' | 'ratio' | 'days' | 'turnover' | 'wealth' | 'percentage_points';

export const BACKTEST_METRICS: { key: keyof BacktestMetrics; label: string; unit: MetricUnit }[] = [
  { key: 'total_return', label: 'Net return', unit: 'percent' },
  { key: 'cagr', label: 'CAGR', unit: 'percent' },
  { key: 'annual_volatility', label: 'Annual vol.', unit: 'percent' },
  { key: 'sharpe_ratio', label: 'Sharpe', unit: 'ratio' },
  { key: 'sortino_ratio', label: 'Sortino', unit: 'ratio' },
  { key: 'calmar_ratio', label: 'Calmar', unit: 'ratio' },
  { key: 'max_drawdown', label: 'Max drawdown', unit: 'percent' },
  { key: 'max_drawdown_duration_days', label: 'Max DD duration', unit: 'days' },
  { key: 'total_turnover', label: 'Total turnover', unit: 'turnover' },
  { key: 'total_transaction_cost', label: 'Costs (wealth units)', unit: 'wealth' },
  { key: 'tracking_error', label: 'Tracking error (ann.)', unit: 'percent' },
  { key: 'information_ratio', label: 'Information ratio', unit: 'ratio' },
  { key: 'excess_total_return', label: 'Excess net return', unit: 'percentage_points' },
];

export function formatBacktestMetric(value: number | null | undefined, unit: MetricUnit): string {
  if (value == null || !Number.isFinite(value)) return '—';
  switch (unit) {
    case 'percent': return `${(value * 100).toFixed(2)}%`;
    case 'percentage_points': return `${(value * 100).toFixed(2)} pp`;
    case 'days': return `${value.toFixed(0)} days`;
    case 'turnover': return `${value.toFixed(2)}×`;
    case 'wealth': return value.toFixed(4);
    case 'ratio': return value.toFixed(2);
  }
}

export function backtestComparisonRows(backtests: BacktestResult[], benchmark: BenchmarkResult | null | undefined, colors: string[], benchmarkColor: string) {
  const rows = backtests.map((backtest) => ({
    key: backtest.strategy as string,
    label: STRATEGY_LABELS[backtest.strategy],
    metrics: backtest.metrics,
    color: strategyColor(backtest.strategy, colors),
    isBenchmark: false,
  }));
  if (benchmark) rows.push({
    key: `benchmark-${benchmark.ticker}`,
    label: benchmarkLabel(benchmark.ticker),
    metrics: benchmark.metrics,
    color: benchmarkColor,
    isBenchmark: true,
  });
  return rows;
}
