import axios from 'axios';
import type {
  AnalysisRequest,
  AnalysisResponse,
  AnalysisSummary,
  ErrorResponse,
  HealthResponse,
  Instrument,
  PriceSnapshot,
} from './types';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
  headers: { 'Content-Type': 'application/json' },
});

// Attach API key if configured
api.interceptors.request.use((config) => {
  const key = import.meta.env.VITE_API_KEY;
  if (key) config.headers['X-API-Key'] = key;
  return config;
});

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health');
  return data;
}

export async function searchAssets(q: string, limit = 10): Promise<Instrument[]> {
  const { data } = await api.get<Instrument[]>('/api/v1/assets/search', {
    params: { q, limit },
  });
  return data;
}

export async function createAnalysis(
  request: AnalysisRequest
): Promise<AnalysisResponse> {
  const { data } = await api.post<AnalysisResponse>('/api/v1/analyses', request);
  return data;
}

export async function listAnalyses(
  limit = 20,
  offset = 0
): Promise<AnalysisSummary[]> {
  const { data } = await api.get<AnalysisSummary[]>('/api/v1/analyses', {
    params: { limit, offset },
  });
  return data;
}

export async function getAnalysis(id: string): Promise<AnalysisResponse> {
  const { data } = await api.get<AnalysisResponse>(`/api/v1/analyses/${id}`);
  return data;
}

export async function getAnalysisPrices(id: string): Promise<PriceSnapshot> {
  const { data } = await api.get<PriceSnapshot>(
    `/api/v1/analyses/${id}/prices`
  );
  return data;
}

export function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as ErrorResponse | undefined;
    if (body?.error?.message) return body.error.message;
    if (err.response?.status) return `Server error (${err.response.status})`;
    return 'Network error - is the backend running?';
  }
  return String(err);
}
