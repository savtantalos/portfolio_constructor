import type { AssistantEvent, ChatMessage, ContentBlock, ToolResultSummary } from '../../api/types';

export interface ToolActivity {
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: 'running' | 'ok' | 'error';
  summary?: ToolResultSummary;
}

export interface DisplayMessage {
  key: string;
  role: 'user' | 'assistant';
  text: string;
  tools: ToolActivity[];
  streaming?: boolean;
  error?: string;
}

/** Parse complete `data:` lines from an SSE buffer; returns events and the unconsumed remainder. */
export function parseSseChunk(buffer: string): { events: AssistantEvent[]; rest: string } {
  const events: AssistantEvent[] = [];
  let rest = buffer;
  let index: number;
  while ((index = rest.indexOf('\n\n')) !== -1) {
    const frame = rest.slice(0, index);
    rest = rest.slice(index + 2);
    for (const line of frame.split('\n')) {
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        events.push(JSON.parse(payload) as AssistantEvent);
      } catch {
        // Ignore malformed frames; the stream ends with message_end or error.
      }
    }
  }
  return { events, rest };
}

/** Collapse stored content blocks into renderable messages, pairing tool calls with their results. */
export function toDisplayMessages(messages: ChatMessage[]): DisplayMessage[] {
  const display: DisplayMessage[] = [];
  const pending = new Map<string, ToolActivity>();
  for (const message of messages) {
    const blocks: ContentBlock[] = message.content;
    const toolResults = blocks.filter((b): b is Extract<ContentBlock, { type: 'tool_result' }> => b.type === 'tool_result');
    if (message.role === 'user' && toolResults.length > 0) {
      for (const result of toolResults) {
        const activity = pending.get(result.tool_use_id);
        if (!activity) continue;
        activity.status = result.is_error ? 'error' : 'ok';
        activity.summary = summarizeStoredResult(activity.name, result.content, Boolean(result.is_error));
        pending.delete(result.tool_use_id);
      }
      continue;
    }
    const text = blocks.filter((b): b is Extract<ContentBlock, { type: 'text' }> => b.type === 'text').map((b) => b.text).join('');
    const tools: ToolActivity[] = blocks
      .filter((b): b is Extract<ContentBlock, { type: 'tool_use' }> => b.type === 'tool_use')
      .map((b) => ({ id: b.id, name: b.name, input: b.input ?? {}, status: 'running' as const }));
    for (const tool of tools) pending.set(tool.id, tool);
    const last = display[display.length - 1];
    if (message.role === 'assistant' && last?.role === 'assistant' && !last.streaming) {
      last.text = [last.text, text].filter(Boolean).join('\n\n');
      last.tools.push(...tools);
    } else {
      display.push({ key: `m${message.id}`, role: message.role, text, tools });
    }
  }
  for (const activity of pending.values()) activity.status = 'error';
  return display;
}

function summarizeStoredResult(name: string, content: string, isError: boolean): ToolResultSummary {
  if (isError) return { message: content.slice(0, 200) };
  if (name === 'run_analysis' || name === 'get_analysis') {
    try {
      const parsed = JSON.parse(content) as { analysis_id?: string; link?: string; request?: { tickers?: string[] } };
      return { analysis_id: parsed.analysis_id, link: parsed.link, tickers: parsed.request?.tickers };
    } catch {
      return {};
    }
  }
  return {};
}

/** Apply one streamed event to the in-progress assistant message. */
export function applyEvent(current: DisplayMessage, event: AssistantEvent): DisplayMessage {
  switch (event.type) {
    case 'text_delta':
      return { ...current, text: current.text + event.text };
    case 'tool_call':
      return { ...current, tools: [...current.tools, { id: event.id, name: event.name, input: event.input, status: 'running' }] };
    case 'tool_result':
      return {
        ...current,
        tools: current.tools.map((t) => (t.id === event.id ? { ...t, status: event.ok ? 'ok' : 'error', summary: event.summary } : t)),
      };
    case 'message_end':
      return { ...current, streaming: false };
    case 'error':
      return { ...current, streaming: false, error: event.message, tools: current.tools.map((t) => (t.status === 'running' ? { ...t, status: 'error' } : t)) };
    default:
      return current;
  }
}

const TOOL_LABELS: Record<string, string> = {
  get_analysis: 'Read analysis',
  get_analysis_dataset: 'Read dataset',
  list_analyses: 'Listed saved analyses',
  search_assets: 'Searched assets',
  run_analysis: 'Ran analysis',
};

export function describeTool(tool: ToolActivity): string {
  const base = TOOL_LABELS[tool.name] ?? tool.name;
  const input = tool.input ?? {};
  if (tool.name === 'search_assets' && typeof input.query === 'string') return `${base}: "${input.query}"`;
  if (tool.name === 'get_analysis_dataset' && typeof input.dataset_id === 'string') return `${base}: ${input.dataset_id}`;
  if (tool.name === 'run_analysis') {
    const request = input.request as { tickers?: unknown } | undefined;
    if (Array.isArray(request?.tickers)) return `${base}: ${(request!.tickers as string[]).join(', ')}`;
  }
  if (tool.status === 'running') return `${base}...`;
  return base;
}
