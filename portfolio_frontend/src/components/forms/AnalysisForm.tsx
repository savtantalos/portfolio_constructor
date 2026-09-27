import { useState } from 'react';
import type { AnalysisRequest, Strategy } from '../../api/types';
import TickerSearch from './TickerSearch';

interface Props {
  onSubmit: (request: AnalysisRequest) => void;
  loading: boolean;
  initialRequest?: AnalysisRequest;
}

const ALL_STRATEGIES: { value: Strategy; label: string }[] = [
  { value: 'equal_weight', label: 'Equal Weight' },
  { value: 'minimum_variance', label: 'Minimum Variance' },
  { value: 'maximum_sharpe', label: 'Maximum Sharpe' },
];

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default function AnalysisForm({ onSubmit, loading, initialRequest }: Props) {
  const today = new Date();
  const twoYearsAgo = new Date(today);
  twoYearsAgo.setFullYear(today.getFullYear() - 2);

  const [tickers, setTickers] = useState<string[]>(initialRequest?.tickers ?? []);
  const [startDate, setStartDate] = useState(initialRequest?.start_date ?? formatDate(twoYearsAgo));
  const [endDate, setEndDate] = useState(initialRequest?.end_date ?? formatDate(today));
  const [strategies, setStrategies] = useState<Strategy[]>(initialRequest?.strategies ?? ['equal_weight', 'minimum_variance', 'maximum_sharpe']);
  const [minWeight, setMinWeight] = useState(initialRequest?.min_weight ?? 0);
  const [maxWeight, setMaxWeight] = useState(initialRequest?.max_weight ?? 1);
  const [riskFreeRate, setRiskFreeRate] = useState(initialRequest?.risk_free_rate ?? 0.02);
  const [monteCarloSamples, setMonteCarloSamples] = useState(initialRequest?.monte_carlo_samples ?? 1000);
  const [frontierPoints, setFrontierPoints] = useState(initialRequest?.frontier_points ?? 20);
  const [backtestEnabled, setBacktestEnabled] = useState(initialRequest?.backtest.enabled ?? true);
  const [lookbackDays, setLookbackDays] = useState(initialRequest?.backtest.lookback_days ?? 252);
  const [rebalanceEvery, setRebalanceEvery] = useState(initialRequest?.backtest.rebalance_every ?? 21);
  const [transactionCostBps, setTransactionCostBps] = useState(initialRequest?.backtest.transaction_cost_bps ?? 10);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const toggleStrategy = (s: Strategy) => {
    setStrategies((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      tickers,
      start_date: startDate,
      end_date: endDate,
      base_currency: initialRequest?.base_currency ?? 'USD',
      strategies,
      min_weight: minWeight,
      max_weight: maxWeight,
      risk_free_rate: riskFreeRate,
      monte_carlo_samples: monteCarloSamples,
      frontier_points: frontierPoints,
      random_seed: initialRequest?.random_seed ?? 42,
      backtest: {
        enabled: backtestEnabled,
        lookback_days: lookbackDays,
        rebalance_every: rebalanceEvery,
        transaction_cost_bps: transactionCostBps,
      },
    });
  };

  const canSubmit = tickers.length >= 2 && strategies.length >= 1 && !loading;

  return (
    <form onSubmit={handleSubmit} className="analysis-form">
      <TickerSearch selected={tickers} onChange={setTickers} />

      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Start Date</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="form-input" />
        </div>
        <div className="form-group">
          <label className="form-label">End Date</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="form-input" />
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">Strategies</label>
        <div className="strategy-toggles">
          {ALL_STRATEGIES.map((s) => (
            <button
              key={s.value}
              type="button"
              className={`strategy-btn ${strategies.includes(s.value) ? 'active' : ''}`}
              onClick={() => toggleStrategy(s.value)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">
          <input type="checkbox" checked={backtestEnabled} onChange={(e) => setBacktestEnabled(e.target.checked)} />
          {' '}Enable Backtesting
        </label>
      </div>

      <button
        type="button"
        className="toggle-advanced"
        onClick={() => setShowAdvanced(!showAdvanced)}
      >
        {showAdvanced ? 'Hide' : 'Show'} Advanced Settings
      </button>

      {showAdvanced && (
        <div className="advanced-settings">
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Min Weight</label>
              <input type="number" step="0.01" min="0" max="1" value={minWeight}
                onChange={(e) => setMinWeight(Number(e.target.value))} className="form-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Max Weight</label>
              <input type="number" step="0.01" min="0.01" max="1" value={maxWeight}
                onChange={(e) => setMaxWeight(Number(e.target.value))} className="form-input" />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Risk-Free Rate</label>
              <input type="number" step="0.005" min="-0.99" max="1" value={riskFreeRate}
                onChange={(e) => setRiskFreeRate(Number(e.target.value))} className="form-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Monte Carlo Samples</label>
              <input type="number" min="0" max="5000" value={monteCarloSamples}
                onChange={(e) => setMonteCarloSamples(Number(e.target.value))} className="form-input" />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Frontier Points</label>
              <input type="number" min="0" max="50" value={frontierPoints}
                onChange={(e) => setFrontierPoints(Number(e.target.value))} className="form-input" />
            </div>
          </div>
          {backtestEnabled && (
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Lookback (days)</label>
                <input type="number" min="60" max="1260" value={lookbackDays}
                  onChange={(e) => setLookbackDays(Number(e.target.value))} className="form-input" />
              </div>
              <div className="form-group">
                <label className="form-label">Rebalance Every</label>
                <input type="number" min="1" max="252" value={rebalanceEvery}
                  onChange={(e) => setRebalanceEvery(Number(e.target.value))} className="form-input" />
              </div>
              <div className="form-group">
                <label className="form-label">Cost (bps)</label>
                <input type="number" min="0" max="500" value={transactionCostBps}
                  onChange={(e) => setTransactionCostBps(Number(e.target.value))} className="form-input" />
              </div>
            </div>
          )}
        </div>
      )}

      <button type="submit" disabled={!canSubmit} className="submit-btn">
        {loading ? 'Analyzing...' : initialRequest ? 'Rerun Analysis' : 'Run Analysis'}
      </button>
    </form>
  );
}
