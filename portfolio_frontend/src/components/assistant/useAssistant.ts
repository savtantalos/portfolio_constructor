import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createConversation,
  getAssistantStatus,
  getConversation,
  listConversations,
  streamMessage,
} from '../../api/assistant';
import { extractError } from '../../api/client';
import type { AssistantEvent, AssistantStatus } from '../../api/types';
import { applyEvent, toDisplayMessages, type DisplayMessage } from './assistantEvents';

export interface AssistantState {
  status: AssistantStatus | null;
  statusError: string;
  conversationId: string | null;
  messages: DisplayMessage[];
  loading: boolean;
  streaming: boolean;
  error: string;
  linkedAnalysisId: string | null;
}

/** Scope key for the conversation shown in the drawer: an analysis id, or the general workspace. */
export function conversationScope(analysisId: string | null): string {
  return analysisId ?? 'workspace';
}

export function useAssistant(analysisId: string | null, path: string) {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [statusError, setStatusError] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [linkedAnalysisId, setLinkedAnalysisId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const scopeRef = useRef<string | null>(null);
  // Conversations the drawer has already chosen for each scope in this tab.
  const chosenRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    let active = true;
    getAssistantStatus()
      .then((s) => { if (active) setStatus(s); })
      .catch((err) => { if (active) { setStatus({ enabled: false, model: '' }); setStatusError(extractError(err)); } });
    return () => { active = false; };
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    const detail = await getConversation(id);
    setConversationId(detail.id);
    setLinkedAnalysisId(detail.analysis_id);
    setMessages(toDisplayMessages(detail.messages));
  }, []);

  // Switch conversations when the open analysis changes, unless the current
  // conversation was just linked to that analysis by the agent.
  useEffect(() => {
    if (!status?.enabled) return;
    const scope = conversationScope(analysisId);
    if (scope === scopeRef.current) return;
    scopeRef.current = scope;
    if (analysisId && linkedAnalysisId === analysisId && conversationId) {
      chosenRef.current.set(scope, conversationId);
      return;
    }
    let active = true;
    setLoading(true);
    setError('');
    const chosen = chosenRef.current.get(scope);
    const pick = chosen
      ? Promise.resolve(chosen)
      : listConversations(analysisId, 1).then((items) => items[0]?.id ?? null);
    pick
      .then(async (id) => {
        if (!active) return;
        if (id) {
          await loadConversation(id);
          chosenRef.current.set(scope, id);
        } else {
          setConversationId(null);
          setLinkedAnalysisId(null);
          setMessages([]);
        }
      })
      .catch((err) => { if (active) setError(extractError(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [analysisId, status?.enabled, conversationId, linkedAnalysisId, loadConversation]);

  const newConversation = useCallback(() => {
    abortRef.current?.abort();
    chosenRef.current.delete(conversationScope(analysisId));
    setConversationId(null);
    setLinkedAnalysisId(null);
    setMessages([]);
    setError('');
    setStreaming(false);
  }, [analysisId]);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const send = useCallback(async (content: string) => {
    const text = content.trim();
    if (!text || streaming) return;
    setError('');
    setStreaming(true);
    const liveKey = `live-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { key: `${liveKey}-u`, role: 'user', text, tools: [] },
      { key: liveKey, role: 'assistant', text: '', tools: [], streaming: true },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    const update = (event: AssistantEvent) => {
      if (event.type === 'conversation_linked') setLinkedAnalysisId(event.analysis_id);
      setMessages((prev) => prev.map((m) => (m.key === liveKey ? applyEvent(m, event) : m)));
    };
    try {
      let id = conversationId;
      if (!id) {
        const created = await createConversation(analysisId);
        id = created.id;
        setConversationId(id);
        setLinkedAnalysisId(created.analysis_id);
        chosenRef.current.set(conversationScope(analysisId), id);
      }
      await streamMessage(id, { content: text, context: { analysis_id: analysisId, path } }, update, controller.signal);
      setMessages((prev) => prev.map((m) => (m.key === liveKey ? { ...m, streaming: false } : m)));
    } catch (err) {
      const aborted = controller.signal.aborted;
      const message = aborted ? 'Stopped.' : err instanceof Error ? err.message : extractError(err);
      setMessages((prev) => prev.map((m) => (m.key === liveKey ? { ...m, streaming: false, error: aborted ? undefined : message } : m)));
      if (!aborted) setError(message);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setStreaming(false);
    }
  }, [analysisId, conversationId, path, streaming]);

  return {
    state: { status, statusError, conversationId, messages, loading, streaming, error, linkedAnalysisId } satisfies AssistantState,
    send,
    stop,
    newConversation,
  };
}
