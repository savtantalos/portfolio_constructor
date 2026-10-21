# Frontend verification

- Run frontend commands from `portfolio_frontend/`.
- `npm run build` runs TypeScript project checks and the Vite production build.
- `npm run lint` runs Oxlint. Existing synchronous state updates in effects in `History.tsx`, `AnalysisView.tsx`, and `components/assistant/useAssistant.ts` produce warnings.
- `npm test` runs asset-return, rolling-volatility, data-table formatting/filtering, and assistant SSE/event-reducer tests using Node's built-in test runner and TypeScript stripping (Node 22.18+ or 24 recommended). No extra test dependencies are needed.
- For browser interaction checks, mock `/api/v1/**` requests to avoid creating analyses in the user's database.
- `npm run dev` serves the frontend on port 5173 and proxies `/api` and `/health` to the backend on port 8000. Use `-- --port <port> --strictPort` for an isolated verification server.

# Backend verification

- Start the local API from the repository root with `.venv/bin/python -m uvicorn portfolio_backend.main:app --host 127.0.0.1 --port 8000`. Without `--reload`, restart it after backend changes; Vite reloads only the frontend. A generic 404 for a newly added endpoint can indicate a stale backend; check its live `/openapi.json` routes.
- Run `.venv/bin/python -m pytest -q` from the repository root; tests use synthetic providers and temporary SQLite databases.
- `.venv/bin/python -m pytest tests/test_exports.py tests/test_analytics.py -q` verifies data exports and portfolio calculations. `.venv/bin/ruff check portfolio_backend tests` runs backend lint and is currently clean.
- The existing API suite has four baseline failures: nonfinite JSON request validation (NaN and positive/negative Infinity) and empty API-key configuration. Distinguish these from new failures.
- Export endpoints must use saved snapshots without fetching market data or rerunning portfolios/backtests. New analyses persist optimizer moments; legacy reconstructed moments must remain explicitly labeled. The ZIP's canonical `prices.json` must match the saved snapshot SHA-256.
- The analysis pipeline lives in `portfolio_backend/service.py` (`perform_analysis`); both the HTTP route and the assistant's `run_analysis` tool call it through the slot-guarded `run_analysis` closure in `main.py`.

# Research assistant

- Enable it by setting `PORTFOLIO_ANTHROPIC_API_KEY` (see `.env.example`); otherwise `/api/v1/assistant/status` reports `enabled: false` and chat routes return 503 `assistant_disabled`. Enabling it sends analysis summaries and chat messages to Anthropic.
- `tests/test_assistant.py` uses a scripted `FakeLLM` injected through `create_app(llm=...)`; no network access or key is needed. Add scenarios there rather than calling the real provider.
- Conversations and messages are stored in the `conversations` and `conversation_messages` tables (created by `create_all` on startup; no migration of existing tables). Messages are stored as provider-shaped content blocks so history replays verbatim.
- Streaming uses server-sent events from a sync generator (`StreamingResponse`); the frontend reads it with `fetch`, not axios. For manual checks, run a throwaway database (`PORTFOLIO_DATABASE_URL=sqlite:////tmp/x.db`) so smoke runs do not pollute `portfolio.db`.
- See `ASSISTANT_BACKEND_GUIDE.md` for a walkthrough of the agent design.
