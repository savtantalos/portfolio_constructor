import { useState } from 'react';
import type { AnalysisRequest, Strategy } from '../../api/types';
import { normalizeBenchmarkTicker, startDateForYears, validateConfiguration } from '../analysisConfiguration';
import { STRATEGY_OPTIONS } from '../strategyMetadata';
import TickerSearch from './TickerSearch';

interface Props {
  onSubmit: (request: AnalysisRequest) => void;
  loading: boolean;
  initialRequest?: AnalysisRequest;
}

const BASKETS = [
  { label: 'Global ETFs', tickers: ['VTI', 'VXUS', 'BND'] },
  { label: 'US equities', tickers: ['AAPL', 'MSFT', 'GOOGL', 'AMZN'] },
  { label: 'Stocks & bonds', tickers: ['SPY', 'AGG'] },
];

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatPercent(value: number): string {
  return Number.isFinite(value) ? `${Number((value * 100).toFixed(4))}%` : 'Not set';
}

export default function AnalysisForm({ onSubmit, loading, initialRequest }: Props) {
  const today = formatDate(new Date());
  const [tickers, setTickers] = useState<string[]>(initialRequest?.tickers ?? []);
  const [startDate, setStartDate] = useState(initialRequest?.start_date ?? startDateForYears(today, 2)!);
  const [endDate, setEndDate] = useState(initialRequest?.end_date ?? today);
  const [strategies, setStrategies] = useState<Strategy[]>(initialRequest?.strategies ?? ['equal_weight', 'minimum_variance', 'maximum_sharpe']);
  const [minWeight, setMinWeight] = useState(initialRequest?.min_weight ?? 0);
  const [maxWeight, setMaxWeight] = useState(initialRequest?.max_weight ?? 1);
  const [riskFreeRate, setRiskFreeRate] = useState(initialRequest?.risk_free_rate ?? 0.02);
  const [monteCarloSamples, setMonteCarloSamples] = useState(initialRequest?.monte_carlo_samples ?? 1000);
  const [frontierPoints, setFrontierPoints] = useState(initialRequest?.frontier_points ?? 20);
  const [backtestEnabled, setBacktestEnabled] = useState(initialRequest?.backtest.enabled ?? true);
  const [benchmarkTicker, setBenchmarkTicker] = useState(initialRequest?.benchmark_ticker ?? '');
  const [lookbackDays, setLookbackDays] = useState(initialRequest?.backtest.lookback_days ?? 252);
  const [rebalanceEvery, setRebalanceEvery] = useState(initialRequest?.backtest.rebalance_every ?? 21);
  const [transactionCostBps, setTransactionCostBps] = useState(initialRequest?.backtest.transaction_cost_bps ?? 10);
  const [scenarioEnabled, setScenarioEnabled] = useState(initialRequest?.scenario?.enabled ?? true);
  const [scenarioHorizon, setScenarioHorizon] = useState(initialRequest?.scenario?.horizon_days ?? 252);
  const [scenarioBlock, setScenarioBlock] = useState(initialRequest?.scenario?.block_days ?? 5);
  const [scenarioPaths, setScenarioPaths] = useState(initialRequest?.scenario?.paths ?? 1000);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const request: AnalysisRequest = {
    tickers,
    start_date: startDate,
    end_date: endDate,
    base_currency: initialRequest?.base_currency ?? 'USD',
    strategies,
    benchmark_ticker: normalizeBenchmarkTicker(benchmarkTicker, backtestEnabled),
    min_weight: minWeight,
    max_weight: maxWeight,
    risk_free_rate: riskFreeRate,
    monte_carlo_samples: monteCarloSamples,
    frontier_points: frontierPoints,
    random_seed: initialRequest?.random_seed ?? 42,
    scenario: {
      enabled: scenarioEnabled,
      horizon_days: scenarioHorizon,
      block_days: scenarioBlock,
      paths: scenarioPaths,
      percentile_levels: initialRequest?.scenario?.percentile_levels ?? [0.05, 0.25, 0.5, 0.75, 0.95],
      random_seed: initialRequest?.scenario?.random_seed ?? null,
    },
    backtest: {
      enabled: backtestEnabled,
      lookback_days: lookbackDays,
      rebalance_every: rebalanceEvery,
      transaction_cost_bps: transactionCostBps,
    },
  };
  const validationErrors = validateConfiguration(request, today);
  const canSubmit = validationErrors.length === 0 && !loading;

  const toggleStrategy = (strategy: Strategy) => {
    setStrategies((prev) =>
      prev.includes(strategy) ? prev.filter((value) => value !== strategy) : [...prev, strategy]
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (canSubmit) onSubmit(request);
  };

  const numberField = (id: string, label: string, value: number, onChange: (value: number) => void, min: number, max: number, step: number | 'any' = 'any') => (
    <div className="form-group">
      <label htmlFor={id} className="form-label">{label}</label>
      <input id={id} type="number" min={min} max={max} step={step} required
        value={Number.isFinite(value) ? value : ''}
        onChange={(e) => onChange(e.target.valueAsNumber)} className="form-input" />
    </div>
  );

  return (
    <form onSubmit={handleSubmit} noValidate className="analysis-form research-form-layout" aria-busy={loading}>
      <fieldset disabled={loading}>
        <legend className="terminal-eyebrow">Run inputs</legend>
        <section className="research-panel" aria-labelledby="basket-heading">
          <div className="panel-heading">
            <h2 id="basket-heading">Build your basket</h2>
            <span className="terminal-eyebrow">01 / Assets</span>
          </div>
          <p id="basket-hint" className="form-hint">Choose 2–30 assets. Example baskets replace all selected tickers.</p>
          <div className="preset-row" role="group" aria-label="Example baskets — replace selected tickers" aria-describedby="basket-hint">
            {BASKETS.map((basket) => (
              <button key={basket.label} type="button" className="preset-btn"
                aria-label={`${basket.label}: replace selected tickers with ${basket.tickers.join(', ')}`}
                aria-pressed={tickers.length === basket.tickers.length && basket.tickers.every((ticker) => tickers.includes(ticker))}
                onClick={() => setTickers([...basket.tickers])}>
                <span>{basket.label}</span>
                <span className="form-hint">{basket.tickers.join(' · ')}</span>
              </button>
            ))}
          </div>
          <TickerSearch selected={tickers} onChange={(next) => { if (!loading) setTickers(next); }} />
        </section>

        <section className="research-panel" aria-labelledby="dates-heading">
          <div className="panel-heading">
            <h2 id="dates-heading">Set the research window</h2>
            <span className="terminal-eyebrow">02 / Dates</span>
          </div>
          <div className="preset-row" role="group" aria-label="Historical window shortcuts" aria-describedby="date-hint">
            {[1, 3, 5].map((years) => {
              const shortcutStart = startDateForYears(endDate, years);
              return (
                <button key={years} type="button" className="preset-btn" disabled={!shortcutStart}
                  aria-label={`${years} year${years === 1 ? '' : 's'} ending on the selected end date`}
                  aria-pressed={Boolean(shortcutStart && startDate === shortcutStart)}
                  onClick={() => { if (shortcutStart) setStartDate(shortcutStart); }}>
                  {years}Y
                </button>
              );
            })}
          </div>
          <p id="date-hint" className="form-hint">Shortcuts count back from your chosen end date. Maximum window: 20 years; no future dates.</p>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="start-date" className="form-label">Start date</label>
              <input id="start-date" type="date" required value={startDate} max={endDate || today}
                aria-describedby="date-hint" onChange={(e) => setStartDate(e.target.value)} className="form-input" />
            </div>
            <div className="form-group">
              <label htmlFor="end-date" className="form-label">End date</label>
              <input id="end-date" type="date" required value={endDate} max={today}
                aria-describedby="date-hint" onChange={(e) => setEndDate(e.target.value)} className="form-input" />
            </div>
          </div>
        </section>

        <section className="research-panel" aria-labelledby="strategies-heading">
          <div className="panel-heading">
            <h2 id="strategies-heading">Choose your strategies</h2>
            <span className="terminal-eyebrow">03 / Methods</span>
          </div>
          <p className="form-hint">Compare one or more methods using the same historical data.</p>
          <div className="strategy-toggles" role="group" aria-labelledby="strategies-heading">
            {STRATEGY_OPTIONS.map((strategy) => (
              <button key={strategy.value} type="button"
                className={`strategy-btn ${strategies.includes(strategy.value) ? 'active' : ''}`}
                aria-pressed={strategies.includes(strategy.value)}
                aria-describedby={`description-${strategy.value}`}
                onClick={() => toggleStrategy(strategy.value)}>
                <span>{strategy.label}</span>
                <span id={`description-${strategy.value}`} className="strategy-description">{strategy.description}</span>
              </button>
            ))}
          </div>
          <div className="form-group">
            <label htmlFor="backtest-enabled" className="form-label">
              <input id="backtest-enabled" type="checkbox" checked={backtestEnabled}
                aria-describedby="backtest-hint" onChange={(e) => setBacktestEnabled(e.target.checked)} />
              {' '}Enable backtesting
            </label>
            <p id="backtest-hint" className="form-hint">Walk-forward evaluation with transaction costs and periodic rebalancing, except Buy &amp; Hold: equal weights at entry with no subsequent rebalance. Short windows may not contain enough observations for your lookback.</p>
          </div>
          <div className="form-group benchmark-field">
            <label htmlFor="benchmark-symbol" className="form-label">Benchmark symbol (optional; leave blank for none)</label>
            <input id="benchmark-symbol" type="text" className="form-input" value={benchmarkTicker}
              disabled={!backtestEnabled} autoCapitalize="characters" autoComplete="off" spellCheck={false}
              placeholder="e.g. SPY" aria-describedby="benchmark-hint"
              onChange={(e) => setBenchmarkTicker(e.target.value)} />
            <p id="benchmark-hint" className="form-hint">Backtesting only. The benchmark buys and holds one symbol on the same evaluation dates, with the same entry fee rate. Selecting it may shorten the common data window. Clear the field to remove it; it is not submitted while backtesting is off.</p>
          </div>
          <div className="form-group">
            <label htmlFor="scenario-enabled" className="form-label">
              <input id="scenario-enabled" type="checkbox" checked={scenarioEnabled}
                aria-describedby="scenario-hint" onChange={(e) => setScenarioEnabled(e.target.checked)} />
              {' '}Enable scenario simulation
            </label>
            <p id="scenario-hint" className="form-hint">Block-bootstrap resampling of historical return blocks projects forward outcome ranges for each fitted allocation. These are conditional scenarios, not forecasts. Horizon, block length, and path count are in advanced settings.</p>
          </div>
        </section>

        <button type="button" className="toggle-advanced" aria-expanded={showAdvanced} aria-controls="advanced-settings"
          onClick={() => setShowAdvanced(!showAdvanced)}>
          {showAdvanced ? 'Hide' : 'Show'} advanced settings
        </button>
        <div id="advanced-settings" className="advanced-settings" hidden={!showAdvanced}>
          <p className="form-hint">Weights and the annual risk-free rate are fractions: 0.25 = 25%. Weight bounds must allow a fully invested portfolio.</p>
          <div className="form-row">
            {numberField('min-weight', 'Minimum weight', minWeight, setMinWeight, 0, 1)}
            {numberField('max-weight', 'Maximum weight (> 0)', maxWeight, setMaxWeight, 0, 1)}
          </div>
          <div className="form-row">
            {numberField('risk-free-rate', 'Annual risk-free rate (> -1)', riskFreeRate, setRiskFreeRate, -1, 1)}
            {numberField('monte-carlo-samples', 'Monte Carlo samples', monteCarloSamples, setMonteCarloSamples, 0, 5000, 1)}
          </div>
          <div className="form-row">
            {numberField('frontier-points', 'Frontier points', frontierPoints, setFrontierPoints, 0, 50, 1)}
          </div>
          <p className="form-hint">Backtest intervals count trading return observations, not calendar days. Settings are retained when backtesting is off.</p>
          <div className="form-row">
            {numberField('lookback-days', 'Lookback (observations)', lookbackDays, setLookbackDays, 60, 1260, 1)}
            {numberField('rebalance-every', 'Rebalance every (observations)', rebalanceEvery, setRebalanceEvery, 1, 252, 1)}
            {numberField('transaction-cost', 'Transaction cost (bps)', transactionCostBps, setTransactionCostBps, 0, 500)}
          </div>
          <p className="form-hint">Scenario horizon counts calendar days; block length sets how many consecutive daily returns are resampled together. More paths reduce sampling noise but increase runtime.</p>
          <div className="form-row">
            {numberField('scenario-horizon', 'Scenario horizon (days)', scenarioHorizon, setScenarioHorizon, 21, 1260, 1)}
            {numberField('scenario-block', 'Block length (days)', scenarioBlock, setScenarioBlock, 1, 63, 1)}
            {numberField('scenario-paths', 'Scenario paths', scenarioPaths, setScenarioPaths, 100, 5000, 1)}
          </div>
        </div>
      </fieldset>

      <aside className="research-panel run-summary" aria-labelledby="run-summary-heading">
        <span className="terminal-eyebrow">Configuration / Live</span>
        <div className="panel-heading"><h2 id="run-summary-heading">Run summary</h2></div>
        <dl className="summary-list">
          <div><dt>Assets · {tickers.length}</dt><dd>{tickers.length ? tickers.join(', ') : 'No assets selected'}</dd></div>
          <div><dt>Research window</dt><dd>{startDate || 'Not set'} → {endDate || 'Not set'}</dd></div>
          <div><dt>Strategies · {strategies.length}</dt><dd>{STRATEGY_OPTIONS.filter((strategy) => strategies.includes(strategy.value)).map((strategy) => strategy.label).join(', ') || 'None selected'}</dd></div>
          <div><dt>Weight bounds / asset</dt><dd>{formatPercent(minWeight)} – {formatPercent(maxWeight)}</dd></div>
          <div><dt>Annual risk-free rate</dt><dd>{formatPercent(riskFreeRate)}</dd></div>
          <div><dt>Monte Carlo / frontier</dt><dd>{Number.isFinite(monteCarloSamples) ? monteCarloSamples : 'Not set'} samples / {Number.isFinite(frontierPoints) ? frontierPoints : 'Not set'} points</dd></div>
          <div><dt>Backtest</dt><dd>{backtestEnabled ? 'Enabled' : 'Disabled'}</dd></div>
          {backtestEnabled && (
            <>
              <div><dt>Lookback / rebalance</dt><dd>{Number.isFinite(lookbackDays) ? lookbackDays : 'Not set'} / {Number.isFinite(rebalanceEvery) ? rebalanceEvery : 'Not set'} observations</dd></div>
              <div><dt>Transaction cost</dt><dd>{Number.isFinite(transactionCostBps) ? transactionCostBps : 'Not set'} bps</dd></div>
              <div><dt>Benchmark</dt><dd>{request.benchmark_ticker ?? 'None'}</dd></div>
            </>
          )}
          <div><dt>Scenarios</dt><dd>{scenarioEnabled ? `${Number.isFinite(scenarioPaths) ? scenarioPaths : 'Not set'} paths · ${Number.isFinite(scenarioHorizon) ? scenarioHorizon : 'Not set'}d horizon` : 'Disabled'}</dd></div>
          <div><dt>Currency / random seed</dt><dd>{request.base_currency} / {request.random_seed}</dd></div>
        </dl>
        <div id="run-validation" aria-live="polite" aria-atomic="true">
          {validationErrors.length > 0 ? (
            <>
              <p className="form-hint">Before you run</p>
              <ul className="validation-list">{validationErrors.map((message) => <li key={message}>{message}</li>)}</ul>
            </>
          ) : <p className="form-hint">{loading ? 'Analysis in progress. Your configuration is locked.' : 'Configuration ready to run.'}</p>}
        </div>
        <button type="submit" disabled={!canSubmit} className="submit-btn" aria-describedby="run-validation">
          {loading ? 'Analyzing...' : initialRequest ? 'Rerun Analysis' : 'Run Analysis'}
        </button>
        <p className="form-hint">{initialRequest ? 'Saves a new run. Your original analysis stays unchanged.' : 'Results are saved to your analysis history.'} Historical estimates are not forecasts.</p>
      </aside>
    </form>
  );
}
