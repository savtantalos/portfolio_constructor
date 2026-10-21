import builtins
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from portfolio_backend.models import (
    AnalysisResponse,
    AnalysisSummary,
    ChatMessage,
    ConversationDetail,
    ConversationSummary,
)


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


class ConversationRecord(Base):
    """Map one assistant conversation, optionally linked to a saved analysis.

    The analysis link is informational: deleting analyses is unsupported, so no
    foreign key is declared and legacy or missing analyses do not break reads.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    analysis_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ConversationMessageRecord(Base):
    """Map one user or assistant turn stored as provider-shaped content blocks."""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


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

    def get_export_source(
        self, analysis_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        with Session(self.engine) as session:
            row = session.execute(
                select(AnalysisRecord.result, AnalysisRecord.price_snapshot).where(
                    AnalysisRecord.id == analysis_id
                )
            ).first()
            return (row[0], row[1]) if row is not None else None

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


def _utc(value: datetime) -> datetime:
    """Attach UTC to naive timestamps that SQLite returns without a zone."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ConversationRepository:
    """Persist assistant conversations and messages through a shared engine.

    The engine's owner is responsible for schema creation and disposal; this
    class only reads and writes. Like analyses, conversations are shared by all
    authorized callers and carry no owner field.
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _summary(record: ConversationRecord) -> ConversationSummary:
        return ConversationSummary(
            id=record.id,
            analysis_id=record.analysis_id,
            title=record.title,
            created_at=_utc(record.created_at),
            updated_at=_utc(record.updated_at),
        )

    def create(self, analysis_id: str | None) -> ConversationDetail:
        now = datetime.now(UTC)
        record = ConversationRecord(
            id=str(uuid4()), created_at=now, updated_at=now, analysis_id=analysis_id, title=None
        )
        with Session(self.engine) as session, session.begin():
            session.add(record)
            session.flush()
            summary = self._summary(record)
        return ConversationDetail(**summary.model_dump(), messages=[])

    def get(self, conversation_id: str) -> ConversationDetail | None:
        with Session(self.engine) as session:
            record = session.get(ConversationRecord, conversation_id)
            if record is None:
                return None
            rows = session.scalars(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == conversation_id)
                .order_by(ConversationMessageRecord.id)
            ).all()
            return ConversationDetail(
                **self._summary(record).model_dump(),
                messages=[
                    ChatMessage(
                        id=row.id, role=row.role, content=row.content,
                        created_at=_utc(row.created_at),
                    )
                    for row in rows
                ],
            )

    def list(self, analysis_id: str | None, limit: int) -> list[ConversationSummary]:
        statement = select(ConversationRecord)
        if analysis_id is not None:
            statement = statement.where(ConversationRecord.analysis_id == analysis_id)
        statement = statement.order_by(
            ConversationRecord.updated_at.desc(), ConversationRecord.id.desc()
        ).limit(limit)
        with Session(self.engine) as session:
            return [self._summary(record) for record in session.scalars(statement)]

    def append_messages(
        self, conversation_id: str, messages: "builtins.list[tuple[str, builtins.list[dict]]]"
    ) -> "builtins.list[int]":
        """Append (role, content) pairs in order, set a title from the first user message.

        Returns:
            The new message IDs in insertion order.

        Raises:
            LookupError: If the conversation does not exist.
        """
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            record = session.get(ConversationRecord, conversation_id)
            if record is None:
                raise LookupError(conversation_id)
            rows = [
                ConversationMessageRecord(
                    conversation_id=conversation_id, created_at=now, role=role, content=content
                )
                for role, content in messages
            ]
            session.add_all(rows)
            if record.title is None:
                for role, content in messages:
                    text = next(
                        (b.get("text", "") for b in content if b.get("type") == "text"), ""
                    )
                    if role == "user" and text.strip():
                        record.title = text.strip()[:117] + ("..." if len(text.strip()) > 117
                                                              else "")
                        break
            record.updated_at = now
            session.flush()
            return [row.id for row in rows]

    def link_analysis(self, conversation_id: str, analysis_id: str) -> bool:
        """Attach an analysis to a conversation that has none; return whether it changed."""
        with Session(self.engine) as session, session.begin():
            record = session.get(ConversationRecord, conversation_id)
            if record is None or record.analysis_id is not None:
                return False
            record.analysis_id = analysis_id
            return True
