# Frontend verification

- Run frontend commands from `portfolio_frontend/`.
- `npm run build` runs TypeScript project checks and the Vite production build.
- `npm run lint` runs Oxlint. Existing synchronous state updates in effects in `History.tsx` and `AnalysisView.tsx` produce warnings.
- `npm test` runs asset-return, rolling-volatility, and data-table formatting/filtering tests using Node's built-in test runner and TypeScript stripping (Node 22.18+ or 24 recommended). No extra test dependencies are needed.
- For browser interaction checks, mock `/api/v1/**` requests to avoid creating analyses in the user's database.
- `npm run dev` serves the frontend on port 5173 and proxies `/api` and `/health` to the backend on port 8000. Use `-- --port <port> --strictPort` for an isolated verification server.
