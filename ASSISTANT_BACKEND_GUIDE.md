# How the Research Assistant Works: A Backend Walkthrough

A learning guide to the Claude-powered, tool-using agent added to Portfolio Lab's
FastAPI backend. It explains *what* was built, *why* each piece exists, and the
general patterns you can reuse when building any LLM agent on top of an existing
application.

Paths are relative to the repository root.

---

## 0. The one-paragraph version

The browser sends a chat message to `POST /api/v1/conversations/{id}/messages`.
The backend loads the stored conversation, builds a **system prompt** (fixed
instructions + a methodology brief + a summary of the analysis the user is
looking at), and calls Claude with a list of **tools** it may use. Claude streams
text back, which we forward to the browser as **server-sent events**. If Claude
instead asks to call a tool (for example `run_analysis`), the backend executes
it against the *same* code the HTTP API uses, appends the result to the
transcript, and calls Claude again. This loop repeats until Claude answers with
plain text or hits a round limit. Every message, including tool calls and tool
results, is persisted so the next turn can replay the exact transcript.

```
Browser ──POST message──▶ FastAPI route ──▶ Assistant.start_turn()
                                                 │
                                        ┌────────▼────────┐
                                        │ build system    │  SYSTEM_PROMPT + knowledge
                                        │ prompt + history│  + "user is viewing analysis X"
                                        └────────┬────────┘
                                                 │
                              ┌──────────────────▼──────────────────┐
                              │  loop (max assistant_max_tool_rounds)│
                              │   Claude.stream(...)  ── text ──▶ SSE│
                              │   stop_reason == tool_use?           │
                              │     yes → ToolExecutor.execute(...)  │
                              │           append tool_result, repeat │
                              │     no  → persist, emit message_end  │
                              └──────────────────────────────────────┘
```

---

## 1. Vocabulary

| Term | Meaning in this project |
| --- | --- |
| **LLM / model** | Claude, called through the Anthropic Messages API. It only sees text we send it; it has no access to the database or network by itself. |
| **System prompt** | Instructions the model reads before the conversation. Ours sets the role ("educational research assistant"), hard rules (no personalized advice, never invent numbers), and includes the methodology brief and current analysis summary. |
| **Tool / function calling** | We describe functions (name, description, JSON schema of inputs) to the model. Instead of answering, the model can emit a `tool_use` block asking us to run one. **We** run the code and send back a `tool_result`. The model never executes anything itself. |
| **Agent / agentic loop** | A model that can call tools *repeatedly*, reading each result before deciding the next step, until it produces a final answer. |
| **Content block** | The Messages API represents each message as a list of typed blocks: `{"type":"text"}`, `{"type":"tool_use"}`, `{"type":"tool_result"}`. We store these verbatim. |
| **Grounding** | Making the model's statements traceable to real data (tool outputs, provided context) rather than memory. The main defence against hallucinated numbers. |
| **SSE (server-sent events)** | A simple HTTP streaming format (`data: {...}\n\n` frames) that lets the browser render tokens as they arrive. |
| **Prompt caching** | Marking a large, stable prefix of the prompt (`cache_control: ephemeral`) so the provider reuses it across calls, cutting cost and latency. |

---

## 2. The files, in the order a request flows through them

```
portfolio_backend/
├── config.py              ← new settings: API key, model, budgets
├── models.py              ← new pydantic models: conversations, messages, status
├── database.py            ← new tables + ConversationRepository
├── service.py             ← NEW: perform_analysis() extracted from main.py
├── assistant_context.py   ← NEW: SYSTEM_PROMPT, summarize_analysis(), load_knowledge()
├── knowledge/methodology.md ← NEW: condensed methodology brief (package data)
├── assistant.py           ← NEW: LLMClient protocol, AnthropicLLM, tools, Assistant loop
└── main.py                ← new routes under /api/v1; Assistant wiring
tests/test_assistant.py    ← NEW: FakeLLM-driven tests, no network
```

---

## 3. Step 1 — Make the engine callable from two places (`service.py`)

**Problem.** The analysis pipeline (fetch prices → check backtest budget → run
`analyze()` → build snapshot and `DataSummary` → save) lived inline inside the
`POST /analyses` route handler in `main.py`. The agent needs to run the exact
same pipeline, but you cannot "call a route" from inside another request.

**Solution.** Move the body into a plain function:

```python
def perform_analysis(payload, *, market_data, repository, settings) -> AnalysisResponse
```

`main.py` now has a tiny closure that wraps it with the existing concurrency
guard:

```python
def run_analysis(payload):
    if not slots.acquire(blocking=False):
        raise PortfolioError("analysis_capacity_reached", ..., 503)
    try:
        return perform_analysis(payload, market_data=..., repository=..., settings=...)
    finally:
        slots.release()
```

The HTTP route calls `run_analysis(payload)` and sets the `Location` header. The
assistant's `run_analysis` tool receives the *same closure*. This is the single
most important design decision: **the agent gets no special powers**. It is
subject to the same validation (`AnalysisRequest`), the same rebalance budget,
the same worker-slot limit, and writes through the same repository. If you later
tighten a rule in `perform_analysis`, the agent inherits it automatically.

> Pattern: *extract a service function, then expose it twice* (HTTP route and
> agent tool). Never give an agent a side door.

---

## 4. Step 2 — Configuration (`config.py`)

New `PORTFOLIO_*` settings, all with bounds enforced by pydantic:

| Setting | Default | Purpose |
| --- | --- | --- |
| `anthropic_api_key` | `None` | **Server-side only.** When unset or blank, the assistant is disabled and the UI shows an explanation. The key never reaches the browser. |
| `assistant_model` | `claude-sonnet-5` | Changeable without code. |
| `assistant_max_output_tokens` | 1500 | Caps reply length and cost per model call. |
| `assistant_max_tool_rounds` | 6 | Caps how many model↔tool iterations one user message can trigger. Prevents runaway loops. |
| `assistant_max_analyses_per_turn` | 2 | Caps `run_analysis` calls per user message (each hits the data provider and writes to the DB). |
| `assistant_max_concurrent_turns` | 2 | A `BoundedSemaphore`, same pattern as `max_concurrent_analyses`. Excess requests get 503 `assistant_busy`. |
| `assistant_history_messages` | 30 | How many stored messages to replay to the model (token control). |
| `assistant_timeout_seconds` | 120 | HTTP timeout for the provider SDK. |

**Why so many knobs?** An agent that can take actions is a cost and abuse
surface. Every loop needs an upper bound, and every bound should be a setting
so operators can tune it without a deploy.

---

## 5. Step 3 — Persistence (`database.py`, `models.py`)

Two new SQLAlchemy tables on the existing `Base`, so the existing
`Base.metadata.create_all()` at startup creates them in any existing database
without touching the `analyses` table:

```
conversations           conversation_messages
──────────────          ─────────────────────
id (uuid, PK)           id (autoincrement, PK)
created_at              conversation_id (FK → conversations.id, indexed)
updated_at (indexed)    created_at
analysis_id (nullable)  role  ("user" | "assistant")
title (nullable)        content (JSON: list of content blocks)
```

**Key decision: store the model's own message format.** `content` holds the
exact `text` / `tool_use` / `tool_result` block lists the Messages API uses.
Benefits:

1. The next turn can rebuild the transcript verbatim — the model "remembers"
   which tools it called and what came back.
2. The UI can render tool activity from history (the frontend pairs
   `tool_use` ids with `tool_result.tool_use_id`).
3. No lossy translation layer to maintain.

Within one user turn the stored sequence looks like:

```
user:      [text "Run AAA/BBB/CCC"]
assistant: [text "Looking up...", tool_use(search_assets)]
user:      [tool_result(search_assets)]           ← tool results are "user" role in the API
assistant: [tool_use(run_analysis)]
user:      [tool_result(run_analysis)]
assistant: [text "Done. See /analysis/..."]
```

`ConversationRepository` (same engine, short-lived sessions, like
`AnalysisRepository`) exposes `create`, `get`, `list`, `append_messages`
(also sets a `title` from the first user message) and `link_analysis` (attaches
an analysis to a conversation that has none — used when the agent creates one
in a general "workspace" chat so the conversation follows the user to that page).

The `analysis_id` column is intentionally *not* a foreign key: analyses are
never deleted today, and a conversation should still load if that changes.

---

## 6. Step 4 — Grounding (`assistant_context.py`, `knowledge/methodology.md`)

### 6.1 The system prompt

`SYSTEM_PROMPT` has three sections — role, hard rules, style. The hard rules
are the product's safety and honesty boundary:

- **Ground every number in tool output or provided context.** If a value is not
  available, say so or fetch it.
- **Always distinguish** in-sample estimates vs. walk-forward backtest vs.
  bootstrap scenarios (the three result types users most often conflate).
- **No personalized investment advice**, no buy/sell/hold instructions, no price
  predictions. Explain trade-offs; the user decides. This matches the
  `ASSUMPTIONS` disclaimer the app already shows everywhere.
- **Before `run_analysis`, restate parameters**; prefer modest sampling settings;
  on validation errors, fix and explain.
- Formatting restricted to short paragraphs, `-` bullets, `**bold**`, `code`
  (because the frontend has a deliberately tiny markdown renderer).

### 6.2 The methodology brief

`knowledge/methodology.md` is a ~1,800-word condensation of
`PORTFOLIO_METHODOLOGY.md` and `LEARNING_GUIDE.md`: data pipeline, allocation
rules, the six strategies, in-sample vs. backtest, every backtest metric's
definition, frontier/Monte Carlo, scenarios, every `AnalysisRequest` field with
its bounds, and interpretation caveats. It ships as **package data** (loaded with
`importlib.resources`) so a deployment does not depend on repo-root markdown.

`load_knowledge()` appends the engine's own `METHODS` and `UNITS` dictionaries
from `exports.py` and the `ASSUMPTIONS` list, so the model's definitions are
*literally the same strings* the export ZIP and UI use.

### 6.3 Prompt caching

The static part (system prompt + knowledge, roughly 5k tokens) is sent as one
block with `"cache_control": {"type": "ephemeral"}`. Anthropic caches that
prefix for a few minutes, so repeated calls within a turn and across users pay a
fraction of the input cost. The dynamic context block (below) comes *after* it,
because anything after a changing block cannot be cached.

### 6.4 `summarize_analysis()` — the grounding payload

A saved `AnalysisResponse` can be hundreds of KB (equity curves per strategy,
fan paths, Monte Carlo points, full price snapshot). Sending that every turn is
expensive and mostly irrelevant. `summarize_analysis` builds a compact dict:

- request parameters, data window and provenance
- per-strategy **in-sample** weights, metrics, risk contributions
- per-strategy **backtest** metrics plus rebalance count and date range (no curves)
- benchmark metrics, scenario summary statistics and percentile tables (no paths)
- correlation matrix only when ≤ 12 tickers; otherwise a note to request the dataset
- warnings (capped at 20), the estimation-provenance flag, and the `/analysis/<id>` link

Values are rounded to 6 decimals. A 30-ticker analysis with scenarios enabled
stays under ~40 KB of JSON (tested). The model can drill into anything omitted
with `get_analysis_dataset`.

### 6.5 Per-turn context injection

In `Assistant._system()` a second system block is built per request:

- the page path the user is on (from the frontend)
- if an analysis is open, "The user is currently viewing analysis X" plus its
  summary, with an instruction to use it directly instead of calling
  `get_analysis`
- otherwise, a hint to use `list_analyses` or help configure a new run

This context lives in the system prompt, **not** in the stored user message, so
the database holds only what the user typed, and old context never leaks into
future turns.

---

## 7. Step 5 — The agent core (`assistant.py`)

### 7.1 A protocol instead of the SDK

```python
class LLMClient(Protocol):
    def stream(self, *, system, messages, tools, tool_choice, max_tokens) -> Iterator[TextDelta | FinalMessage]: ...
```

Everything in the loop depends only on this two-event interface:
`TextDelta(text)` while streaming, then one `FinalMessage(content, stop_reason, usage)`.
`AnthropicLLM` implements it with `client.messages.stream(...)`, iterating
`stream.text_stream` and then calling `get_final_message()`. It normalizes the
SDK objects into plain dicts (only `text` and `tool_use` blocks are kept).

`build_llm_client(settings)` returns `None` when no key is set — the single
source of truth for "assistant disabled".

This mirrors how `MarketDataProvider` is injected for market data: `create_app(llm=...)`
accepts any object with that `stream` method, which is how the tests drive the
whole agent with a scripted `FakeLLM` and zero network access.

### 7.2 Tool definitions

Tools are JSON-schema descriptions in the Messages API format
(`name`, `description`, `input_schema`):

| Tool | Reads/does | Why it exists |
| --- | --- | --- |
| `get_analysis(analysis_id)` | `repository.get` → `summarize_analysis` | Compare or explain any saved run, not only the open one. |
| `get_analysis_dataset(analysis_id, dataset_id, offset, max_rows)` | `repository.get_export_source` → `exports.build_data` → one dataset, ≤ 60 rows per call | Lets the model inspect details the summary omits (rebalance events, equity rows, covariance) with bounded token cost. Reuses the export module, so numbers match downloads exactly. |
| `list_analyses(limit)` | `repository.list` | Find recent runs. |
| `search_assets(query, limit)` | `market_data.search` | Resolve company names to provider symbols before running. |
| `run_analysis(request)` | the slot-guarded `run_analysis` closure | Execute a full analysis and persist it. |

The `run_analysis` input schema is **generated from the pydantic model**:
`AnalysisRequest.model_json_schema()`, with `$defs` hoisted to the root of the
tool schema so nested `$ref`s resolve. The model therefore sees every field,
bound, default, and docstring of the real request type, and any future field you
add to `AnalysisRequest` becomes available to the agent automatically.

### 7.3 `ToolExecutor` — run tools, never raise

`execute(name, arguments) -> (ok, payload_for_model, public_summary)`:

- Dispatches to `_tool_<name>` methods via `getattr`.
- Converts `PortfolioError` (domain errors like `backtest_budget_exceeded`),
  pydantic `ValidationError` (e.g. the model sent one ticker), and `TypeError`
  (wrong argument names) into **error tool results** with a readable message.
  The model reads the message and typically fixes its request on the next round.
  This is the "self-correction" behaviour; it would be impossible if these
  surfaced as HTTP 500s.
- Any other exception is logged server-side and reported generically.
- Enforces `assistant_max_analyses_per_turn` and records created analyses so
  the loop can link the conversation.

Two outputs per tool: the full `payload_for_model` (what Claude reads) and a
small `public_summary` (what the browser shows in the tool card, e.g.
`{"analysis_id", "link", "tickers"}`). Keeping them separate means the UI never
has to parse model-oriented JSON blobs.

### 7.4 Rebuilding a valid transcript: `replayable_history`

The Messages API is strict: the transcript must start with a `user` message,
and every `tool_use` must be followed by a matching `tool_result`. After
trimming to the last N messages we could cut in the middle of a tool exchange, so
`replayable_history`:

1. keeps the last `assistant_history_messages - 1` stored messages,
2. drops leading messages until the first is a plain user text message,
3. drops a trailing assistant message whose tool calls never got results
   (possible if a previous turn crashed between the two writes).

### 7.5 The loop: `Assistant._run()`

```python
persist user message; yield start
history = replayable_history(stored) + [new user message]
system  = [cached static block, per-turn context block]
rounds = 0
while True:
    final_round = rounds >= max_tool_rounds
    stream Claude(system, messages, tools, tool_choice = {"type":"none"} if final_round else None)
        → forward TextDelta as SSE text_delta
    append assistant content to messages
    if stop_reason != "tool_use": persist assistant message; break
    for each tool_use block:
        yield tool_call
        result = "limit reached" error if final_round else executor.execute(...)
        yield tool_result
    append user message of tool_result blocks
    persist (assistant, tool results) together
    link conversation to any analysis just created; yield conversation_linked
    if final_round: break
    rounds += 1
yield message_end
```

Points worth understanding:

- **Round cap uses `tool_choice: none`, not "remove the tools".** The API rejects
  a transcript containing `tool_use` blocks if the request does not define the
  tools, so on the last permitted round we keep the definitions but forbid new
  calls, forcing a text answer. If the model still emits a call, it gets an
  error result and the turn ends.
- **Persistence is atomic per tool round.** The assistant message and its tool
  results are written in one `append_messages` call, so the database never holds
  a dangling `tool_use`. The user message is written first so it survives
  provider failures.
- **Error handling.** Any exception in the loop is logged with
  `logger.exception` and converted into one SSE `error` event with a generic
  message. Provider error details (which could include request internals) never
  reach the browser.
- **Concurrency.** `start_turn` acquires the `BoundedSemaphore` *before*
  returning the generator (so busy → clean HTTP 503) and the generator's
  `finally` releases it.

### 7.6 Why validate up front and stream afterwards

`start_turn` performs all checks that should produce an HTTP status (disabled →
503, unknown conversation → 404, busy → 503) *before* handing a generator to
`StreamingResponse`. Once streaming begins, the status code is already 200 and
only in-band `error` events are possible. Splitting the method into
"validate then return generator" is what makes both behaviours testable.

---

## 8. Step 6 — HTTP routes (`main.py`)

All under the key-protected `/api/v1` router, so the existing `X-API-Key`
check applies:

| Route | Purpose |
| --- | --- |
| `GET /assistant/status` | `{enabled, model}` — the UI hides the chat when disabled. |
| `POST /conversations` | Create, optionally linked to an analysis (404 if it does not exist). |
| `GET /conversations?analysis_id=&limit=` | Most-recent-first list; the UI picks the latest for the open analysis. |
| `GET /conversations/{id}` | Conversation with all messages. |
| `POST /conversations/{id}/messages` | The streaming endpoint: `StreamingResponse(generator, media_type="text/event-stream")` with `Cache-Control: no-cache` and `X-Accel-Buffering: no` (tells nginx-style proxies not to buffer). |

The route is a **sync** function returning a sync generator. FastAPI runs sync
route code and iterates sync generators in a threadpool, which is exactly what
the blocking Anthropic SDK and SQLAlchemy sessions need. No `async` was
introduced, matching the rest of the codebase.

Event format: one JSON object per `data:` line, discriminated by `type`:

```
data: {"type":"start","conversation_id":"...","user_message_id":1}
data: {"type":"text_delta","text":"Sharpe "}
data: {"type":"tool_call","id":"toolu_1","name":"run_analysis","input":{...}}
data: {"type":"tool_result","id":"toolu_1","name":"run_analysis","ok":true,"summary":{"analysis_id":"...","link":"/analysis/..."}}
data: {"type":"conversation_linked","analysis_id":"..."}
data: {"type":"message_end","message_ids":[1,2,3]}
data: {"type":"error","code":"assistant_error","message":"..."}
```

---

## 9. Step 7 — Testing an agent without a model (`tests/test_assistant.py`)

`FakeLLM` takes a *script*: a list of `FinalMessage`s (or exceptions) returned
one per call, and records every request (system, messages, tools, tool_choice).
Helpers `text("...")` and `tool_call(name, args)` build the two message shapes.
Combined with the existing `FakeProvider` pattern (synthetic prices), the whole
agent runs in-process with temporary SQLite.

What the tests pin down:

- disabled state (no key) → status `enabled: false`, 503 `assistant_disabled`
- conversation CRUD, 404s, blank-message 422
- a plain reply streams `start → text_delta* → message_end`, persists both
  messages, sets the title, and the request carried the cache-controlled system
  block, the methodology brief, the page context, and all five tools
- the open analysis's real weights appear in the injected context
- a two-tool turn (`search_assets` → `run_analysis` → text): tool events, the
  analysis really exists via `GET /analyses/{id}`, the conversation is linked,
  six messages stored in the right roles, and the *model* received the tool
  outputs it should have
- invalid tool input becomes an `is_error` tool result mentioning the bad
  field, nothing is created, and no 500 occurs
- round and per-turn analysis budgets: second run refused, third round forced
  to `tool_choice: none`, extra call refused, history still consistent
- provider exception → generic `error` event (no internal text leaked) and the
  conversation remains replayable on the next turn
- busy semaphore → 503 `assistant_busy`
- `replayable_history` edge cases; `summarize_analysis` stays bounded on a
  30-ticker run; the knowledge brief loads from the package

> Pattern: *inject the model behind a protocol and script it*. Agent logic
> (loops, persistence, budgets, error mapping) is deterministic code and should
> be tested like any other code. Only prompt quality needs a real model.

---

## 10. Design principles you can reuse

1. **Same code path for humans and agents.** Extract a service function; the
   route and the tool both call it. The agent never bypasses validation,
   budgets, or persistence.
2. **Bound every loop and every resource** (rounds, actions per turn, tokens,
   concurrent turns, history length), and make the bounds configuration.
3. **Store the provider's message format.** It makes replay exact and lets the
   UI reconstruct tool activity from history.
4. **Ground, then constrain.** Give the model real data through tools and a
   compact context summary; forbid numbers from memory in the prompt; cap and
   round what you send to control tokens.
5. **Turn exceptions into tool errors.** Models fix their own mistakes when the
   error message is specific; they cannot when the request 500s.
6. **Keep secrets and raw errors server-side.** The browser gets `enabled: bool`
   and generic error messages, never the key or provider stack traces.
7. **Validate before streaming.** Everything that deserves an HTTP status must
   happen before the first byte is sent.
8. **Inject the model.** A two-method protocol and a scripted fake make the
   entire agent unit-testable, fast, and free.

---

## 11. Where to read the code

| Topic | Location |
| --- | --- |
| Settings and budgets | `portfolio_backend/config.py` |
| Shared analysis pipeline | `portfolio_backend/service.py` → `perform_analysis` |
| Slot-guarded wrapper used by route and tool | `portfolio_backend/main.py` → `run_analysis` |
| Conversation tables and repository | `portfolio_backend/database.py` → `ConversationRecord`, `ConversationMessageRecord`, `ConversationRepository` |
| API models for chat | `portfolio_backend/models.py` → `ChatMessage`, `ConversationDetail`, `ChatSendRequest`, `AssistantStatus` |
| System prompt and knowledge | `portfolio_backend/assistant_context.py` → `SYSTEM_PROMPT`, `load_knowledge`; `portfolio_backend/knowledge/methodology.md` |
| Analysis summary for grounding | `portfolio_backend/assistant_context.py` → `summarize_analysis` |
| Model protocol and Anthropic adapter | `portfolio_backend/assistant.py` → `LLMClient`, `AnthropicLLM`, `build_llm_client` |
| Tool schemas | `portfolio_backend/assistant.py` → `tool_definitions`, `_request_schema` |
| Tool execution and error mapping | `portfolio_backend/assistant.py` → `ToolExecutor` |
| Transcript repair | `portfolio_backend/assistant.py` → `replayable_history` |
| The agent loop and SSE | `portfolio_backend/assistant.py` → `Assistant.start_turn`, `Assistant._run` |
| Routes | `portfolio_backend/main.py` (search for `tags=["assistant"]`) |
| Tests and the fake model | `tests/test_assistant.py` → `FakeLLM`, `FakeProvider` |

---

## 12. Ideas for extending it

- **Propose-only mode:** a setting that turns `run_analysis` into "return the
  validated request for the user to click Run" — same tool, different executor.
- **Compare tool:** `compare_analyses(ids)` returning side-by-side metrics,
  saving the model a few round trips.
- **Per-user ownership:** when authentication lands (see
  `PRODUCTION_READINESS.md`), add `owner_id` to `conversations` alongside
  `analyses` and scope every query.
- **Usage accounting:** `FinalMessage.usage` already carries token counts; log
  or store them per conversation to track cost.
- **Evaluation set:** a handful of real-model transcripts checked for the hard
  rules (no advice, no invented numbers) would complement the deterministic
  tests.
