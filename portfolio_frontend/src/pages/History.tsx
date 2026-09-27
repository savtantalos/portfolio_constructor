import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listAnalyses, extractError } from '../api/client';
import type { AnalysisSummary } from '../api/types';

export default function History() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    setError('');
    listAnalyses(limit, offset)
      .then(setAnalyses)
      .catch((err) => setError(extractError(err)))
      .finally(() => setLoading(false));
  }, [offset]);

  return (
    <div className="page">
      <h1 className="page-title">Analysis History</h1>
      <p className="page-subtitle">View and revisit your past portfolio analyses.</p>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="loading-spinner">Loading...</div>
      ) : analyses.length === 0 ? (
        <div className="empty-state">
          <p>No analyses yet.</p>
          <Link to="/" className="submit-btn" style={{ display: 'inline-block', textDecoration: 'none' }}>
            Create your first analysis
          </Link>
        </div>
      ) : (
        <>
          <div className="history-list">
            {analyses.map((a) => (
              <Link key={a.id} to={`/analysis/${a.id}`} className="history-card">
                <div className="history-tickers">{a.tickers.join(' / ')}</div>
                <div className="history-meta">
                  <span>{a.start_date} to {a.end_date}</span>
                  <span className="history-date">{new Date(a.created_at).toLocaleString()}</span>
                </div>
              </Link>
            ))}
          </div>
          <div className="pagination">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} className="page-btn">
              Previous
            </button>
            <span className="page-info">Showing {offset + 1}-{offset + analyses.length}</span>
            <button disabled={analyses.length < limit} onClick={() => setOffset(offset + limit)} className="page-btn">
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
