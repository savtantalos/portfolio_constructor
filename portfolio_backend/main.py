import secrets
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.exc import SQLAlchemyError

from portfolio_backend import __version__
from portfolio_backend.assistant import Assistant, LLMClient, build_llm_client
from portfolio_backend.config import Settings
from portfolio_backend.database import AnalysisRepository, ConversationRepository
from portfolio_backend.errors import PortfolioError
from portfolio_backend.exports import build_data, render_archive, render_csv
from portfolio_backend.market_data import YahooFinanceProvider
from portfolio_backend.market_types import MarketDataProvider
from portfolio_backend.models import (
    AnalysisData,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisSummary,
    AssistantStatus,
    ChatSendRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    ErrorResponse,
    HealthResponse,
    Instrument,
    PriceSnapshot,
)
from portfolio_backend.service import ASSUMPTIONS, perform_analysis

__all__ = ["ASSUMPTIONS", "app", "create_app"]


def create_app(
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    """Build the shared-workspace API and its application-scoped dependencies.

    Args:
        settings: Configuration to use; otherwise load default settings.
        provider: Market-data implementation; otherwise create a configured
            Yahoo Finance provider with an in-process cache.
        llm: Language-model client for the assistant; otherwise build an
            Anthropic client when an API key is configured, or disable it.

    Returns:
        An app with optional CORS and API-key protection on `/api/v1` routes.
        Health and framework documentation routes are not key-protected.

    Notes:
        Construction creates a database engine but schema initialization occurs
        at lifespan startup; shutdown disposes the engine. Analysis concurrency
        is bounded per app instance, not across worker processes. Stored analyses
        are shared by all authorized callers, with no per-user ownership checks.
        This module also constructs a default app at import time.
    """
    configuration = settings or Settings()
    repository = AnalysisRepository(configuration.database_url)
    market_data = provider or YahooFinanceProvider(
        cache_ttl_seconds=configuration.cache_ttl_seconds,
        cache_max_entries=configuration.cache_max_entries,
        timeout_seconds=configuration.provider_timeout_seconds,
    )
    slots = BoundedSemaphore(configuration.max_concurrent_analyses)
    conversations = ConversationRepository(repository.engine)
    llm_client = llm or build_llm_client(configuration)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize storage before serving and dispose it after serving ends.

        Args:
            app: Application supplied by FastAPI; not otherwise used.

        Yields:
            None while the application serves requests.

        Raises:
            SQLAlchemyError: If schema initialization or engine disposal fails.
                Initialization failure prevents entry into the cleanup block.
        """
        repository.initialize()
        try:
            yield
        finally:
            repository.close()

    app = FastAPI(
        title="Portfolio Construction API",
        version=__version__,
        description=(
            "Single-user research backend for daily equity/ETF portfolio analysis. "
            "Allocation estimates are in-sample; backtests are lagged and walk-forward. "
            "Set PORTFOLIO_API_KEY before exposing this service beyond localhost. "
            "This is a shared-workspace API, not a multi-tenant application."
        ),
        lifespan=lifespan,
    )
    if configuration.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=configuration.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key"],
        )

    @app.exception_handler(PortfolioError)
    async def handle_portfolio_error(request: Request, error: PortfolioError):
        """Expose a domain error using the API's structured error envelope.

        Args:
            request: Failed request supplied by FastAPI; not otherwise used.
            error: Domain failure carrying a public code, message, and status.

        Returns:
            A JSON response with the error's HTTP status, code, and message.
        """
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, error: SQLAlchemyError):
        """Translate request-time SQLAlchemy failures without exposing internals.

        Args:
            request: Failed request supplied by FastAPI; not otherwise used.
            error: Database failure; its details are intentionally not returned.

        Returns:
            A generic HTTP 503 JSON response with code `storage_unavailable`.
        """
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "storage_unavailable",
                    "message": "Analysis storage is unavailable. Please retry later.",
                }
            },
        )

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(api_key: Annotated[str | None, Depends(api_key_header)] = None) -> None:
        """Check the shared API key, or allow access when none is configured.

        Args:
            api_key: Optional `X-API-Key` header injected by FastAPI.

        Raises:
            PortfolioError: HTTP 401 if a configured key is missing or incorrect.

        Notes:
            Uses constant-time byte comparison and grants shared-workspace
            access, not a user identity or per-analysis authorization.
        """
        expected = configuration.api_key
        if expected is not None and not secrets.compare_digest(
            (api_key or "").encode(), expected.get_secret_value().encode()
        ):
            raise PortfolioError("unauthorized", "A valid X-API-Key header is required.", 401)

    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(authorize)],
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        """Return the service version without authentication or dependency probes."""
        return HealthResponse(version=__version__)

    @router.get("/assets/search", response_model=list[Instrument], tags=["assets"])
    def search_assets(
        q: Annotated[str, Query(min_length=1, max_length=100)],
        limit: Annotated[int, Query(ge=1, le=20)] = 10,
    ) -> list[Instrument]:
        """Search the market-data provider through the key-protected router.

        Args:
            q: Search text, stripped before forwarding; HTTP length is 1–100.
            limit: Maximum requested matches, constrained to 1–20 over HTTP.

        Returns:
            Instruments returned by the provider, which may use its cache.

        Raises:
            PortfolioError: If the query is blank or the provider reports a
                domain failure. Provider searches may perform network I/O.
        """
        if not q.strip():
            raise PortfolioError("invalid_search", "Search query cannot be blank.")
        return market_data.search(q.strip(), limit)

    def run_analysis(payload: AnalysisRequest) -> AnalysisResponse:
        """Run and persist an analysis inside one bounded per-app slot.

        Raises:
            PortfolioError: HTTP 503 if no analysis slot is immediately available.
        """
        if not slots.acquire(blocking=False):
            raise PortfolioError(
                "analysis_capacity_reached", "Analysis workers are busy. Retry later.", 503
            )
        try:
            return perform_analysis(
                payload, market_data=market_data, repository=repository, settings=configuration
            )
        finally:
            slots.release()

    @router.post("/analyses", response_model=AnalysisResponse, status_code=201, tags=["analyses"])
    def create_analysis(payload: AnalysisRequest, response: Response) -> AnalysisResponse:
        """Compute and persist an analysis and its auditable price snapshot.

        Args:
            payload: Validated assets, date window, allocation, and backtest
                settings used to fetch data and run the analysis.
            response: FastAPI response whose `Location` header is set after save.

        Returns:
            The saved analysis, including a UUID, UTC timestamp, data provenance,
            combined warnings, and SHA-256 hash of the canonical price snapshot.

        Raises:
            PortfolioError: HTTP 503 if no analysis slot is immediately available;
                also raised for excess rebalance budgets or data/analysis errors.
            SQLAlchemyError: If persistence fails; the app maps this to HTTP 503.

        Notes:
            Router authorization runs first. Provider access may perform network
            I/O or update caches. An acquired per-app slot covers fetching,
            computation, and transactional storage, and is released on every exit.
            Successful requests store both results and prices in shared storage.
        """
        result = run_analysis(payload)
        response.headers["Location"] = f"/api/v1/analyses/{result.id}"
        return result

    @router.get("/analyses", response_model=list[AnalysisSummary], tags=["analyses"])
    def list_analyses(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[AnalysisSummary]:
        """Read a page of shared analysis summaries after router authorization.

        Args:
            limit: Page size, constrained to 1–100 over HTTP.
            offset: Number of records to skip, nonnegative over HTTP.

        Returns:
            Summaries ordered by creation time, then ID, both descending.

        Raises:
            SQLAlchemyError: If storage access fails; mapped to HTTP 503.
        """
        return repository.list(limit, offset)

    @router.get("/analyses/{analysis_id}", response_model=AnalysisResponse, tags=["analyses"])
    def get_analysis(analysis_id: UUID) -> AnalysisResponse:
        """Read a saved shared-workspace result after router authorization.

        Args:
            analysis_id: UUID parsed by FastAPI and normalized for lookup.

        Returns:
            The stored analysis without fetching data or recomputing results.

        Raises:
            PortfolioError: HTTP 404 if no matching analysis exists.
            SQLAlchemyError: If storage access fails; mapped to HTTP 503.
        """
        result = repository.get(str(analysis_id))
        if result is None:
            raise PortfolioError("analysis_not_found", "Analysis not found.", 404)
        return result

    @router.get("/analyses/{analysis_id}/prices", response_model=PriceSnapshot, tags=["analyses"])
    def get_analysis_prices(analysis_id: UUID) -> dict:
        """Read stored analysis prices after shared-workspace authorization.

        Args:
            analysis_id: UUID parsed by FastAPI and normalized for lookup.

        Returns:
            The saved snapshot mapping of tickers, dates, and prices, serialized
            by FastAPI as a `PriceSnapshot`; no provider refresh is performed.

        Raises:
            PortfolioError: HTTP 404 if no matching snapshot is found.
            SQLAlchemyError: If storage access fails; mapped to HTTP 503.
        """
        result = repository.get_prices(str(analysis_id))
        if result is None:
            raise PortfolioError("analysis_not_found", "Analysis not found.", 404)
        return result

    def load_analysis_data(analysis_id: UUID) -> tuple[dict, dict, AnalysisData]:
        source = repository.get_export_source(str(analysis_id))
        if source is None:
            raise PortfolioError("analysis_not_found", "Analysis not found.", 404)
        stored_analysis, stored_prices = source
        data = build_data(
            AnalysisResponse.model_validate(stored_analysis),
            PriceSnapshot.model_validate(stored_prices),
        )
        return stored_analysis, stored_prices, data

    @router.get("/analyses/{analysis_id}/data", response_model=AnalysisData, tags=["analyses"])
    def get_analysis_data(analysis_id: UUID) -> AnalysisData:
        return load_analysis_data(analysis_id)[2]

    @router.get(
        "/analyses/{analysis_id}/export",
        response_class=Response,
        responses={200: {"content": {"application/zip": {"schema": {
            "type": "string", "format": "binary"
        }}}}},
        tags=["analyses"],
    )
    def export_analysis(analysis_id: UUID) -> Response:
        stored_analysis, stored_prices, data = load_analysis_data(analysis_id)
        return Response(
            content=render_archive(stored_analysis, stored_prices, data),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="analysis-{analysis_id}.zip"'
            },
        )

    @router.get(
        "/analyses/{analysis_id}/export/{dataset_id}",
        response_class=Response,
        responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
        tags=["analyses"],
    )
    def export_analysis_dataset(analysis_id: UUID, dataset_id: str) -> Response:
        data = load_analysis_data(analysis_id)[2]
        dataset = next((item for item in data.datasets if item.id == dataset_id), None)
        if dataset is None:
            raise PortfolioError("dataset_not_found", "Dataset not found.", 404)
        return Response(
            content=render_csv(dataset),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="analysis-{analysis_id}-{dataset.id}.csv"'
                )
            },
        )

    assistant = Assistant(
        settings=configuration,
        llm=llm_client,
        repository=repository,
        conversations=conversations,
        market_data=market_data,
        run_analysis=run_analysis,
    )

    @router.get("/assistant/status", response_model=AssistantStatus, tags=["assistant"])
    def assistant_status() -> AssistantStatus:
        """Report whether the assistant is configured, without probing the provider."""
        return AssistantStatus(enabled=assistant.enabled, model=configuration.assistant_model)

    @router.post(
        "/conversations", response_model=ConversationDetail, status_code=201, tags=["assistant"]
    )
    def create_conversation(payload: ConversationCreate) -> ConversationDetail:
        """Start an empty conversation, optionally attached to a saved analysis.

        Raises:
            PortfolioError: HTTP 404 if the referenced analysis does not exist.
        """
        if payload.analysis_id and repository.get(payload.analysis_id) is None:
            raise PortfolioError("analysis_not_found", "Analysis not found.", 404)
        return conversations.create(payload.analysis_id)

    @router.get("/conversations", response_model=list[ConversationSummary], tags=["assistant"])
    def list_conversations(
        analysis_id: Annotated[UUID | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> list[ConversationSummary]:
        """List recent conversations, optionally filtered to one analysis."""
        return conversations.list(str(analysis_id) if analysis_id else None, limit)

    @router.get(
        "/conversations/{conversation_id}", response_model=ConversationDetail, tags=["assistant"]
    )
    def get_conversation(conversation_id: UUID) -> ConversationDetail:
        """Read one conversation and its stored messages.

        Raises:
            PortfolioError: HTTP 404 if no matching conversation exists.
        """
        result = conversations.get(str(conversation_id))
        if result is None:
            raise PortfolioError("conversation_not_found", "Conversation not found.", 404)
        return result

    @router.post(
        "/conversations/{conversation_id}/messages",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
        tags=["assistant"],
    )
    def send_message(conversation_id: UUID, payload: ChatSendRequest) -> StreamingResponse:
        """Stream the assistant's reply to a new user message as server-sent events.

        Raises:
            PortfolioError: HTTP 404 if the conversation is missing; HTTP 503 if
                the assistant is disabled or all assistant turns are busy.
        """
        events = assistant.start_turn(str(conversation_id), payload)
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)
    return app


app = create_app()
