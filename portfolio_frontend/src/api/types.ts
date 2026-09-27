// TypeScript types mirroring portfolio_backend/models.py

export type Strategy = 'equal_weight' | 'minimum_variance' | 'maximum_sharpe';

export interface BacktestConfig {
  enabled: boolean;
  lookback_days: number;
  rebalance_every: number;
  transaction_cost_bps: number;
}

export interface AnalysisRequest {
  tickers: string[];
  start_date: string;
  end_date: string;
  base_currency: string;
  strategies: Strategy[];
  min_weight: number;
  max_weight: number;
  risk_free_rate: number;
  monte_carlo_samples: number;
  frontier_points: number;
  random_seed: number;
  backtest: BacktestConfig;
}

export interface Instrument {
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string | null;
  instrument_type: string | null;
}

export interface RiskMetrics {
  expected_annual_return: number;
  annual_volatility: number;
  sharpe_ratio: number | null;
}

export interface PortfolioPoint {
  weights: Record<string, number>;
  metrics: RiskMetrics;
}

export interface PortfolioResult extends PortfolioPoint {
  strategy: Strategy;
  risk_contributions: Record<string, number>;
}

export interface EquityPoint {
  date: string;
  value: number;
  drawdown: number;
}

export interface RebalanceEvent {
  date: string;
  weights: Record<string, number>;
  turnover: number;
  transaction_cost: number;
}

export interface BacktestMetrics {
  total_return: number;
  cagr: number;
  annual_volatility: number;
  sharpe_ratio: number | null;
  max_drawdown: number;
  total_turnover: number;
  total_transaction_cost: number;
}

export interface BacktestResult {
  strategy: Strategy;
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  rebalances: RebalanceEvent[];
}

export interface AnalyticsResult {
  portfolios: PortfolioResult[];
  monte_carlo: PortfolioPoint[];
  efficient_frontier: PortfolioPoint[];
  correlation: Record<string, Record<string, number | null>>;
  backtests: BacktestResult[];
  warnings: string[];
}

export interface PriceSnapshot {
  tickers: string[];
  dates: string[];
  prices: number[][];
}

export interface DataSummary {
  provider: string;
  fetched_at: string;
  requested_start: string;
  requested_end: string;
  effective_start: string;
  effective_end: string;
  price_observations: number;
  return_observations: number;
  currency: string;
  adjustment: string;
  snapshot_sha256: string;
  instruments: Instrument[];
}

export interface AnalysisResponse {
  id: string;
  created_at: string;
  engine_version: string;
  request: AnalysisRequest;
  data: DataSummary;
  results: AnalyticsResult;
  assumptions: string[];
}

export interface AnalysisSummary {
  id: string;
  created_at: string;
  tickers: string[];
  start_date: string;
  end_date: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

export interface HealthResponse {
  status: 'ok';
  version: string;
}
