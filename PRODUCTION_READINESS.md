# Web Launch and Production Readiness

Assessment date: 2026-09-28

Status: Deferred proposal. No hosting providers have been selected or provisioned, and no implementation is implied by this document. Recheck the codebase, provider pricing, limits, and terms before starting.

## Goal and recommendation

Launch a low-cost, invite-only proof of concept (POC), then improve reliability before opening public registration. Keep the existing React/Vite frontend and FastAPI analytics backend; a rewrite is unnecessary.

Recommended starting stack:

- **Cloudflare Pages:** static frontend hosting.
- **Railway:** Python/FastAPI backend.
- **Supabase:** managed PostgreSQL and user authentication.

Plan for approximately **$10–25/month in infrastructure at light usage**, excluding domain registration, email delivery, taxes, and market-data licensing. This is a planning allowance, not a measured workload cost or guaranteed ceiling. Market-data licensing may exceed hosting costs.

Start with a small invited cohort and conservative calculation limits. Do not introduce Kubernetes, microservices, multiple backend replicas, or a separate cache service without measured need.

## Current repository state

| Area | Current implementation | Launch implication |
| --- | --- | --- |
| Frontend | React, Vite, TypeScript, React Router | Can be built and deployed as static assets; configure SPA route fallback |
| Backend | FastAPI with NumPy, Pandas, SciPy, and scikit-learn | Use a Python/container host; benchmark memory and CPU requirements |
| Persistence | SQLAlchemy, local SQLite by default; PostgreSQL driver and URL handling already present | Managed PostgreSQL does not require replacing the persistence layer |
| Schema management | `Base.metadata.create_all()` at startup | Add versioned migrations; table creation does not migrate existing schemas |
| Authentication | Optional shared `X-API-Key`; no configured key means unrestricted API access | Replace public-browser shared-key access with individually authenticated users |
| Browser API key | `VITE_API_KEY` can be embedded in frontend JavaScript | Browser-delivered values are public; this cannot protect a public application |
| Ownership | Analysis records have no owner; history, results, and prices are shared | Login alone is insufficient; enforce per-user authorization in the backend |
| Calculations | Run synchronously within the HTTP request; concurrency bounded per app instance | Add quotas, benchmark request duration, and introduce durable jobs if needed |
| Storage size | Full results and price snapshots stored as JSON | Measure bytes per analysis; enforce retention and storage quotas |
| Market data | `yfinance` with an interchangeable provider interface | Verify storage/display rights before serving other users |
| Health | `/health` reports service version without dependency probes | Add a separate database readiness check |
| Verification | Backend API/analytics/provider tests; frontend calculation tests and build/lint commands | Extend with authorization, PostgreSQL, and deployment checks |

Relevant code:

- [Backend configuration](portfolio_backend/config.py)
- [Database models and repository](portfolio_backend/database.py)
- [API routes and authorization](portfolio_backend/main.py)
- [Request limits](portfolio_backend/models.py)
- [Market-data implementation](portfolio_backend/market_data.py)
- [Market-data provider interface](portfolio_backend/market_types.py)
- [Frontend API client](portfolio_frontend/src/api/client.ts)
- [Frontend development proxy](portfolio_frontend/vite.config.ts)
- [Backend guide](portfolio_backend/README.md)

SQLite already persists data locally. The cloud concern is that ordinary container-local files can disappear when an instance is replaced or redeployed. Managed PostgreSQL keeps application data independent of backend instances. Persistence alone is not a backup strategy.

## Proposed deployment architecture

```text
Browser
  +-- Static React frontend --------> Cloudflare Pages
  +-- Sign-in / session refresh ----> Supabase Auth
  +-- Authenticated API requests ---> FastAPI on Railway
                                        +-- Supabase PostgreSQL
                                        +-- Authorized market-data provider
```

Initially, route all application-data access through FastAPI. Keep ownership checks, calculation limits, and business rules in one place. Browser access to Supabase Auth does not require direct browser access to analysis tables.

Deployment considerations:

- Build the frontend for production; do not expose the Vite development server.
- Set the public API URL explicitly. Vite's local `/api` proxy is not production routing.
- Configure exact CORS origins and allow the `Authorization` header. CORS is not authentication.
- Enable HTTPS and verify frontend deep links work after refresh.
- Store database credentials and other secrets only in backend/provider secret settings. Never put privileged credentials in `VITE_*` variables.
- Choose nearby backend/database regions, accounting for intended users and privacy requirements.
- For a persistent SQLAlchemy backend, select a compatible direct database connection or session pooler. Supabase direct connections normally require IPv6; session pooling supports IPv4-only environments. Bound the SQLAlchemy pool to the database connection budget.
- Use a restricted database role for runtime access and a separate privileged migration process.

## Hosting costs and trade-offs

Provider details below were checked on the assessment date and may change.

| Component | Starting option | Cost / limitation |
| --- | --- | --- |
| Frontend | Cloudflare Pages Free | Static asset requests are free; build and asset limits still apply |
| Backend | Railway Hobby | $5/month minimum including $5 resource usage; additional usage is billed |
| Database and auth | Supabase Free | 500 MB database; free projects may pause after a week of inactivity; automatic backups not included |
| Domain | Optional for initial POC | Provider domains allow a start without domain registration |
| Auth email | External SMTP if email flows are enabled | Separate provider setup and potentially separate cost |
| Market data | Undecided | Must establish rights and pricing for multi-user use, storage, and display |

Railway advertises resource rates of approximately $10/GB-month for memory, $20/vCPU-month for CPU, and $0.05/GB egress. Billing depends on actual consumption; the $5 minimum is not a $5 total-price guarantee. Benchmark this app before choosing resource caps.

Supabase Free is reasonable for a carefully backed-up POC whose limitations are understood, not a reliability promise. The 500 MB database allowance can become restrictive because analyses contain results, sampled portfolios, backtests, and price snapshots.

When users depend on their saved work, consider Supabase Pro, starting at $25/month for one Micro project through included compute credits, with daily backups retained for seven days and no inactivity pausing. Additional projects, compute, usage, and add-ons can increase the bill. Backend costs remain separate.

Alternatives:

- **Render:** fixed-price backend starts at $7/month with 512 MB RAM. That memory tier needs testing for this workload. Free PostgreSQL expires after 30 days and is not suitable as the ongoing POC database.
- **Small VPS:** potentially inexpensive, but transfers OS patching, database maintenance, TLS, backups, monitoring, and recovery to the project owner. Prefer managed services for the first launch unless those operational responsibilities are intentional.

Configure billing alerts and review available resource/spending controls. Understand whether a spending limit stops the service: an alert alone is not a hard cap.

## Authentication and private user data

A website does not inherently need login. A public landing page or read-only sample demo can be anonymous. Private saved portfolios, personal history, and per-user limits require identity and authorization.

Recommended POC approach:

1. Use Supabase Auth instead of implementing password storage and recovery.
2. Start with Google sign-in and an application-level invite allowlist enforced by the backend.
3. Keep public access disabled until resource and abuse controls are ready.
4. Add email-based sign-in if needed. Configure external SMTP for verification, magic links, or password resets; Supabase's default sender is restricted to project-team addresses and is not intended for production delivery.

Required implementation:

- Frontend login, logout, session refresh, and expired-session handling.
- Backend validation of token signature, allowed algorithm, issuer, audience, and expiry, using the provider's supported key-verification flow.
- Derive identity from the validated token, never a client-submitted owner ID.
- Add an indexed, non-null `owner_id` to analysis records after an explicit legacy-data migration.
- Scope every history, result, and price-snapshot query to the authenticated owner; apply the same rule to future update/delete/export routes.
- Assign existing local analyses to the owner's account only after explicit confirmation, or leave them out of the hosted database. Never silently expose legacy analyses to everyone.
- Protect against direct access through Supabase's generated Data API: keep application tables unexposed or use appropriate permissions and row-level security (RLS).
- Do not assume Supabase Auth or RLS automatically secures existing SQLAlchemy connections. Privileged roles may bypass RLS; backend ownership enforcement remains essential in this design.
- Keep privileged Supabase keys and database credentials out of the browser.

Acceptance tests must demonstrate that user A cannot list or retrieve user B's analyses or price snapshots, including when the analysis ID is known. Test missing, expired, malformed, wrong-issuer, and wrong-audience tokens as well.

## Market-data rights: launch gate

The current provider uses `yfinance`. Its documentation states that Yahoo Finance API use is intended for personal use and directs users to Yahoo's terms. The Python library's open-source license does not grant rights to the downloaded market data.

Before serving other users, establish permission for:

- Fetching market data on users' behalf.
- Storing historical price snapshots and cached data.
- Displaying prices, charts, and derived analytics.
- Any commercial use or redistribution.

A free or invite-only POC is not automatically exempt. A paid API subscription also does not necessarily include the required display and storage rights. Obtain and review the applicable provider terms; this assessment is not a legal determination.

For a low-cost demonstration while resolving licensing, use synthetic data or a dataset explicitly licensed for the intended use. The existing `MarketDataProvider` interface provides a replacement boundary without rewriting analytics.

Also verify the replacement provider's adjusted-price methodology, instrument coverage, currencies, historical depth, attribution requirements, quotas, and behavior from the chosen hosting region.

## Phased implementation checklist

### Phase A: Safe invite-only POC

Complete before inviting users:

- [ ] Resolve market-data rights or select appropriately licensed/synthetic demonstration data.
- [ ] Provision managed PostgreSQL and configure secure, bounded connections.
- [ ] Add Alembic migrations, ownership fields, and ownership/listing indexes.
- [ ] Decide how existing local analyses are handled; preserve the original database during migration.
- [ ] Implement managed authentication, backend token verification, and invite enforcement.
- [ ] Remove shared-key authentication from the public browser flow.
- [ ] Enforce ownership on all analysis and price endpoints.
- [ ] Fail startup in production if required security configuration is missing.
- [ ] Restrict Supabase Data API exposure and database privileges.
- [ ] Add per-user analysis quotas and per-IP request limits, including asset search.
- [ ] Set conservative ticker, history-window, Monte Carlo, frontier, and rebalance limits.
- [ ] Start with one backend instance and explicitly limited calculation concurrency.
- [ ] Configure production deployment, HTTPS, CORS, frontend API URL, and SPA fallback.
- [ ] Add CI for backend tests/lint and frontend tests/build/lint.
- [ ] Configure structured error logging without tokens, credentials, or unnecessary portfolio details.
- [ ] Add uptime monitoring, database readiness checks, and billing alerts.
- [ ] Schedule backups and successfully restore one into an isolated database.
- [ ] Publish a privacy notice, research-risk disclosures, retention policy, and account/data deletion process.
- [ ] Run the release acceptance checks below.

The existing semaphore bounds simultaneous analyses per app instance. It is not a per-user quota, rate limiter, or global concurrency control. Additional worker processes or replicas each get independent limits and caches.

### Phase B: Dependable broader beta

- [ ] Benchmark typical and worst-allowed analyses on the actual hosting tier: duration, peak RAM, CPU, provider calls, response size, and saved-record size.
- [ ] Upgrade database availability/backups before users rely on the service; choose a plan matching the intended reliability level.
- [ ] If analyses approach request timeouts, introduce a durable job model: submit, job ID, queued/running/succeeded/failed states, and progress/status polling.
- [ ] Ensure durable jobs have bounded retries, failure reporting, ownership, and restart recovery. FastAPI background tasks alone are not a durable queue.
- [ ] Add duplicate-submission protection so retries do not repeatedly consume compute or create duplicate results.
- [ ] Add automated deployment smoke checks and a rollback procedure, including migration compatibility.
- [ ] Test provider outages/rate limits, database failures, expired sessions, and capacity exhaustion.
- [ ] Implement storage quotas and retention/deletion workflows before saved JSON grows without bounds.
- [ ] Review privacy obligations for target jurisdictions and any financial-services implications of the product's actual features; a disclaimer alone is not a compliance strategy.

### Phase C: Scale when justified

Only add these when measurements or product needs justify them:

- Separate calculation workers and a durable queue.
- Shared market-data caching, subject to provider rights.
- Multiple backend replicas with shared quotas and global concurrency controls.
- Larger storage or object storage for snapshots, with ownership and retention preserved.
- Billing, subscriptions, and plan-based quotas.
- Expanded administrative controls, audit trails, and reliability commitments.

## Verification and release acceptance

This assessment did not include a load test, deployment, restore drill, or full security audit.

Existing verification commands:

```bash
# Repository root; use the project's Python environment
pytest -q
ruff check .

# portfolio_frontend/
npm test
npm run build
npm run lint
```

See [AGENTS.md](AGENTS.md) for frontend runtime requirements and known lint warnings. Browser interaction checks should mock `/api/v1/**` to avoid creating analyses in the user's database.

Before an invite-only release, verify:

- Authenticated user isolation across history, results, and prices, including direct-ID requests.
- Unauthenticated and invalid-token requests cannot access private data or consume analysis resources.
- Production configuration cannot accidentally disable authentication.
- Frontend build artifacts contain no shared API secret or privileged backend credentials.
- Supabase Data API access cannot bypass the intended authorization boundary.
- PostgreSQL integration and migrations work against an isolated PostgreSQL database, not just SQLite tests.
- Data survives backend restarts and redeployments.
- A backup restores successfully; the restored data is usable by the application.
- Quotas and capacity limits behave correctly under concurrent requests.
- Worst-allowed analysis requests fit the chosen runtime and hosting limits, or run through a durable job path.
- Login callbacks, logout, token refresh, CORS, and frontend deep links work on deployed domains.
- Provider or database failure produces safe user-facing errors and actionable internal logs.

## Decisions to revisit when implementation resumes

1. Is the launch a disposable demo, private research beta, or public product?
2. What is the monthly budget, including data licensing and email rather than hosting alone?
3. How many invited users and analyses per day are expected? What concurrency is realistic?
4. Which markets, instruments, historical depth, and data-display rights are required?
5. Is Google-only sign-in acceptable initially?
6. Should current local analyses migrate to the owner's hosted account?
7. Which region, retention period, and acceptable data-loss/recovery targets apply?
8. Are users paying or relying on saved results? If so, avoid treating free-tier limits as production guarantees.

Recommended first implementation milestone: **managed PostgreSQL, Supabase login, and private per-user analysis history**, followed by deployment and operational safeguards. Market-data permission remains a prerequisite for serving real market data to users.

## Provider references

Checked 2026-09-28; verify again before purchasing or deploying:

- [Cloudflare Pages pricing](https://developers.cloudflare.com/pages/functions/pricing/)
- [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/)
- [Railway pricing](https://railway.com/pricing)
- [Supabase pricing](https://supabase.com/pricing)
- [Supabase free-project pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
- [Supabase custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp)
- [Supabase PostgreSQL connections](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Render pricing](https://render.com/pricing.md)
- [Render free-tier restrictions](https://render.com/docs/free)
- [yfinance documentation and data-use warning](https://ranaroussi.github.io/yfinance/)
