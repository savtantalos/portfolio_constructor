import axios from 'axios';
import type {
  AssistantEvent,
  AssistantStatus,
  ChatSendRequest,
  ConversationDetail,
  ConversationSummary,
} from './types';
import { parseSseChunk } from '../components/assistant/assistantEvents';

const baseURL = import.meta.env.VITE_API_URL || '';
const api = axios.create({ baseURL, headers: { 'Content-Type': 'application/json' } });

api.interceptors.request.use((config) => {
  const key = import.meta.env.VITE_API_KEY;
  if (key) config.headers['X-API-Key'] = key;
  return config;
});

export async function getAssistantStatus(): Promise<AssistantStatus> {
  const { data } = await api.get<AssistantStatus>('/api/v1/assistant/status');
  return data;
}

export async function createConversation(analysisId?: string | null): Promise<ConversationDetail> {
  const { data } = await api.post<ConversationDetail>('/api/v1/conversations', {
    analysis_id: analysisId ?? null,
  });
  return data;
}

export async function listConversations(analysisId?: string | null, limit = 10): Promise<ConversationSummary[]> {
  const { data } = await api.get<ConversationSummary[]>('/api/v1/conversations', {
    params: { analysis_id: analysisId ?? undefined, limit },
  });
  return data;
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const { data } = await api.get<ConversationDetail>(`/api/v1/conversations/${id}`);
  return data;
}

/**
 * Send a message and stream assistant events. Uses fetch because axios cannot
 * read a response body incrementally in browsers.
 */
export async function streamMessage(
  conversationId: string,
  request: ChatSendRequest,
  onEvent: (event: AssistantEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
  const key = import.meta.env.VITE_API_KEY;
  if (key) headers['X-API-Key'] = key;
  const response = await fetch(`${baseURL}/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    let message = `Server error (${response.status})`;
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      // keep the generic message
    }
    throw new Error(message);
  }
  if (!response.body) throw new Error('Streaming is not supported by this browser.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSseChunk(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
  const tail = parseSseChunk(buffer + '\n\n');
  tail.events.forEach(onEvent);
}
