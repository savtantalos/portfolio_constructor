import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createAnalysis, getAnalysis, extractError } from '../api/client';
import type { AnalysisRequest } from '../api/types';
import AnalysisForm from '../components/forms/AnalysisForm';

export default function NewAnalysis() {
  const { id } = useParams<{ id: string }>();
  return <AnalysisEditor key={id ?? 'new'} id={id} />;
}

function AnalysisEditor({ id }: { id?: string }) {
  const navigate = useNavigate();
  const [initialRequest, setInitialRequest] = useState<AnalysisRequest>();
  const [sourceLoading, setSourceLoading] = useState(Boolean(id));
  const [sourceError, setSourceError] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    let active = true;
    getAnalysis(id)
      .then((analysis) => { if (active) setInitialRequest(analysis.request); })
      .catch((err) => { if (active) setSourceError(extractError(err)); })
      .finally(() => { if (active) setSourceLoading(false); });
    return () => { active = false; };
  }, [id]);

  const handleSubmit = async (request: AnalysisRequest) => {
    setLoading(true);
    setError('');
    try {
      const result = await createAnalysis(request);
      navigate(`/analysis/${result.id}`);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      {id && <Link to={`/analysis/${id}`} className="back-link">Back to original analysis</Link>}
      <p className="terminal-eyebrow">Research terminal / {id ? 'Rerun' : 'New run'}</p>
      <h1 className="page-title">{id ? 'Edit & Rerun Analysis' : 'New Portfolio Analysis'}</h1>
      <p className="page-subtitle">
        {id
          ? 'Refine your basket, window, or assumptions. Rerunning saves a new analysis and leaves the original in History.'
          : 'Build an asset basket, set a historical window, and compare allocation strategies in one research run.'}
      </p>
      {sourceLoading ? (
        <div className="loading-spinner" role="status">Loading original settings...</div>
      ) : sourceError ? (
        <div className="alert alert-error" role="alert">{sourceError}</div>
      ) : (
        <>
          {error && <div className="alert alert-error" role="alert">{error}</div>}
          <AnalysisForm onSubmit={handleSubmit} loading={loading} initialRequest={initialRequest} />
        </>
      )}
    </div>
  );
}
