import type { AnalysisRequest } from '../api/types';

export function normalizeBenchmarkTicker(value: string | null | undefined, backtestEnabled: boolean): string | null {
  return backtestEnabled ? value?.trim().toUpperCase() || null : null;
}

function parseDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
    && parsed.getUTCFullYear() >= 1 ? parsed : null;
}

export function startDateForYears(endDate: string, years: number): string | null {
  const end = parseDate(endDate);
  if (!end || !Number.isInteger(years) || years < 1 || end.getUTCFullYear() <= years) return null;
  const start = new Date(end);
  start.setUTCFullYear(end.getUTCFullYear() - years);
  if (start.getUTCMonth() !== end.getUTCMonth()) start.setUTCDate(0);
  return start.toISOString().slice(0, 10);
}

export function validateConfiguration(request: AnalysisRequest, today: string): string[] {
  const errors: string[] = [];
  const count = request.tickers.length;
  if (count < 2 || count > 30) errors.push('Select between 2 and 30 assets.');
  if (request.strategies.length === 0) errors.push('Select at least one strategy.');
  if (request.benchmark_ticker != null) {
    if (!/^[A-Z0-9^][A-Z0-9.^=_-]{0,31}$/.test(request.benchmark_ticker)) {
      errors.push('Benchmark symbol must be 1–32 characters: start with a letter, number or ^; then use letters, numbers, . ^ = _ or -.');
    }
    if (!request.backtest.enabled) errors.push('Enable backtesting to use a benchmark.');
  }

  const start = parseDate(request.start_date);
  const end = parseDate(request.end_date);
  if (!start || !end) errors.push('Enter a valid start date and end date.');
  if (start && end) {
    if (start >= end) errors.push('Start date must be before end date.');
    if (request.end_date > today) errors.push('End date cannot be in the future.');
    if (end.getTime() - start.getTime() > 366 * 20 * 86400000) {
      errors.push('The historical window cannot exceed 20 years.');
    }
  }

  const { min_weight: min, max_weight: max } = request;
  const validMin = Number.isFinite(min) && min >= 0 && min <= 1;
  const validMax = Number.isFinite(max) && max > 0 && max <= 1;
  if (!validMin) errors.push('Minimum weight must be between 0 and 1.');
  if (!validMax) errors.push('Maximum weight must be greater than 0 and at most 1.');
  if (validMin && validMax) {
    if (min > max) errors.push('Minimum weight cannot exceed maximum weight.');
    if (count >= 2 && (count * min > 1 + 1e-10 || count * max < 1 - 1e-10)) {
      errors.push(`Weight bounds cannot fully allocate ${count} assets. Minimum × ${count} must be ≤ 1 and maximum × ${count} must be ≥ 1. Adjust the bounds in advanced settings or change the basket.`);
    }
  }

  if (!Number.isFinite(request.risk_free_rate) || request.risk_free_rate <= -1 || request.risk_free_rate > 1) {
    errors.push('Annual risk-free rate must be greater than -1 and at most 1.');
  }
  const integerFields: [string, number, number, number][] = [
    ['Monte Carlo samples', request.monte_carlo_samples, 0, 5000],
    ['Frontier points', request.frontier_points, 0, 50],
    ['Backtest lookback', request.backtest.lookback_days, 60, 1260],
    ['Rebalance interval', request.backtest.rebalance_every, 1, 252],
  ];
  if (request.scenario) {
    integerFields.push(
      ['Scenario horizon', request.scenario.horizon_days, 21, 1260],
      ['Scenario block length', request.scenario.block_days, 1, 63],
      ['Scenario paths', request.scenario.paths, 100, 5000],
    );
  }
  for (const [label, value, lower, upper] of integerFields) {
    if (!Number.isInteger(value) || value < lower || value > upper) {
      errors.push(`${label} must be a whole number between ${lower} and ${upper}.`);
    }
  }
  const cost = request.backtest.transaction_cost_bps;
  if (!Number.isFinite(cost) || cost < 0 || cost > 500) {
    errors.push('Transaction cost must be between 0 and 500 basis points.');
  }
  return errors;
}
