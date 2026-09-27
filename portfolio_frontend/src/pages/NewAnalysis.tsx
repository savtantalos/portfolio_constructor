import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createAnalysis, extractError } from '../api/client';
import type { AnalysisRequest } from '../api/types';
import AnalysisForm from '../components/forms/AnalysisForm';

export default function NewAnalysis() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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
      <h1 className="page-title">New Portfolio Analysis</h1>
      <p className="page-subtitle">
        Search for stocks/ETFs, configure your analysis, and explore the results interactively.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <AnalysisForm onSubmit={handleSubmit} loading={loading} />
    </div>
  );
}
