from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, String, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from portfolio_backend.models import AnalysisResponse, AnalysisSummary


class Base(DeclarativeBase):
    """Own SQLAlchemy mappings and metadata for the analysis storage schema."""

    pass


class AnalysisRecord(Base):
    """Map one shared analysis, its summary columns, and its price snapshot.

    The UUID string is the primary key. Full responses and snapshots are stored
    as JSON alongside indexed creation times and request fields used for listing.
    Records contain no owner or tenant field.
    """

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    tickers: Mapped[list[str]] = mapped_column(JSON)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    price_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class AnalysisRepository:
    """Persist shared analyses through an engine and short-lived sessions.

    Call `initialize` before accessing records and `close` during shutdown.
    Each operation owns its session; writes are transactional. The repository
    performs no authorization, application-level locking, or concurrency limiting,
    and database and model-validation failures propagate to callers.
    """

    def __init__(self, database_url: str):
        """Configure an engine without creating tables or opening a session.

        Args:
            database_url: SQLAlchemy connection URL. Bare PostgreSQL schemes
                select psycopg; SQLite allows cross-thread connection use with
                a 30-second lock timeout. In-memory SQLite uses a shared
                `StaticPool` connection without adding access serialization.

        Notes:
            Connections are acquired lazily and checked with pool pre-ping.
            URL, dialect, and driver-loading errors propagate from SQLAlchemy.
        """
        url = make_url(database_url)
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.get_backend_name() == "sqlite":
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url.database in {None, "", ":memory:"}:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)

    def initialize(self) -> None:
        """Create missing mapped tables, without migrating existing schemas.

        Raises:
            SQLAlchemyError: If connection or schema creation fails.
        """
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        """Dispose the engine pool and release its idle connections at shutdown.

        This does not delete persisted tables or permanently disable the engine;
        a later operation can create new connections. Disposing the shared
        in-memory SQLite connection loses that connection's database.
        """
        self.engine.dispose()

    def save(self, response: AnalysisResponse, snapshot: dict[str, Any]) -> None:
        """Insert a response and price snapshot together in one transaction.

        Args:
            response: Analysis whose ID, timestamp, and request fields populate
                summary columns; the full model is serialized in JSON mode.
            snapshot: JSON-compatible price snapshot stored without validation.

        Raises:
            SQLAlchemyError: If insertion or commit fails, including duplicate
                IDs. The transaction rolls back on failure and the session closes.

        Notes:
            Successful exit commits both payloads; existing rows are not updated.
        """
        with Session(self.engine) as session, session.begin():
            session.add(
                AnalysisRecord(
                    id=response.id,
                    created_at=response.created_at,
                    tickers=response.request.tickers,
                    start_date=response.request.start_date,
                    end_date=response.request.end_date,
                    result=response.model_dump(mode="json"),
                    price_snapshot=snapshot,
                )
            )

    def get(self, analysis_id: str) -> AnalysisResponse | None:
        with Session(self.engine) as session:
            payload = session.scalar(
                select(AnalysisRecord.result).where(AnalysisRecord.id == analysis_id)
            )
            return AnalysisResponse.model_validate(payload) if payload is not None else None

    def get_prices(self, analysis_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(AnalysisRecord.price_snapshot).where(AnalysisRecord.id == analysis_id)
            )

    def list(self, limit: int, offset: int) -> list[AnalysisSummary]:
        statement = (
            select(
                AnalysisRecord.id,
                AnalysisRecord.created_at,
                AnalysisRecord.tickers,
                AnalysisRecord.start_date,
                AnalysisRecord.end_date,
            )
            .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        with Session(self.engine) as session:
            return [
                AnalysisSummary.model_validate(dict(row))
                for row in session.execute(statement).mappings()
            ]
