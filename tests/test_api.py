from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from portfolio_backend.config import Settings
from portfolio_backend.errors import PortfolioError
from portfolio_backend.main import create_app
from portfolio_backend.market_types import MarketDataset
from portfolio_backend.models import Instrument


class FakeProvider:
    """Supply deterministic test prices, a fixed search result, and injectable history failures."""

    def __init__(self):
        """Start with no history calls and no configured failure."""
        self.calls = 0
        self.error = None

    def search(self, query, limit=10):
        """Return the fixed example instrument, sliced to the limit regardless of query."""
        return [Instrument(symbol="AAA", name="Example company", currency="USD")][:limit]

    def history(self, tickers, start, end, base_currency):
        """Count the call, then raise a configured error or return seeded business-day prices."""
        self.calls += 1
        if self.error:
            raise self.error
        rng = np.random.default_rng(7)
        dates = pd.bdate_range(start, end)
        returns = rng.normal(0.0008, 0.008, (len(dates), len(tickers)))
        prices = pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), dates, tickers)
        return MarketDataset(
            prices=prices,
            instruments=[Instrument(symbol=ticker, currency=base_currency) for ticker in tickers],
            fetched_at=datetime.now(UTC),
            warnings=["Synthetic test data"],
            provider="test",
        )


@pytest.fixture
def provider():
    """Provide a fresh fake market-data provider for each test."""
    return FakeProvider()


@pytest.fixture
def settings(tmp_path):
    """Use a temporary SQLite database without loading a dotenv file."""
    return Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", _env_file=None)


@pytest.fixture
def client(settings, provider):
    """Yield an app client with isolated settings, fake data, and managed lifespan."""
    with TestClient(create_app(settings=settings, provider=provider)) as client:
        yield client


@pytest.fixture
def payload():
    """Provide a three-asset analysis request exercising ticker normalization and backtesting."""
    return {
        "tickers": [" aaa ", "BBB", "CCC"],
        "start_date": "2022-01-01",
        "end_date": "2023-12-31",
        "monte_carlo_samples": 20,
        "frontier_points": 5,
        "max_weight": 0.6,
        "backtest": {"lookback_days": 126, "rebalance_every": 63},
    }


def test_health_and_openapi(client):
    """Health reports the expected version, and schema and interactive docs expose the API."""
    assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}
    schema = client.get("/openapi.json").json()
    assert "/api/v1/analyses" in schema["paths"]
    assert client.get("/docs").status_code == 200


def test_asset_search(client):
    """Asset search returns provider results and rejects whitespace-only queries."""
    response = client.get("/api/v1/assets/search", params={"q": "Example", "limit": 1})
    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "AAA"
    assert client.get("/api/v1/assets/search", params={"q": " "}).status_code == 422


def test_analysis_roundtrip_and_reproducibility(client, payload, provider):
    """Analyses persist normalized requests and snapshots, reproduce results,
    and paginate newest first.
    """
    response = client.post("/api/v1/analyses", json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["request"]["tickers"] == ["AAA", "BBB", "CCC"]
    assert result["data"]["provider"] == "test"
    assert result["data"]["return_observations"] == result["data"]["price_observations"] - 1
    assert len(result["data"]["snapshot_sha256"]) == 64
    assert "Synthetic test data" in result["results"]["warnings"]
    assert len(result["results"]["portfolios"]) == 3
    assert len(result["results"]["monte_carlo"]) == 20
    assert result["results"]["backtests"]
    assert client.get(f"/api/v1/analyses/{result['id']}").json() == result
    snapshot = client.get(f"/api/v1/analyses/{result['id']}/prices").json()
    assert snapshot["tickers"] == ["AAA", "BBB", "CCC"]
    assert len(snapshot["dates"]) == result["data"]["price_observations"]
    assert len(snapshot["prices"][0]) == 3
    assert provider.calls == 1
    repeat = client.post("/api/v1/analyses", json=payload).json()
    assert repeat["data"]["snapshot_sha256"] == result["data"]["snapshot_sha256"]
    assert repeat["results"] == result["results"]
    listing = client.get("/api/v1/analyses", params={"limit": 1}).json()
    assert len(listing) == 1
    assert listing[0]["id"] == repeat["id"]
    assert client.get("/api/v1/analyses?limit=0").status_code == 422
    assert client.get("/api/v1/analyses?offset=1").json()[0]["id"] == result["id"]


def test_persistence_survives_app_restart(settings, provider, payload):
    """A new app instance using the same database retrieves the unchanged saved analysis."""
    with TestClient(create_app(settings=settings, provider=provider)) as first:
        saved = first.post("/api/v1/analyses", json=payload).json()
    with TestClient(create_app(settings=settings, provider=provider)) as second:
        assert second.get(f"/api/v1/analyses/{saved['id']}").json() == saved


@pytest.mark.parametrize(
    "patch",
    [
        {"tickers": ["AAA", "aaa"]},
        {"tickers": ["AAA"]},
        {"tickers": ["AAA", "../BBB"]},
        {"tickers": [str(index) for index in range(31)]},
        {"min_weight": 0.4},
        {"max_weight": 0.2},
        {"start_date": "2024-01-01"},
        {"end_date": "2999-01-01"},
        {"monte_carlo_samples": 5001},
        {"strategies": ["equal_weight", "equal_weight"]},
        {"unknown_setting": True},
    ],
)
def test_invalid_request_never_fetches_prices(client, payload, provider, patch):
    """Invalid tickers, bounds, dates, counts, strategies, or fields fail before fetching data."""
    response = client.post("/api/v1/analyses", json=payload | patch)
    assert response.status_code == 422
    assert provider.calls == 0


def test_not_found_and_invalid_id(client):
    """Unknown UUIDs return analysis_not_found while malformed identifiers fail validation."""
    response = client.get("/api/v1/analyses/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"
    assert client.get("/api/v1/analyses/not-a-uuid").status_code == 422


def test_provider_error_is_not_saved(client, payload, provider):
    """Provider failures retain their error response, save nothing, and allow a later retry."""
    provider.error = PortfolioError("provider_unavailable", "Data unavailable", 503)
    response = client.post("/api/v1/analyses", json=payload)
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "provider_unavailable", "message": "Data unavailable"}
    }
    assert client.get("/api/v1/analyses").json() == []
    provider.error = None
    assert client.post("/api/v1/analyses", json=payload).status_code == 201


def test_api_key_protects_all_data_routes(settings, provider, payload):
    """Configured keys guard listing, creation, and search while health remains public."""
    settings.api_key = "test-only-key-not-a-real-secret"
    with TestClient(create_app(settings=settings, provider=provider)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/analyses").status_code == 401
        assert client.post("/api/v1/analyses", json=payload).status_code == 401
        assert client.get("/api/v1/assets/search?q=AAA").status_code == 401
        headers = {"X-API-Key": "test-only-key-not-a-real-secret"}
        assert client.get("/api/v1/analyses", headers=headers).status_code == 200
        assert client.get("/api/v1/analyses", headers={"X-API-Key": "wrong"}).status_code == 401


def test_cpu_budget_rejects_excessive_backtest_work(client, payload):
    """Daily rebalancing over the fixture range exceeds the backtest work budget."""
    payload["backtest"] = {"lookback_days": 60, "rebalance_every": 1}
    response = client.post("/api/v1/analyses", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "backtest_budget_exceeded"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_values_return_safe_validation_errors(client, payload, value):
    import json

    body = json.dumps(payload)[:-1] + ', "risk_free_rate": ' + value + "}"
    response = client.post(
        "/api/v1/analyses", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_empty_api_key_is_invalid_configuration():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(api_key="", _env_file=None)


def test_failed_storage_does_not_leak_details_or_hold_capacity(settings, provider, payload, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from portfolio_backend.database import AnalysisRepository

    settings.max_concurrent_analyses = 1
    with TestClient(create_app(settings=settings, provider=provider)) as client:
        with monkeypatch.context() as patch:
            def fail_save(*args):
                raise SQLAlchemyError("private connection details")

            patch.setattr(AnalysisRepository, "save", fail_save)
            response = client.post("/api/v1/analyses", json=payload)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "storage_unavailable"
            assert "private" not in response.text
        assert client.get("/api/v1/analyses").json() == []
        assert client.post("/api/v1/analyses", json=payload).status_code == 201


def test_analysis_capacity_is_bounded(settings, provider, payload, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    settings.max_concurrent_analyses = 1
    entered, release = Event(), Event()
    original = provider.history

    def blocked_history(*args):
        entered.set()
        assert release.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(provider, "history", blocked_history)
    with TestClient(create_app(settings=settings, provider=provider)) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, "/api/v1/analyses", json=payload)
            try:
                assert entered.wait(timeout=10)
                rejected = client.post("/api/v1/analyses", json=payload)
                assert rejected.status_code == 503
                assert rejected.json()["error"]["code"] == "analysis_capacity_reached"
            finally:
                release.set()
            assert first.result(timeout=10).status_code == 201
