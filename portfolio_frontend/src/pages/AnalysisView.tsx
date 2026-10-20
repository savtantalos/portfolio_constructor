import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getAnalysis, getAnalysisPrices, extractError } from '../api/client';
import type { AnalysisResponse, PriceSnapshot } from '../api/types';
import type { ColorTheme } from '../hooks/useColorTheme';
import ThemePicker from '../components/layout/ThemePicker';
import MetricsCards from '../components/layout/MetricsCards';
import BacktestComparison from '../components/layout/BacktestComparison';
import WeightsChart from '../components/charts/WeightsChart';
import FrontierChart from '../components/charts/FrontierChart';
import CorrelationHeatmap from '../components/charts/CorrelationHeatmap';
import EquityCurveChart from '../components/charts/EquityCurveChart';
import DrawdownChart from '../components/charts/DrawdownChart';
import RiskContributionChart from '../components/charts/RiskContributionChart';
import PriceChart from '../components/charts/PriceChart';
import ScenarioChart from '../components/charts/ScenarioChart';
import ScenarioTable from '../components/layout/ScenarioTable';
import AnalysisData from '../components/AnalysisData';

interface Props {
  theme: ColorTheme;
  themeName: string;
  themeNames: string[];
  setTheme: (name: string) => void;
}

export default function AnalysisView({ theme, themeName, themeNames, setTheme }: Props) {
  const { id } = useParams<{ id: string }>();
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [prices, setPrices] = useState<PriceSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'overview' | 'frontier' | 'backtest' | 'scenarios' | 'prices' | 'data' | 'warnings'>('overview');

  useEffect(() => {
    if (!id) return;
    let active = true;
    setLoading(true);
    setError('');
    setActiveTab('overview');
    Promise.all([getAnalysis(id), getAnalysisPrices(id)])
      .then(([a, p]) => { if (active) { setAnalysis(a); setPrices(p); } })
      .catch((err) => { if (active) setError(extractError(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  if (loading) return (
    <div className="page" aria-busy="true" role="status" aria-label="Loading analysis">
      <div className="skeleton skeleton-heading" />
      <div className="research-snapshot skeleton-grid" aria-hidden="true">{[0, 1, 2].map((i) => <div className="skeleton" key={i} />)}</div>
      <div className="skeleton skeleton-chart" />
      <span className="sr-only">Loading analysis...</span>
    </div>
  );
  if (error) return <div className="page"><div className="alert alert-error">{error}</div><Link to="/" className="back-link">Back</Link></div>;
  if (!analysis) return <div className="page"><div className="alert alert-error">Analysis not found</div></div>;

  const { results, data } = analysis;
  const hasBacktests = results.backtests.length > 0 || Boolean(results.benchmark);
  const tabs = [
    { key: 'overview' as const, label: 'Overview' },
    { key: 'frontier' as const, label: 'Frontier & Monte Carlo' },
    ...(hasBacktests ? [{ key: 'backtest' as const, label: 'Backtesting' }] : []),
    ...(results.scenarios && results.scenarios.length > 0 ? [{ key: 'scenarios' as const, label: 'Scenarios' }] : []),
    ...(prices ? [{ key: 'prices' as const, label: 'Returns & Volatility' }] : []),
    { key: 'data' as const, label: 'Data & Downloads' },
    { key: 'warnings' as const, label: results.warnings.length ? `Notes & warnings (${results.warnings.length})` : 'Methodology & notes' },
  ];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <Link to="/history" className="back-link">&#8592; History</Link>
          <h1 className="page-title">{analysis.request.tickers.join(' / ')}</h1>
          <p className="page-subtitle">
            {data.effective_start} to {data.effective_end} &middot; {data.price_observations} observations &middot; v{analysis.engine_version}
          </p>
        </div>
        <div className="page-actions">
          <Link to={`/analysis/${analysis.id}/edit`} className="submit-btn action-link">Edit &amp; rerun</Link>
          <ThemePicker current={themeName} themes={themeNames} onChange={setTheme} theme={theme} />
        </div>
      </div>

      <div className="terminal-status" aria-label="Analysis metadata">
        <span><b>{data.currency}</b> base currency</span>
        <span><b>{data.price_observations.toLocaleString()}</b> price observations</span>
        <span><b>{results.portfolios.length}</b> computed strategies</span>
        <span>Source <b>{data.provider}</b></span>
        <span>Engine <b>v{analysis.engine_version}</b></span>
      </div>
      {results.warnings.length > 0 && (
        <div className="research-warning">
          <span>{results.warnings.length} research {results.warnings.length === 1 ? 'warning' : 'warnings'} · {results.warnings[0]}</span>
          <button type="button" className="page-btn" onClick={() => setActiveTab('warnings')}>Review notes</button>
        </div>
      )}
      <div className="tab-bar" aria-label="Analysis sections">
        {tabs.map((t) => (
          <button key={t.key} aria-pressed={activeTab === t.key} className={`tab-btn ${activeTab === t.key ? 'active' : ''}`} onClick={() => setActiveTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="tab-content">
          <MetricsCards portfolios={results.portfolios} backtests={results.backtests} theme={theme} />
          <div className="charts-grid">
            <WeightsChart portfolios={results.portfolios} theme={theme} />
            <RiskContributionChart portfolios={results.portfolios} theme={theme} />
            <CorrelationHeatmap correlation={results.correlation} theme={theme} />
          </div>
        </div>
      )}

      {activeTab === 'frontier' && (
        <div className="tab-content">
          <FrontierChart
            frontier={results.efficient_frontier}
            monteCarlo={results.monte_carlo}
            portfolios={results.portfolios}
            theme={theme}
          />
        </div>
      )}

      {activeTab === 'backtest' && hasBacktests && (
        <div className="tab-content">
          <BacktestComparison backtests={results.backtests} benchmark={results.benchmark} theme={theme} />
          <EquityCurveChart backtests={results.backtests} benchmark={results.benchmark} theme={theme} />
          <DrawdownChart backtests={results.backtests} benchmark={results.benchmark} theme={theme} />
          <div className="backtest-summary">
            <h3>Backtest Configuration</h3>
            <div className="config-grid">
              <span>Lookback: {analysis.request.backtest.lookback_days} return observations</span>
              <span>Rebalance: every {analysis.request.backtest.rebalance_every} return observations (except buy &amp; hold)</span>
              <span>Transaction cost: {analysis.request.backtest.transaction_cost_bps} bps</span>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'prices' && prices && (
        <div className="tab-content">
          <PriceChart snapshot={prices} theme={theme} currency={data.currency} />
          <div className="data-summary">
            <h3>Data Summary</h3>
            <div className="config-grid">
              <span>Provider: {data.provider}</span>
              <span>Adjustment: {data.adjustment}</span>
              <span>Currency: {data.currency}</span>
              <span>SHA-256: <code>{data.snapshot_sha256.slice(0, 16)}...</code></span>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'scenarios' && results.scenarios && results.scenarios.length > 0 && (
        <div className="tab-content">
          <p className="research-note">Block-bootstrap scenarios resample consecutive historical return blocks with replacement. Fan bands show cross-path wealth percentiles for each fitted allocation over the projected horizon — conditional scenarios, not forecasts.</p>
          <ScenarioChart scenarios={results.scenarios} theme={theme} />
          <ScenarioTable scenarios={results.scenarios} theme={theme} />
          <div className="backtest-summary">
            <h3>Scenario Configuration</h3>
            <div className="config-grid">
              <span>Horizon: {analysis.request.scenario?.horizon_days ?? '—'} calendar days</span>
              <span>Block: {analysis.request.scenario?.block_days ?? '—'} observations</span>
              <span>Paths: {analysis.request.scenario?.paths ?? '—'}</span>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'data' && <AnalysisData key={analysis.id} analysis={analysis} />}

      {activeTab === 'warnings' && (
        <div className="tab-content">
          <h2 className="section-title">Research notes</h2>
          <p className="research-note">Optimization metrics describe the full analysis sample. Walk-forward backtests fit weights using prior observations at each rebalance. Historical results do not guarantee future performance.</p>
          {results.warnings.length === 0 && <p className="research-note">No engine warnings were reported. This does not imply the analysis is free of limitations.</p>}
          <div className="warnings-list">
            {results.warnings.map((w, i) => (
              <div key={i} className="warning-item">{w}</div>
            ))}
          </div>
          {analysis.assumptions.length > 0 && (
            <>
              <h3 className="section-title">Assumptions & Disclaimers</h3>
              <div className="warnings-list">
                {analysis.assumptions.map((a, i) => (
                  <div key={i} className="assumption-item">{a}</div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
