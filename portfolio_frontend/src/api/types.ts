// TypeScript types mirroring portfolio_backend/models.py

export type Strategy = 'equal_weight' | 'minimum_variance' | 'maximum_sharpe'
  | 'buy_and_hold' | 'inverse_volatility' | 'equal_risk_contribution';

export interface BacktestConfig {
  enabled: boolean;
  lookback_days: number;
  rebalance_every: number;
  transaction_cost_bps: number;
}

export interface ScenarioConfig {
  enabled: boolean;
  horizon_days: number;
  block_days: number;
  paths: number;
  percentile_levels: number[];
  random_seed?: number | null;
}

export interface AnalysisRequest {
  tickers: string[];
  start_date: string;
  end_date: string;
  base_currency: string;
  strategies: Strategy[];
  benchmark_ticker?: string | null;
  min_weight: number;
  max_weight: number;
  risk_free_rate: number;
  monte_carlo_samples: number;
  frontier_points: number;
  random_seed: number;
  scenario?: ScenarioConfig;
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
  sortino_ratio?: number | null;
  calmar_ratio?: number | null;
  max_drawdown_duration_days?: number | null;
  tracking_error?: number | null;
  information_ratio?: number | null;
  excess_total_return?: number | null;
}

export interface BacktestResult {
  strategy: Strategy;
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  rebalances: RebalanceEvent[];
}

export interface BenchmarkResult {
  ticker: string;
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  rebalances: RebalanceEvent[];
}

export interface ScenarioPercentileMetrics {
  terminal_return: number;
  max_drawdown: number;
  terminal_wealth: number;
  cagr: number | null;
}

export interface ScenarioFanPath {
  percentile: number;
  dates: string[];
  values: number[];
}

export interface ScenarioSummaryStatistics {
  terminal_wealth_mean: number;
  terminal_wealth_median: number;
  max_drawdown_worst_5pct: number;
  terminal_return_5pct: number;
  terminal_return_95pct: number;
}

export interface ScenarioResult {
  strategy: Strategy;
  weights: Record<string, number>;
  percentiles: Record<string, ScenarioPercentileMetrics>;
  fan_paths: ScenarioFanPath[];
  summary_statistics: ScenarioSummaryStatistics;
}

export interface EstimationSnapshot {
  tickers: string[];
  expected_annual_returns: number[];
  optimizer_covariance_annual: number[][];
  annualization_factor: 252;
  mean_estimator: 'arithmetic_daily_mean';
  covariance_estimator: 'LedoitWolf';
}

export interface AnalyticsResult {
  estimation?: EstimationSnapshot | null;
  portfolios: PortfolioResult[];
  monte_carlo: PortfolioPoint[];
  efficient_frontier: PortfolioPoint[];
  correlation: Record<string, Record<string, number | null>>;
  backtests: BacktestResult[];
  benchmark?: BenchmarkResult | null;
  scenarios?: ScenarioResult[] | null;
  warnings: string[];
}

export interface PriceSnapshot {
  tickers: string[];
  dates: string[];
  prices: number[][];
}

export interface AnalysisDataset {
  id: string;
  title: string;
  category: 'Market data' | 'Risk & estimates' | 'Portfolios' | 'Backtests';
  description: string;
  columns: string[];
  rows: (string | number | null)[][];
}

export interface AnalysisDataResponse {
  datasets: AnalysisDataset[];
  notes: string[];
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
