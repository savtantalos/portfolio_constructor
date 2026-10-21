import type { Strategy } from '../api/types';

export const STRATEGY_LABELS: Record<Strategy, string> = {
  equal_weight: 'Equal Weight',
  minimum_variance: 'Minimum Variance',
  maximum_sharpe: 'Maximum Sharpe',
  buy_and_hold: 'Buy & Hold',
  inverse_volatility: 'Inverse Volatility',
  equal_risk_contribution: 'Equal Risk Contribution',
};

export const STRATEGY_OPTIONS: { value: Strategy; label: string; description: string }[] = [
  { value: 'equal_weight', label: STRATEGY_LABELS.equal_weight, description: 'Allocates equally to every asset and restores equal weights at each backtest rebalance.' },
  { value: 'minimum_variance', label: STRATEGY_LABELS.minimum_variance, description: 'Seeks the lowest estimated portfolio volatility within your weight bounds.' },
  { value: 'maximum_sharpe', label: STRATEGY_LABELS.maximum_sharpe, description: 'Seeks the highest estimated return above the risk-free rate per unit of risk.' },
  { value: 'buy_and_hold', label: STRATEGY_LABELS.buy_and_hold, description: 'Equal weights at entry; then holds without rebalancing as weights drift.' },
  { value: 'inverse_volatility', label: STRATEGY_LABELS.inverse_volatility, description: 'Scales weights by inverse volatility from the covariance diagonal, within bounds; ignores correlations.' },
  { value: 'equal_risk_contribution', label: STRATEGY_LABELS.equal_risk_contribution, description: 'Uses the full covariance matrix to seek equal risk contributions; approximate under weight bounds.' },
];

const STRATEGY_COLOR_INDEX: Record<Strategy, number> = {
  equal_weight: 0,
  minimum_variance: 1,
  maximum_sharpe: 2,
  buy_and_hold: 3,
  inverse_volatility: 4,
  equal_risk_contribution: 5,
};

export function strategyColor(strategy: Strategy, colors: string[]): string {
  return colors[STRATEGY_COLOR_INDEX[strategy] % colors.length] ?? '#808080';
}

export function benchmarkLabel(ticker: string): string {
  return `${ticker} buy & hold`;
}
