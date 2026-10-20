import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from portfolio_backend.assistant import FinalMessage, TextDelta, replayable_history
from portfolio_backend.assistant_context import load_knowledge, summarize_analysis
from portfolio_backend.config import Settings
from portfolio_backend.main import create_app
from portfolio_backend.market_types import MarketDataset
from portfolio_backend.models import AnalysisResponse, Instrument

NIL_UUID = "00000000-0000-0000-0000-000000000000"


class FakeProvider:
    """Deterministic synthetic prices and a fixed search result."""

    def search(self, query, limit=10):
        return [Instrument(symbol="AAA", name=f"Match for {query}", currency="USD")][:limit]

    def history(self, tickers, start, end, base_currency):
        rng = np.random.default_rng(11)
        dates = pd.bdate_range(start, end)
        returns = rng.normal(0.0006, 0.009, (len(dates), len(tickers)))
        prices = pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), dates, tickers)
        return MarketDataset(
            prices=prices,
            instruments=[Instrument(symbol=t, currency=base_currency) for t in tickers],
            fetched_at=datetime.now(UTC),
            warnings=["Synthetic test data"],
            provider="test",
        )


def text(content):
    return FinalMessage(content=[{"type": "text", "text": content}], stop_reason="end_turn")


def tool_call(name, arguments, call_id="toolu_1", preface=None):
    content = ([{"type": "text", "text": preface}] if preface else []) + [
        {"type": "tool_use", "id": call_id, "name": name, "input": arguments}
    ]
    return FinalMessage(content=content, stop_reason="tool_use")


class FakeLLM:
    """Replay scripted responses and record every request for assertions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def stream(self, *, system, messages, tools, tool_choice, max_tokens):
        self.calls.append({
            "system": system, "messages": list(messages), "tools": tools,
            "tool_choice": tool_choice, "max_tokens": max_tokens,
        })
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        final = self.script.pop(0)
        if isinstance(final, Exception):
            raise final
        for block in final.content:
            if block["type"] == "text" and block["text"]:
                yield TextDelta(block["text"][:3])
                yield TextDelta(block["text"][3:])
        yield final


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        _env_file=None,
        anthropic_api_key="test-key",
        assistant_max_tool_rounds=2,
        assistant_max_analyses_per_turn=1,
        assistant_history_messages=6,
    )


@pytest.fixture
def payload():
    return {
        "tickers": ["AAA", "BBB", "CCC"],
        "start_date": "2022-01-01",
        "end_date": "2023-06-30",
        "monte_carlo_samples": 20,
        "frontier_points": 5,
        "backtest": {"lookback_days": 126, "rebalance_every": 63},
    }


def make_client(settings, script):
    llm = FakeLLM(script)
    client = TestClient(create_app(settings=settings, provider=FakeProvider(), llm=llm))
    return client, llm


def events_from(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(line[len("data: "):])
        for line in response.text.split("\n") if line.startswith("data: ")
    ]


def test_status_and_disabled_when_no_key(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", _env_file=None)
    with TestClient(create_app(settings=settings, provider=FakeProvider())) as client:
        assert client.get("/api/v1/assistant/status").json() == {
            "enabled": False, "model": "claude-sonnet-5"
        }
        conversation = client.post("/api/v1/conversations", json={}).json()
        response = client.post(
            f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "hi"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "assistant_disabled"


def test_conversation_crud_and_validation(settings):
    client, _ = make_client(settings, [])
    with client:
        assert client.get("/api/v1/assistant/status").json()["enabled"] is True
        missing = client.post("/api/v1/conversations", json={"analysis_id": "0" * 36})
        assert missing.status_code == 404
        created = client.post("/api/v1/conversations", json={})
        assert created.status_code == 201
        body = created.json()
        assert body["analysis_id"] is None and body["messages"] == [] and body["title"] is None
        assert client.get(f"/api/v1/conversations/{body['id']}").json()["id"] == body["id"]
        assert client.get("/api/v1/conversations").json()[0]["id"] == body["id"]
        assert client.get(f"/api/v1/conversations/{NIL_UUID}").status_code == 404
        blank = client.post(f"/api/v1/conversations/{body['id']}/messages", json={"content": "  "})
        assert blank.status_code == 422
        unknown = client.post(
            f"/api/v1/conversations/{NIL_UUID}/messages", json={"content": "hi"}
        )
        assert unknown.status_code == 404


def test_plain_reply_streams_and_persists(settings):
    client, llm = make_client(settings, [text("Sharpe is excess return per unit of volatility.")])
    with client:
        conversation = client.post("/api/v1/conversations", json={}).json()
        events = events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": "What is Sharpe?", "context": {"path": "/"}},
        ))
        types = [e["type"] for e in events]
        assert types[0] == "start" and types[-1] == "message_end"
        assert "".join(e["text"] for e in events if e["type"] == "text_delta") == (
            "Sharpe is excess return per unit of volatility."
        )
        stored = client.get(f"/api/v1/conversations/{conversation['id']}").json()
        assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
        assert stored["title"] == "What is Sharpe?"
        assert events[-1]["message_ids"] == [m["id"] for m in stored["messages"]]
    call = llm.calls[0]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Methodology brief" in call["system"][0]["text"]
    assert "No analysis is open" in call["system"][1]["text"]
    assert "/" in call["system"][1]["text"]
    assert call["tool_choice"] is None
    assert {t["name"] for t in call["tools"]} == {
        "get_analysis", "get_analysis_dataset", "list_analyses", "search_assets", "run_analysis"
    }
    assert call["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "What is Sharpe?"}]}
    ]


def test_open_analysis_context_is_injected_into_system_prompt(settings, payload):
    client, llm = make_client(settings, [text("ok")])
    with client:
        analysis = client.post("/api/v1/analyses", json=payload).json()
        conversation = client.post(
            "/api/v1/conversations", json={"analysis_id": analysis["id"]}
        ).json()
        events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": "Explain", "context": {"analysis_id": analysis["id"]}},
        ))
    context = llm.calls[0]["system"][1]["text"]
    assert f"viewing analysis {analysis['id']}" in context
    weight = analysis["results"]["portfolios"][0]["weights"]["AAA"]
    assert json.dumps(round(weight, 6)) in context


def test_tool_loop_runs_analysis_and_links_conversation(settings, payload):
    script = [
        tool_call("search_assets", {"query": "example"}, "toolu_a", preface="Looking up."),
        tool_call("run_analysis", {"request": payload}, "toolu_b"),
        text("Done. See the link."),
    ]
    client, llm = make_client(settings, script)
    with client:
        conversation = client.post("/api/v1/conversations", json={}).json()
        events = events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": "Run AAA/BBB/CCC"},
        ))
        calls = [e for e in events if e["type"] == "tool_call"]
        results = [e for e in events if e["type"] == "tool_result"]
        assert [c["name"] for c in calls] == ["search_assets", "run_analysis"]
        assert all(r["ok"] for r in results)
        assert results[0]["summary"] == {"query": "example", "count": 1}
        analysis_id = results[1]["summary"]["analysis_id"]
        assert results[1]["summary"]["link"] == f"/analysis/{analysis_id}"
        assert {"type": "conversation_linked", "analysis_id": analysis_id} in events
        assert events[-1]["type"] == "message_end"

        saved = client.get(f"/api/v1/analyses/{analysis_id}")
        assert saved.status_code == 200
        assert saved.json()["request"]["tickers"] == ["AAA", "BBB", "CCC"]
        stored = client.get(f"/api/v1/conversations/{conversation['id']}").json()
        assert stored["analysis_id"] == analysis_id
        roles = [m["role"] for m in stored["messages"]]
        assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]
        assert stored["messages"][2]["content"][0]["type"] == "tool_result"
        assert stored["messages"][2]["content"][0]["tool_use_id"] == "toolu_a"
        listed = client.get("/api/v1/conversations", params={"analysis_id": analysis_id}).json()
        assert [c["id"] for c in listed] == [conversation["id"]]

    second_round = llm.calls[1]["messages"]
    assert second_round[-1]["role"] == "user"
    tool_result = second_round[-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "is_error" not in tool_result
    assert json.loads(tool_result["content"])[0]["symbol"] == "AAA"
    run_result = json.loads(llm.calls[2]["messages"][-1]["content"][0]["content"])
    assert run_result["analysis_id"] == analysis_id
    assert {p["strategy"] for p in run_result["in_sample_portfolios"]} == {
        "equal_weight", "minimum_variance", "maximum_sharpe"
    }


def test_invalid_tool_input_returns_error_result_not_500(settings, payload):
    bad = {**payload, "tickers": ["AAA"]}
    script = [
        tool_call("run_analysis", {"request": bad}, "toolu_bad"),
        tool_call("get_analysis", {"analysis_id": "0" * 36}, "toolu_missing"),
        text("Could not run."),
    ]
    client, llm = make_client(settings, script)
    with client:
        conversation = client.post("/api/v1/conversations", json={}).json()
        events = events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "run"}
        ))
        results = [e for e in events if e["type"] == "tool_result"]
        assert [r["ok"] for r in results] == [False, False]
        assert results[0]["summary"]["message"] == "Invalid request parameters"
        assert client.get("/api/v1/analyses").json() == []
    first_result = llm.calls[1]["messages"][-1]["content"][0]
    assert first_result["is_error"] is True
    assert "tickers" in first_result["content"]
    assert llm.calls[2]["messages"][-1]["content"][0]["content"] == "Analysis not found."


def test_round_and_analysis_budgets_are_enforced(settings, payload):
    script = [
        tool_call("run_analysis", {"request": payload}, "toolu_1"),
        tool_call("run_analysis", {"request": payload}, "toolu_2"),
        tool_call("list_analyses", {}, "toolu_3"),
        text("Final answer without tools."),
    ]
    client, llm = make_client(settings, script)
    with client:
        conversation = client.post("/api/v1/conversations", json={}).json()
        events = events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "go"}
        ))
        results = [e for e in events if e["type"] == "tool_result"]
        assert [r["ok"] for r in results] == [True, False, False]
        assert "budget" in results[1]["summary"]["message"].lower()
        assert "limit" in results[2]["summary"]["message"].lower()
        assert len(client.get("/api/v1/analyses").json()) == 1
        assert events[-1]["type"] == "message_end"
        stored = client.get(f"/api/v1/conversations/{conversation['id']}").json()
        assert stored["messages"][-1]["content"][0]["type"] == "tool_result"
    assert len(llm.calls) == 3
    assert llm.calls[2]["tool_choice"] == {"type": "none"}
    assert llm.script == [text("Final answer without tools.")]


def test_provider_failure_yields_error_event_and_keeps_history_replayable(settings):
    client, _ = make_client(settings, [RuntimeError("boom"), text("Recovered.")])
    with client:
        conversation = client.post("/api/v1/conversations", json={}).json()
        events = events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "hello"}
        ))
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == "assistant_error"
        assert "boom" not in json.dumps(events)
        again = events_from(client.post(
            f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "retry"}
        ))
        assert again[-1]["type"] == "message_end"
        stored = client.get(f"/api/v1/conversations/{conversation['id']}").json()
        assert [m["role"] for m in stored["messages"]] == ["user", "user", "assistant"]


def test_busy_assistant_returns_503(settings):
    client, _ = make_client(settings, [text("ok")])
    with client:
        conversation = client.post("/api/v1/conversations", json={}).json()
        app = client.app
        assistant_semaphore = None
        for route in app.routes:
            closure = getattr(route.endpoint, "__closure__", None) or ()
            for cell in closure:
                if cell.cell_contents.__class__.__name__ == "Assistant":
                    assistant_semaphore = cell.cell_contents._turns
        assert assistant_semaphore is not None
        for _ in range(settings.assistant_max_concurrent_turns):
            assert assistant_semaphore.acquire(blocking=False)
        try:
            response = client.post(
                f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "hi"}
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "assistant_busy"
        finally:
            for _ in range(settings.assistant_max_concurrent_turns):
                assistant_semaphore.release()


def test_replayable_history_trims_and_repairs():
    user = {"role": "user", "content": [{"type": "text", "text": "q"}]}
    assistant_tool = {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t", "name": "list_analyses", "input": {}}
    ]}
    result = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "[]"}
    ]}
    answer = {"role": "assistant", "content": [{"type": "text", "text": "a"}]}
    full = [user, assistant_tool, result, answer, user, assistant_tool]
    assert replayable_history(full, 10) == [user, assistant_tool, result, answer, user]
    assert replayable_history(full, 4) == [user]
    assert replayable_history([assistant_tool, result], 10) == []
    assert replayable_history([], 10) == []


def test_summary_is_bounded_for_large_baskets(settings, payload):
    client, _ = make_client(settings, [])
    with client:
        wide = {**payload, "tickers": [f"T{i:02d}" for i in range(30)], "scenario": {
            "enabled": True, "paths": 100, "horizon_days": 21
        }}
        analysis = AnalysisResponse.model_validate(
            client.post("/api/v1/analyses", json=wide).json()
        )
    summary = summarize_analysis(analysis)
    assert isinstance(summary["correlation"], str)
    assert summary["scenarios"] and "fan_paths" not in json.dumps(summary)
    assert "equity_curve" not in json.dumps(summary)
    assert summary["backtests"][0]["rebalance_count"] >= 1
    assert len(json.dumps(summary)) < 40_000
    assert summary["estimation"] == "persisted optimizer moments available"


def test_knowledge_brief_loads_from_package():
    knowledge = load_knowledge()
    assert "walk-forward" in knowledge.lower()
    assert "Engine method definitions" in knowledge
    assert "Research tool, not an investment recommendation" in knowledge
