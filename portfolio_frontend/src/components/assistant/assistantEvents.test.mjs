import assert from 'node:assert/strict';
import test from 'node:test';
import { applyEvent, describeTool, parseSseChunk, toDisplayMessages } from './assistantEvents.ts';

test('SSE parser yields complete frames and keeps the partial remainder', () => {
  const first = parseSseChunk('data: {"type":"start","conversation_id":"c","user_message_id":1}\n\ndata: {"type":"text_de');
  assert.deepEqual(first.events, [{ type: 'start', conversation_id: 'c', user_message_id: 1 }]);
  assert.equal(first.rest, 'data: {"type":"text_de');
  const second = parseSseChunk(first.rest + 'lta","text":"Hi"}\n\n: comment\ndata: not json\n\n');
  assert.deepEqual(second.events, [{ type: 'text_delta', text: 'Hi' }]);
  assert.equal(second.rest, '');
});

test('stored messages collapse tool rounds into one assistant message with results', () => {
  const messages = [
    { id: 1, role: 'user', content: [{ type: 'text', text: 'Run it' }], created_at: 'x' },
    { id: 2, role: 'assistant', content: [
      { type: 'text', text: 'Searching.' },
      { type: 'tool_use', id: 't1', name: 'search_assets', input: { query: 'apple' } },
    ], created_at: 'x' },
    { id: 3, role: 'user', content: [{ type: 'tool_result', tool_use_id: 't1', content: '[]' }], created_at: 'x' },
    { id: 4, role: 'assistant', content: [
      { type: 'tool_use', id: 't2', name: 'run_analysis', input: { request: { tickers: ['AAA', 'BBB'] } } },
    ], created_at: 'x' },
    { id: 5, role: 'user', content: [{ type: 'tool_result', tool_use_id: 't2', content: '{"analysis_id":"abc","link":"/analysis/abc","request":{"tickers":["AAA","BBB"]}}' }], created_at: 'x' },
    { id: 6, role: 'assistant', content: [{ type: 'text', text: 'Done.' }], created_at: 'x' },
    { id: 7, role: 'user', content: [{ type: 'text', text: 'Thanks' }], created_at: 'x' },
    { id: 8, role: 'assistant', content: [{ type: 'tool_use', id: 't3', name: 'list_analyses', input: {} }], created_at: 'x' },
  ];
  const display = toDisplayMessages(messages);
  assert.deepEqual(display.map((m) => [m.role, m.text]), [
    ['user', 'Run it'], ['assistant', 'Searching.\n\nDone.'], ['user', 'Thanks'], ['assistant', ''],
  ]);
  assert.deepEqual(display[1].tools.map((t) => [t.name, t.status]), [['search_assets', 'ok'], ['run_analysis', 'ok']]);
  assert.deepEqual(display[1].tools[1].summary, { analysis_id: 'abc', link: '/analysis/abc', tickers: ['AAA', 'BBB'] });
  assert.equal(display[3].tools[0].status, 'error', 'dangling tool call is shown as failed');
  assert.equal(describeTool(display[1].tools[0]), 'Searched assets: "apple"');
  assert.equal(describeTool(display[1].tools[1]), 'Ran analysis: AAA, BBB');
});

test('streamed events build up the live assistant message', () => {
  let current = { key: 'live', role: 'assistant', text: '', tools: [], streaming: true };
  current = applyEvent(current, { type: 'text_delta', text: 'Look' });
  current = applyEvent(current, { type: 'text_delta', text: 'ing.' });
  current = applyEvent(current, { type: 'tool_call', id: 't', name: 'list_analyses', input: {} });
  assert.equal(describeTool(current.tools[0]), 'Listed saved analyses...');
  current = applyEvent(current, { type: 'tool_result', id: 't', name: 'list_analyses', ok: true, summary: { count: 2 } });
  assert.equal(current.text, 'Looking.');
  assert.deepEqual(current.tools[0], { id: 't', name: 'list_analyses', input: {}, status: 'ok', summary: { count: 2 } });
  current = applyEvent(current, { type: 'conversation_linked', analysis_id: 'abc' });
  assert.equal(current.streaming, true);
  const ended = applyEvent(current, { type: 'message_end', message_ids: [1, 2] });
  assert.equal(ended.streaming, false);
  const failed = applyEvent(
    applyEvent(current, { type: 'tool_call', id: 'u', name: 'run_analysis', input: {} }),
    { type: 'error', code: 'assistant_error', message: 'Try again' },
  );
  assert.equal(failed.error, 'Try again');
  assert.equal(failed.tools[1].status, 'error');
});
