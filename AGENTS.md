# Frontend verification

- Run frontend commands from `portfolio_frontend/`.
- `npm run build` runs TypeScript project checks and the Vite production build.
- `npm run lint` runs Oxlint. Existing synchronous state updates in effects in `History.tsx` and `AnalysisView.tsx` produce warnings.
- `npm test` runs asset-return, rolling-volatility, and data-table formatting/filtering tests using Node's built-in test runner and TypeScript stripping (Node 22.18+ or 24 recommended). No extra test dependencies are needed.
- For browser interaction checks, mock `/api/v1/**` requests to avoid creating analyses in the user's database.
- `npm run dev` serves the frontend on port 5173 and proxies `/api` and `/health` to the backend on port 8000. Use `-- --port <port> --strictPort` for an isolated verification server.

# Backend verification

- Run `.venv/bin/python -m pytest -q` from the repository root; tests use synthetic providers and temporary SQLite databases.
- `.venv/bin/python -m pytest tests/test_exports.py tests/test_analytics.py -q` verifies data exports and portfolio calculations. `.venv/bin/ruff check portfolio_backend tests` runs backend lint.
- The existing API suite has four baseline failures: nonfinite JSON request validation (NaN and positive/negative Infinity) and empty API-key configuration. Existing backend code also has lint violations; distinguish these from new failures.
- Export endpoints must use saved snapshots without fetching market data or rerunning portfolios/backtests. New analyses persist optimizer moments; legacy reconstructed moments must remain explicitly labeled. The ZIP's canonical `prices.json` must match the saved snapshot SHA-256.
