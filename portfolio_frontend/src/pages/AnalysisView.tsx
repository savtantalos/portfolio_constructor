import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getAnalysis, getAnalysisPrices, extractError } from '../api/client';
import type { AnalysisResponse, PriceSnapshot } from '../api/types';
import type { ColorTheme } from '../hooks/useColorTheme';
import ThemePicker from '../components/layout/ThemePicker';
import MetricsCards from '../components/layout/MetricsCards';
import WeightsChart from '../components/charts/WeightsChart';
import FrontierChart from '../components/charts/FrontierChart';
import CorrelationHeatmap from '../components/charts/CorrelationHeatmap';
import EquityCurveChart from '../components/charts/EquityCurveChart';
import DrawdownChart from '../components/charts/DrawdownChart';
import RiskContributionChart from '../components/charts/RiskContributionChart';
import PriceChart from '../components/charts/PriceChart';
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
  const [activeTab, setActiveTab] = useState<'overview' | 'frontier' | 'backtest' | 'prices' | 'data' | 'warnings'>('overview');

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError('');
    Promise.all([getAnalysis(id), getAnalysisPrices(id)])
      .then(([a, p]) => { setAnalysis(a); setPrices(p); })
      .catch((err) => setError(extractError(err)))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page"><div className="loading-spinner">Loading analysis...</div></div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div><Link to="/" className="back-link">Back</Link></div>;
  if (!analysis) return <div className="page"><div className="alert alert-error">Analysis not found</div></div>;

  const { results, data } = analysis;
  const tabs = [
    { key: 'overview' as const, label: 'Overview' },
    { key: 'frontier' as const, label: 'Frontier & Monte Carlo' },
    ...(results.backtests.length > 0 ? [{ key: 'backtest' as const, label: 'Backtesting' }] : []),
    ...(prices ? [{ key: 'prices' as const, label: 'Returns & Volatility' }] : []),
    { key: 'data' as const, label: 'Data & Downloads' },
    ...(results.warnings.length > 0 ? [{ key: 'warnings' as const, label: `Warnings (${results.warnings.length})` }] : []),
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

      <div className="tab-bar">
        {tabs.map((t) => (
          <button key={t.key} className={`tab-btn ${activeTab === t.key ? 'active' : ''}`} onClick={() => setActiveTab(t.key)}>
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

      {activeTab === 'backtest' && results.backtests.length > 0 && (
        <div className="tab-content">
          <EquityCurveChart backtests={results.backtests} theme={theme} />
          <DrawdownChart backtests={results.backtests} theme={theme} />
          <div className="backtest-summary">
            <h3>Backtest Configuration</h3>
            <div className="config-grid">
              <span>Lookback: {analysis.request.backtest.lookback_days} days</span>
              <span>Rebalance: every {analysis.request.backtest.rebalance_every} days</span>
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

      {activeTab === 'data' && <AnalysisData key={analysis.id} analysis={analysis} />}

      {activeTab === 'warnings' && results.warnings.length > 0 && (
        <div className="tab-content">
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
