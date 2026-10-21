import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, matchPath, useLocation } from 'react-router-dom';
import { describeTool, type DisplayMessage, type ToolActivity } from './assistantEvents';
import { useAssistant } from './useAssistant';
import MessageContent from './MessageContent';

const STARTERS_WITH_ANALYSIS = [
  'Explain the backtest results in plain language.',
  'Why do the strategies allocate so differently?',
  'What do the warnings mean for how I should read this?',
  'Which single input would be most informative to change next?',
];

const STARTERS_WITHOUT_ANALYSIS = [
  'What is the difference between in-sample metrics and the backtest?',
  'Help me set up an analysis comparing a few broad ETFs.',
  'How does minimum variance differ from inverse volatility?',
  'What does the block-bootstrap scenario chart show?',
];

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function AssistantDrawer({ open, onClose }: Props) {
  const location = useLocation();
  const match = matchPath('/analysis/:id', location.pathname) ?? matchPath('/analysis/:id/edit', location.pathname);
  const analysisId = match?.params.id ?? null;
  const { state, send, stop, newConversation } = useAssistant(analysisId, location.pathname);
  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [state.messages, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!draft.trim() || state.streaming) return;
    void send(draft);
    setDraft('');
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const enabled = state.status?.enabled ?? false;
  const starters = analysisId ? STARTERS_WITH_ANALYSIS : STARTERS_WITHOUT_ANALYSIS;

  return (
    <aside className="assistant-drawer" aria-label="Research assistant" role="complementary">
      <div className="assistant-header">
        <div>
          <p className="terminal-eyebrow">Research assistant</p>
          <h2>{analysisId ? 'Discussing this analysis' : 'Workspace chat'}</h2>
        </div>
        <div className="assistant-header-actions">
          <button type="button" className="page-btn" onClick={newConversation} disabled={!enabled || state.streaming || state.messages.length === 0}>New chat</button>
          <button type="button" className="page-btn" onClick={onClose} aria-label="Close assistant">&times;</button>
        </div>
      </div>

      {state.status === null && <div className="assistant-empty">Checking assistant availability...</div>}
      {state.status !== null && !enabled && (
        <div className="assistant-empty">
          <p>The assistant is not configured on this server.</p>
          <p className="research-note">Set <code>PORTFOLIO_ANTHROPIC_API_KEY</code> in the backend environment to enable it. When enabled, analysis summaries and chat messages are sent to the model provider.</p>
          {state.statusError && <div className="alert alert-error">{state.statusError}</div>}
        </div>
      )}

      {enabled && (
        <>
          <div className="assistant-messages" ref={listRef}>
            {state.loading && <div className="assistant-empty">Loading conversation...</div>}
            {!state.loading && state.messages.length === 0 && (
              <div className="assistant-empty">
                <p>Ask about the methodology, what a result means, or how to configure a run. The assistant reads saved analyses and can run new ones for you.</p>
                <div className="assistant-starters">
                  {starters.map((s) => (
                    <button key={s} type="button" className="assistant-starter" onClick={() => void send(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {state.messages.map((message) => <MessageBubble key={message.key} message={message} />)}
          </div>
          {state.error && <div className="alert alert-error assistant-alert" role="alert">{state.error}</div>}
          <form className="assistant-composer" onSubmit={submit}>
            <textarea
              ref={inputRef}
              className="form-input assistant-input"
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={analysisId ? 'Ask about this analysis...' : 'Ask about strategies, backtests, or set up a run...'}
              aria-label="Message the assistant"
              disabled={state.streaming}
            />
            {state.streaming ? (
              <button type="button" className="page-btn" onClick={stop}>Stop</button>
            ) : (
              <button type="submit" className="submit-btn assistant-send" disabled={!draft.trim()}>Send</button>
            )}
          </form>
          <p className="assistant-footer">Educational research assistant. Not investment advice; verify numbers against the saved analysis.</p>
        </>
      )}
    </aside>
  );
}

function MessageBubble({ message }: { message: DisplayMessage }) {
  return (
    <div className={`assistant-message assistant-message-${message.role}`}>
      {message.tools.length > 0 && (
        <ul className="assistant-tools" aria-label="Assistant actions">
          {message.tools.map((tool) => <ToolCard key={tool.id} tool={tool} />)}
        </ul>
      )}
      {message.role === 'assistant' ? (
        <div className="assistant-text">
          {message.text ? <MessageContent text={message.text} /> : null}
          {message.streaming && <span className="assistant-cursor" aria-hidden="true" />}
          {!message.text && !message.streaming && message.tools.length === 0 && !message.error && (
            <p className="research-note">(empty reply)</p>
          )}
        </div>
      ) : (
        <div className="assistant-text">{message.text.split('\n').map((line, i) => <p key={i}>{line}</p>)}</div>
      )}
      {message.error && <div className="alert alert-error assistant-alert">{message.error}</div>}
    </div>
  );
}

function ToolCard({ tool }: { tool: ToolActivity }) {
  const link = tool.summary?.link ?? (tool.summary?.analysis_id ? `/analysis/${tool.summary.analysis_id}` : null);
  return (
    <li className={`assistant-tool assistant-tool-${tool.status}`}>
      <span className="assistant-tool-icon" aria-hidden="true">
        {tool.status === 'running' ? '…' : tool.status === 'ok' ? '✓' : '!'}
      </span>
      <span className="assistant-tool-label">{describeTool(tool)}</span>
      {tool.status === 'error' && tool.summary?.message && <span className="assistant-tool-detail">{tool.summary.message}</span>}
      {tool.status === 'ok' && tool.name === 'run_analysis' && link && (
        <Link to={link} className="assistant-link">Open analysis</Link>
      )}
    </li>
  );
}
