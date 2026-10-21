"""Tool-using research assistant: provider adapter, tools, and the streaming turn loop."""

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from threading import BoundedSemaphore
from typing import Any, Protocol

from pydantic import ValidationError

from portfolio_backend.assistant_context import (
    SYSTEM_PROMPT,
    load_knowledge,
    summarize_analysis,
    summarize_listing,
)
from portfolio_backend.config import Settings
from portfolio_backend.database import AnalysisRepository, ConversationRepository
from portfolio_backend.errors import PortfolioError
from portfolio_backend.exports import build_data
from portfolio_backend.market_types import MarketDataProvider
from portfolio_backend.models import (
    AnalysisRequest,
    AnalysisResponse,
    ChatSendRequest,
    ConversationDetail,
    PriceSnapshot,
)

logger = logging.getLogger(__name__)

MAX_DATASET_ROWS = 60


@dataclass
class TextDelta:
    """A streamed fragment of assistant text."""

    text: str


@dataclass
class FinalMessage:
    """The completed assistant message as provider-shaped content blocks."""

    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: dict[str, int] = field(default_factory=dict)


LLMEvent = TextDelta | FinalMessage


class LLMClient(Protocol):
    """Minimal streaming chat interface so tests can script the model."""

    def stream(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None,
        max_tokens: int,
    ) -> Iterator[LLMEvent]: ...


class AnthropicLLM:
    """Stream Claude Messages API responses with the official SDK."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=2)
        self._model = model

    def stream(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None,
        max_tokens: int,
    ) -> Iterator[LLMEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        with self._client.messages.stream(**params) as stream:
            for text in stream.text_stream:
                yield TextDelta(text)
            final = stream.get_final_message()
        content = []
        for block in final.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        yield FinalMessage(
            content=content,
            stop_reason=final.stop_reason,
            usage={
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            },
        )


def build_llm_client(settings: Settings) -> LLMClient | None:
    """Create the Anthropic client when a non-empty key is configured; otherwise None."""
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if not key.strip():
        return None
    return AnthropicLLM(key, settings.assistant_model, settings.assistant_timeout_seconds)


def _request_schema() -> dict[str, Any]:
    schema = AnalysisRequest.model_json_schema()
    definitions = schema.pop("$defs", {})
    schema.pop("title", None)
    return {
        "type": "object",
        "properties": {"request": schema},
        "required": ["request"],
        "$defs": definitions,
    }


def tool_definitions() -> list[dict[str, Any]]:
    """Describe the assistant's tools in the Messages API format."""
    return [
        {
            "name": "get_analysis",
            "description": (
                "Read a compact summary of a saved analysis: request parameters, data window, "
                "in-sample weights and metrics per strategy, backtest metrics, benchmark, "
                "scenario statistics, correlation (small baskets), and warnings."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"analysis_id": {"type": "string", "description": "Analysis UUID."}},
                "required": ["analysis_id"],
            },
        },
        {
            "name": "get_analysis_dataset",
            "description": (
                "Read rows of one exported dataset of a saved analysis. Dataset ids: "
                "adjusted_prices, daily_returns, asset_estimates, sample_covariance, "
                "optimizer_covariance, correlation, strategy_weights, strategy_metrics, "
                "risk_contributions, efficient_frontier, monte_carlo, backtest_metrics, "
                "backtest_equity, backtest_rebalances, scenario_summary, scenario_percentiles, "
                "scenario_fan, benchmark_prices, benchmark_metrics, benchmark_equity, "
                "benchmark_trades. Rows are capped; use offset to page."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "analysis_id": {"type": "string"},
                    "dataset_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "max_rows": {
                        "type": "integer", "minimum": 1, "maximum": MAX_DATASET_ROWS,
                        "default": MAX_DATASET_ROWS,
                    },
                },
                "required": ["analysis_id", "dataset_id"],
            },
        },
        {
            "name": "list_analyses",
            "description": "List the most recent saved analyses with tickers and date windows.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
                },
            },
        },
        {
            "name": "search_assets",
            "description": (
                "Search the market-data provider for instruments by name or symbol. Returns "
                "symbols, names, exchanges, and currencies. Use it to resolve tickers."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 100},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                },
                "required": ["query"],
            },
        },
        {
            "name": "run_analysis",
            "description": (
                "Fetch market data, run every selected strategy, backtest, optionally simulate "
                "scenarios, and save the analysis. Returns the saved analysis summary including "
                "its id and link. Only call this after the parameters are clear to the user."
            ),
            "input_schema": _request_schema(),
        },
    ]


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def replayable_history(
    messages: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Trim stored messages to a valid provider transcript.

    Keeps the most recent `limit` messages, drops leading messages until the
    transcript starts with a plain user message, and drops a trailing assistant
    message whose tool calls never received results.
    """
    history = list(messages[-limit:])
    while history:
        first = history[0]
        has_tool_result = any(b.get("type") == "tool_result" for b in first["content"])
        if first["role"] == "user" and not has_tool_result:
            break
        history.pop(0)
    if history and history[-1]["role"] == "assistant" and any(
        b.get("type") == "tool_use" for b in history[-1]["content"]
    ):
        history.pop()
    return history


class ToolExecutor:
    """Run assistant tools against the repository, provider, and analysis pipeline."""

    def __init__(
        self,
        *,
        repository: AnalysisRepository,
        market_data: MarketDataProvider,
        run_analysis: Callable[[AnalysisRequest], AnalysisResponse],
        max_analyses: int,
    ):
        self._repository = repository
        self._market_data = market_data
        self._run_analysis = run_analysis
        self._max_analyses = max_analyses
        self.analyses_run = 0
        self.created: list[AnalysisResponse] = []

    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[bool, Any, dict[str, Any]]:
        """Return (ok, model_payload, public_summary) and never raise."""
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return False, f"Unknown tool: {name}", {"message": "Unknown tool"}
            return handler(**arguments)
        except PortfolioError as error:
            return False, f"{error.code}: {error.message}", {"message": error.message}
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(p) for p in item['loc'])}: {item['msg']}" for item in error.errors()
            )
            return False, f"Invalid request: {details}", {"message": "Invalid request parameters"}
        except TypeError as error:
            return False, f"Invalid tool arguments: {error}", {"message": "Invalid tool arguments"}
        except Exception:
            logger.exception("Assistant tool %s failed", name)
            return False, "The tool failed unexpectedly.", {"message": "Tool failed"}

    def _tool_get_analysis(self, analysis_id: str) -> tuple[bool, Any, dict[str, Any]]:
        analysis = self._repository.get(str(analysis_id))
        if analysis is None:
            return False, "Analysis not found.", {"message": "Analysis not found"}
        return True, summarize_analysis(analysis), {"analysis_id": analysis.id}

    def _tool_get_analysis_dataset(
        self, analysis_id: str, dataset_id: str, offset: int = 0, max_rows: int = MAX_DATASET_ROWS
    ) -> tuple[bool, Any, dict[str, Any]]:
        source = self._repository.get_export_source(str(analysis_id))
        if source is None:
            return False, "Analysis not found.", {"message": "Analysis not found"}
        stored_analysis, stored_prices = source
        data = build_data(
            AnalysisResponse.model_validate(stored_analysis),
            PriceSnapshot.model_validate(stored_prices),
        )
        dataset = next((item for item in data.datasets if item.id == dataset_id), None)
        if dataset is None:
            available = ", ".join(item.id for item in data.datasets)
            return False, f"Dataset not found. Available: {available}", {
                "message": "Dataset not found"
            }
        offset = max(0, int(offset))
        max_rows = max(1, min(int(max_rows), MAX_DATASET_ROWS))
        rows = dataset.rows[offset:offset + max_rows]
        payload = {
            "dataset_id": dataset.id,
            "title": dataset.title,
            "description": dataset.description,
            "columns": dataset.columns,
            "total_rows": len(dataset.rows),
            "offset": offset,
            "rows": rows,
        }
        return True, payload, {"dataset_id": dataset.id, "rows": len(rows)}

    def _tool_list_analyses(self, limit: int = 10) -> tuple[bool, Any, dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        items = self._repository.list(limit, 0)
        return True, summarize_listing(items), {"count": len(items)}

    def _tool_search_assets(self, query: str, limit: int = 8) -> tuple[bool, Any, dict[str, Any]]:
        query = str(query).strip()
        if not query:
            return False, "Search query cannot be blank.", {"message": "Blank query"}
        limit = max(1, min(int(limit), 20))
        instruments = self._market_data.search(query[:100], limit)
        summary = {"query": query, "count": len(instruments)}
        return True, [i.model_dump() for i in instruments], summary

    def _tool_run_analysis(self, request: dict[str, Any]) -> tuple[bool, Any, dict[str, Any]]:
        if self.analyses_run >= self._max_analyses:
            return False, (
                "The per-message analysis budget is used up. Ask the user to send a new message "
                "to run more analyses."
            ), {"message": "Analysis budget for this message reached"}
        self.analyses_run += 1
        payload = AnalysisRequest.model_validate(request)
        analysis = self._run_analysis(payload)
        self.created.append(analysis)
        return True, summarize_analysis(analysis), {
            "analysis_id": analysis.id,
            "link": f"/analysis/{analysis.id}",
            "tickers": analysis.request.tickers,
        }


class Assistant:
    """Own the system prompt, concurrency, persistence, and the tool loop."""

    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient | None,
        repository: AnalysisRepository,
        conversations: ConversationRepository,
        market_data: MarketDataProvider,
        run_analysis: Callable[[AnalysisRequest], AnalysisResponse],
    ):
        self._settings = settings
        self._llm = llm
        self._repository = repository
        self._conversations = conversations
        self._market_data = market_data
        self._run_analysis = run_analysis
        self._turns = BoundedSemaphore(settings.assistant_max_concurrent_turns)
        self._tools = tool_definitions()
        self._static_system = {
            "type": "text",
            "text": f"{SYSTEM_PROMPT}\n\n# Methodology brief\n\n{load_knowledge()}",
            "cache_control": {"type": "ephemeral"},
        }

    @property
    def enabled(self) -> bool:
        return self._llm is not None

    def start_turn(self, conversation_id: str, payload: ChatSendRequest) -> Iterator[str]:
        """Validate, reserve a turn slot, and return the SSE generator.

        Raises:
            PortfolioError: HTTP 503 if disabled or busy; HTTP 404 if the
                conversation does not exist.
        """
        if self._llm is None:
            raise PortfolioError(
                "assistant_disabled", "The research assistant is not configured.", 503
            )
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise PortfolioError("conversation_not_found", "Conversation not found.", 404)
        if not self._turns.acquire(blocking=False):
            raise PortfolioError(
                "assistant_busy", "The assistant is busy. Please retry shortly.", 503
            )
        return self._run(conversation, payload)

    def _system(self, conversation: ConversationDetail, payload: ChatSendRequest) -> list[dict]:
        context_id = payload.context.analysis_id or conversation.analysis_id
        lines = []
        if payload.context.path:
            lines.append(f"The user is currently on the page `{payload.context.path}`.")
        if context_id:
            analysis = self._repository.get(context_id)
            if analysis is not None:
                lines.append(
                    f"The user is currently viewing analysis {context_id}. Its summary follows; "
                    "use it directly instead of calling get_analysis for this id.\n"
                    + _dump(summarize_analysis(analysis))
                )
            else:
                lines.append(f"Analysis {context_id} referenced by the UI could not be loaded.")
        else:
            lines.append(
                "No analysis is open. Use list_analyses to find saved runs or help the user "
                "configure a new one."
            )
        return [self._static_system, _text_block("# Current context\n\n" + "\n\n".join(lines))]

    def _run(self, conversation: ConversationDetail, payload: ChatSendRequest) -> Iterator[str]:
        assert self._llm is not None
        settings = self._settings
        try:
            user_content = [_text_block(payload.content)]
            (user_id,) = self._conversations.append_messages(
                conversation.id, [("user", user_content)]
            )
            yield _sse({"type": "start", "conversation_id": conversation.id,
                        "user_message_id": user_id})
            history = replayable_history(
                [{"role": m.role, "content": m.content} for m in conversation.messages],
                settings.assistant_history_messages - 1,
            )
            messages = [*history, {"role": "user", "content": user_content}]
            system = self._system(conversation, payload)
            executor = ToolExecutor(
                repository=self._repository,
                market_data=self._market_data,
                run_analysis=self._run_analysis,
                max_analyses=settings.assistant_max_analyses_per_turn,
            )
            message_ids: list[int] = [user_id]
            rounds = 0
            while True:
                final_round = rounds >= settings.assistant_max_tool_rounds
                final: FinalMessage | None = None
                for event in self._llm.stream(
                    system=system,
                    messages=messages,
                    tools=self._tools,
                    tool_choice={"type": "none"} if final_round else None,
                    max_tokens=settings.assistant_max_output_tokens,
                ):
                    if isinstance(event, TextDelta):
                        if event.text:
                            yield _sse({"type": "text_delta", "text": event.text})
                    else:
                        final = event
                if final is None:
                    raise RuntimeError("The model stream ended without a final message")
                assistant_content = final.content or [_text_block("")]
                messages.append({"role": "assistant", "content": assistant_content})
                tool_uses = [b for b in assistant_content if b.get("type") == "tool_use"]
                if final.stop_reason != "tool_use" or not tool_uses:
                    message_ids += self._conversations.append_messages(
                        conversation.id, [("assistant", assistant_content)]
                    )
                    break
                results = []
                for block in tool_uses:
                    yield _sse({"type": "tool_call", "id": block["id"], "name": block["name"],
                                "input": block.get("input", {})})
                    if final_round:
                        ok, model_payload, summary = False, (
                            "Tool round limit reached for this message; answer with the "
                            "information already gathered."
                        ), {"message": "Tool round limit reached"}
                    else:
                        ok, model_payload, summary = executor.execute(
                            block["name"], dict(block.get("input") or {})
                        )
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": model_payload if isinstance(model_payload, str)
                        else _dump(model_payload),
                        **({} if ok else {"is_error": True}),
                    })
                    yield _sse({"type": "tool_result", "id": block["id"], "name": block["name"],
                                "ok": ok, "summary": summary})
                messages.append({"role": "user", "content": results})
                message_ids += self._conversations.append_messages(
                    conversation.id, [("assistant", assistant_content), ("user", results)]
                )
                for created in executor.created:
                    if self._conversations.link_analysis(conversation.id, created.id):
                        yield _sse({"type": "conversation_linked", "analysis_id": created.id})
                executor.created.clear()
                if final_round:
                    break
                rounds += 1
            yield _sse({"type": "message_end", "message_ids": message_ids})
        except Exception:
            logger.exception("Assistant turn failed for conversation %s", conversation.id)
            yield _sse({
                "type": "error",
                "code": "assistant_error",
                "message": "The assistant could not complete this reply. Please try again.",
            })
        finally:
            self._turns.release()
