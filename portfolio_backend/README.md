# Portfolio Construction Backend — Code Guide

A FastAPI service that fetches adjusted daily prices for equities/ETFs, computes
constrained portfolio allocations, Monte Carlo weight samples, an efficient
frontier, correlations, and walk-forward backtests, then stores each analysis so
it can be retrieved later.

This guide explains each file: what it does, the Python/FastAPI idioms it uses,
and *why* the code is written the way it is.

## Big picture

```
HTTP request
    │
    ▼
main.py          FastAPI app: auth, routes, exception handlers, concurrency limit
    │
    ├──► models.py        Pydantic schemas: request validation + response types
    ├──► market_data.py   YahooFinanceProvider: fetch/validate/cache prices
    │        └── uses market_types.py  (MarketDataset + MarketDataProvider protocol)
    ├──► analytics.py     numpy/scipy math: optimization, sampling, backtest
    ├──► database.py      AnalysisRepository: SQLAlchemy persistence
    └──► errors.py        PortfolioError: one exception type for all domain failures
```

Layers only talk *downward* (main → analytics/market_data → models/errors). That
keeps each file independently testable: the test suite injects a fake provider
into `create_app()` and never touches Yahoo Finance.

Request lifecycle for `POST /api/v1/analyses`:

1. `Depends(authorize)` checks `X-API-Key` (if `PORTFOLIO_API_KEY` is set).
2. FastAPI parses the body into `AnalysisRequest` — all Pydantic validation runs
   here, before any market data is fetched.
3. `market_data.history()` returns a `MarketDataset` of common trading dates.
4. `analyze()` runs the math; warnings from data alignment are merged in.
5. A `PriceSnapshot` is hashed (SHA-256) for reproducibility, the full
   `AnalysisResponse` + snapshot are saved via the repository, and a `Location`
   header points at `GET /api/v1/analyses/{id}`.

Any `PortfolioError` raised at any step is converted to a consistent
`{"error": {"code", "message"}}` HTTP response (see below).

---

## `errors.py` — the domain error type

```python
class PortfolioError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
```

Six lines, but it's the backbone of error handling. Instead of scattering HTTP
details through the math and data layers, every module raises one exception type
that carries three things:

- `code` — a stable machine-readable string (`"currency_mismatch"`,
  `"analysis_not_found"`, ...). Clients can switch on this; it never changes with
  wording tweaks.
- `message` — a human-readable, *safe* explanation. Upstream exceptions are
  mapped in `market_data.py::_upstream_error` so raw provider/library messages
  (which could leak internals) never reach the client.
- `status_code` — the HTTP status, defaulting to **422** (unprocessable entity —
  the most common case: the request was understood but can't be fulfilled, e.g.
  not enough history). Callers pass 401/404/502/503 where appropriate.

`super().__init__(message)` keeps the exception's `str()`/`repr()` sensible for
logs and tracebacks.

Why a single exception class instead of many? The handler in `main.py` only
needs one registration, and the `code` field already distinguishes cases
(`analytics.py` checks `exc.code == "no_positive_excess_return"` to decide
whether to downgrade an error to a warning).

## How `@app.exception_handler(PortfolioError)` works in `main.py`

```python
@app.exception_handler(PortfolioError)
async def handle_portfolio_error(request: Request, error: PortfolioError):
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )
```

- `@app.exception_handler(X)` is FastAPI's decorator for "when an exception of
  type `X` (or a subclass) propagates out of any endpoint or dependency, call
  this function instead of returning a 500." It's the same registration pattern
  as `@app.get(...)`: the decorator just puts the function in the app's
  exception-handler table.
- `request: Request` is required by the handler signature (FastAPI always passes
  it, even though this handler doesn't use it).
- `async def` because exception handlers run inside the ASGI event loop and
  FastAPI `await`s them. This handler does no I/O, so `async` costs nothing — it
  returns immediately. Important: **`async` here does not make the endpoints or
  the math asynchronous.** The endpoints are plain `def`, so Starlette runs them
  in a threadpool; the handler is async only because that's the required calling
  convention.
- It returns a `JSONResponse` directly (bypassing `response_model`), using the
  status and code the exception carried. That's why every domain failure in the
  API has the identical shape `{"error": {"code": ..., "message": ...}}`,
  matching the `ErrorResponse` schema declared on the router.

There is a second handler for `SQLAlchemyError`: any unexpected database failure
becomes `503 storage_unavailable` with a fixed generic message — again so raw
driver errors can't leak to clients.

Two error shapes to be aware of (this is intentional but worth knowing):

- **Domain errors** (`PortfolioError`, `SQLAlchemyError`) → `{"error": {...}}`
  via these handlers.
- **Schema validation errors** (malformed JSON body, bad UUID in the path,
  `limit=0`) → FastAPI's built-in `RequestValidationError` handler →
  `{"detail": [...]}` with HTTP 422. Tests assert both behaviors.

## `config.py` — settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PORTFOLIO_", env_file=".env", extra="ignore", validate_assignment=True
    )
    database_url: str = "sqlite:///./portfolio.db"
    api_key: SecretStr | None = None
    ...
```

`pydantic-settings` reads environment variables at instantiation:
`PORTFOLIO_API_KEY`, `PORTFOLIO_DATABASE_URL`, `PORTFOLIO_CORS_ORIGINS`,
`PORTFOLIO_CACHE_TTL_SECONDS`, etc. Notable choices:

- `SecretStr` wraps the API key so it never appears in `repr()`/logs/dumps;
  `main.py` unwraps it only inside `compare_digest`.
- `Field(ge=..., le=...)` bounds every numeric setting — a misconfigured env var
  fails fast at startup instead of misbehaving later.
- `validate_assignment=True` makes `settings.api_key = "..."` in tests get
  validated/coerced too.
- `extra="ignore"` means unrelated env vars in a shared `.env` don't crash it.
- Defaults are safe for local dev: no API key (auth disabled), local SQLite, 2
  concurrent analyses, 200-rebalance CPU budget.

## `models.py` — request/response schemas

Everything inherits from `StrictModel` (`extra="forbid"`, `allow_inf_nan=False`):
unknown JSON fields are rejected instead of silently ignored, and NaN/Infinity
can never enter through the API or out through a response.

`AnalysisRequest` shows Pydantic's two validator levels:

- `@field_validator("tickers", mode="before")` — normalizes raw input *before*
  type checks: `" aaa "` → `"AAA"`. This is why `" aaa "` in a request is legal
  but stored uppercase.
- `@model_validator(mode="after")` — cross-field rules that single fields can't
  express: unique tickers, `start_date < end_date`, ≤20-year window, no future
  end date, and the linear-programming feasibility check
  `count*min_weight ≤ 1 ≤ count*max_weight` (without it, the optimizer would just
  fail obscurely later).
- Regex `Field(pattern=...)` constraints mirror what Yahoo accepts for tickers
  and enforce a 3-letter uppercase currency.

Response models (`AnalysisResponse`, `AnalyticsResult`, `BacktestResult`,
`PriceSnapshot`, `DataSummary`, `AnalysisSummary`, `ErrorResponse`,
`HealthResponse`) are also the OpenAPI contract — `response_model=` on each route
serializes through them, so the schema *is* the API documentation at `/docs`.

`Strategy` is a `str, Enum`, so `"equal_weight"` in JSON maps to
`Strategy.EQUAL_WEIGHT` and comparisons like `strategy == Strategy.MAXIMUM_SHARPE`
work in the analytics layer.

## `market_types.py` — the provider seam

```python
@dataclass
class MarketDataset:
    prices: pd.DataFrame
    instruments: list[Instrument]
    fetched_at: datetime
    warnings: list[str] = field(default_factory=list)
    provider: str = "yahoo_finance"
    adjustment: str = "Yahoo adjusted close: splits and cash dividends"

class MarketDataProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[Instrument]: ...
    def history(self, tickers, start, end, base_currency) -> MarketDataset: ...
```

Two deliberate decouplings:

- `MarketDataProvider` is a `typing.Protocol` — structural typing ("duck typing
  with type checking"). `create_app(provider=...)` accepts anything with these
  two methods, which is exactly how `tests/test_api.py::FakeProvider` injects
  synthetic data without subclassing or mocking internals.
- `MarketDataset` is a plain dataclass (not Pydantic — it holds a DataFrame) that
  bundles everything the API layer needs: the aligned price matrix, per-symbol
  metadata, a fetch timestamp, provider/attribution strings, and **warnings**
  (e.g. "history starts after requested start"). Warnings flow through to
  `results.warnings` so data-quality caveats are visible in every response.

## `market_data.py` — Yahoo Finance provider

`YahooFinanceProvider` implements the protocol. The design theme is *validate
everything, assume nothing*:

- **`_upstream_error()`** maps yfinance/Python exceptions to safe
  `PortfolioError`s: rate-limit → 503 `market_data_rate_limited`, missing ticker
  → 422, timeout → 503, malformed data → 422, anything else → 502
  `market_data_upstream_error`. Unknown exceptions get a generic message —
  provider internals never leak.
- **`search()`** wraps `yf.Search`, filters to `_SUPPORTED_TYPES = {EQUITY, ETF}`
  with valid symbol shape, dedupes, maps to `Instrument`.
- **`history()`** validates inputs again (defense in depth — the API validates
  too, but the provider is usable without the API), then per symbol calls
  `client.history(..., auto_adjust=False)` and requires an **`Adj Close`**
  column: never unadjusted prices, never silently falling back to `Close`
  (splits would fabricate fake losses). It also pulls history metadata and
  *requires* it to declare both the instrument type and a currency **equal to**
  `base_currency` — `GBp` is rejected, not converted; no FX.
- **Alignment**: all series are outer-joined then `dropna(how="any")` — only
  dates where *every* ticker trades survive, nothing is forward-filled. Dropped
  dates and truncated ranges become warnings. Fewer than 61 common rows →
  `insufficient_history`.
- **Cache**: an `OrderedDict` used as a bounded LRU guarded by `RLock`, keyed on
  `(tickers-tuple, start, end, currency)` with `time.monotonic()` TTL expiry.
  Two subtleties: hits and stores go through `_copy_dataset()` (deep copy) so a
  caller mutating a returned DataFrame can't poison the cache, and *failures are
  never cached*. Constructor validates its own config since `Settings` bounds
  could be bypassed by direct use.

## `analytics.py` — the math engine

Pure functions over a price DataFrame — no FastAPI, no provider, no DB. Errors
are `PortfolioError` codes. Flow inside `analyze()`:

`_validate` → `_estimate` → `_weights`/`_point`/`_frontier`/`_sample`/`_backtest`
→ `AnalyticsResult`.

- **`_validate`**: ≥61 rows (60 returns); `DatetimeIndex` unique, sorted, and
  unique *after `.normalize()`* (two timestamps on one calendar day count as
  duplicates); columns match `request.tickers` exactly; all prices finite and
  >0; arithmetic returns finite. Backtests additionally need
  `lookback_days + 3` rows: lookback returns + 1 execution-lag return + ≥1
  realized return.
- **`_estimate`**: `mu` = mean daily arithmetic return × 252 (arithmetic, not
  log/geometric). Covariance = **Ledoit–Wolf shrinkage** × 252, then symmetrized
  (`Σ/2 + Σᵀ/2`) — shrinkage keeps near-collinear assets from producing a
  singular/unstable matrix that SLSQP would choke on.
- **`_solve`** wraps `scipy.optimize.minimize(method="SLSQP")` with `ftol=1e-12`,
  `maxiter=1000`, and treats *both* optimizer failure and "success" with
  infeasible weights as `optimization_failed` — never returns a fake optimum.
- **`_weights`** dispatches per strategy:
  - `EQUAL_WEIGHT` → `1/n` (note: bypasses bound checks by design).
  - `MINIMUM_VARIANCE` → min `wᵀΣw` s.t. `Σw=1`, box bounds; shortcuts to the
    initial point when the problem is degenerate (zero-variance or zero-slack
    bounds), then still validates.
  - `MAXIMUM_SHARPE` → first a greedy `_max_return` on **excess** returns checks
    whether *any feasible portfolio* (not any single asset) has `μw − rf > 0`;
    if not, `no_positive_excess_return` — which `analyze()` downgrades to a
    warning and simply omits that strategy. Otherwise it solves the classic
    tangency transform: minimize `yᵀΣy` s.t. `scaled_excess·y = 1`, `y ≥ 0`, and
    the clever linearization `y_i ≥ lower_i·Σy`, `y_i ≤ upper_i·Σy` written as
    `(I − lower·1ᵀ)y ≥ 0` / `(upper·1ᵀ − I)y ≥ 0` — bounds on *weights* become
    linear constraints on *unscaled* `y` because `w = y/Σy` is unknown up front.
    Then `w = y/Σy` and it's re-validated.
- **`_frontier`**: min-variance point first, then interior targets equally spaced
  in **expected return** (`np.linspace`, not in volatility), each a min-variance
  solve with a `μw ≥ target` inequality constraint. The endpoint is *not* the
  greedy max-return portfolio — `_max_return` also returns `face_lower/face_upper`
  (the box-face containing all max-expected-return optima: assets pinned at bound
  stay pinned, the partially filled tie-group keeps slack), and the endpoint is
  min-variance *on that face*. Ties in `mu` are split proportionally to bound
  width — deterministic, optimizer-independent.
- **`_sample`**: seeded **hit-and-run MCMC** on the bounded simplex —
  `default_rng(request.random_seed)`, Gaussian direction projected to sum-zero,
  analytic interval bounds along the ray, uniform step, small sum-correction for
  float drift, burn-in `20·n` and thinning `3·n`. These are *correlated* draws,
  not i.i.d. uniform — the response warning says so explicitly. Degenerate bounds
  repeat the sole feasible allocation.
- **`_backtest`**: walk-forward with a deliberate execution lag, indexed
  carefully because `returns[i]` is the move `dates[i] → dates[i+1]`:
  - NAV = 1 at `dates[lookback]` close (cash until entry); loop starts at
    `first = lookback + 1`.
  - On `dates[index]`, holdings first drift by `returns[index−1]` (the return
    *into* that close), then — if it's a rebalance day — weights are refit on
    `returns[index−lookback−1 : index−1]`, i.e. estimation *excludes* the
    execution-day return. No look-ahead.
  - Costs: entry charges a flat `fee_rate` on initial capital (turnover 1, invest
    `1 − fee`); later rebalances solve the self-financing equation
    `after + fee·‖after·target − holdings‖₁ = before` with `brentq` — cost is on
    *full one-way notional*, turnover is notional/pre-trade NAV, costs are in
    initial-wealth units.
  - Metrics: total return, CAGR via `expm1(log(V)·365.25/calendar-days)`,
    sample-std daily vol ×√252, Sharpe net of `rf/252` daily, running-peak
    drawdown, summed turnover/cost. `Sharpe = None` when vol ≈ 0. A nonpositive
    NAV raises `backtest_failed`; rolling `MAXIMUM_SHARPE` failures omit just
    that backtest with a warning.
- **`analyze`** also computes risk contributions `w·(Σw)/wᵀΣw` (zeros if
  variance ≈ 0) and a plain `DataFrame.corr()` on raw returns (NaN → `None`).
  Every methodological caveat is appended to `warnings` — the API returns its
  own honest limitations alongside the numbers.

## `database.py` — persistence

SQLAlchemy 2.0 style (`DeclarativeBase`, `Mapped`, `mapped_column`, `select`,
`Session`). One table, `analyses`, stores the whole result JSON and the price
snapshot JSON next to indexable columns (`created_at`, `tickers`, dates).

`AnalysisRepository` encapsulates the engine so `main.py` never writes SQL:

- `__init__` normalizes `postgres://` → `postgresql+psycopg://`, enables
  `pool_pre_ping` (drop dead connections), sets SQLite `check_same_thread=False`
  + 30s busy timeout (needed because sync endpoints run in a threadpool), and
  uses `StaticPool` for in-memory DBs so the test fixture's schema survives
  across sessions.
- `initialize()`/`close()` are called from the app lifespan (create tables /
  dispose engine).
- `save()` does one transactional insert (`session.begin()`); `get()` rehydrates
  the stored dict through `AnalysisResponse.model_validate` — storage is
  validated on the way *out* too, so schema changes surface as errors instead of
  silent corruption. `list()` returns newest-first `AnalysisSummary` rows with
  deterministic tie-break (`id desc`).

## `main.py` — the application

Everything is inside `create_app(settings, provider)` — an **app factory**, so
tests build isolated apps with fake settings/providers instead of importing a
global singleton. The module-level `app = create_app()` is just the production
instance Uvicorn serves.

- `ASSUMPTIONS` is a disclosure list returned verbatim in every analysis —
  methodological limits are part of the API contract, not a README footnote.
- `lifespan` (an `@asynccontextmanager`): `repository.initialize()` before the
  first `yield`, `repository.close()` in `finally` — startup/shutdown resource
  management tied to the ASGI lifespan protocol.
- `CORSMiddleware` is only added when `PORTFOLIO_CORS_ORIGINS` is configured —
  browsers are denied by default.
- `slots = BoundedSemaphore(max_concurrent_analyses)`: `POST /analyses` calls
  `acquire(blocking=False)` and releases in `finally`. A **threading**
  semaphore (not `asyncio.Semaphore`) is correct here because endpoints are
  sync `def` running in Starlette's threadpool — it's a CPU-boundness limit,
  not an async-concurrency limit. Overflow → `503 analysis_capacity_reached`.
- `authorize` dependency: `APIKeyHeader(auto_error=False)` extracts
  `X-API-Key` without FastAPI auto-raising its own error shape, then
  `secrets.compare_digest` compares bytes in constant time (no timing oracle)
  and raises the standard `401 unauthorized` PortfolioError. It's attached as
  `dependencies=[Depends(authorize)]` on the `APIRouter` so it protects every
  `/api/v1/*` route while `/health` stays open. If no key is configured, it's a
  no-op — local dev isn't locked out.
- `POST /analyses` also enforces a **CPU budget** before running: it computes the
  rebalance count `ceil((observations − lookback − 1)/rebalance_every)` and
  rejects with `backtest_budget_exceeded` (422) beyond
  `max_backtest_rebalances` — the expensive walk-forward is never started.
- The stored `PriceSnapshot` is serialized with sorted keys + `allow_nan=False`
  and hashed; `snapshot_sha256` in `DataSummary` lets clients verify
  reproducibility (the test asserts a repeated request yields an identical hash).
- `GET /analyses/{id}` takes a `UUID` path param — FastAPI parses/rejects bad IDs
  (422) before the repository is touched, and string `result.id`s round-trip.
- `app.include_router(router)` mounts everything under `/api/v1` with shared
  error-response models documented in OpenAPI.

## `__init__.py`

Only `__version__ = "0.1.0"` — the single source for `FastAPI(version=...)`,
`/health`, `engine_version`, and the OpenAPI doc, kept in sync with
`pyproject.toml`.

## Running it

```bash
uv sync                      # or: pip install -e . into a venv
uvicorn portfolio_backend.main:app --reload   # serves on :8000, docs at /docs
pytest -q                    # 123 tests, all offline (fake provider)
ruff check .                 # lint (E, F, I, UP, B), line-length 100
```

`PORTFOLIO_API_KEY` must be set before exposing beyond localhost — without it,
all `/api/v1` routes are open.
