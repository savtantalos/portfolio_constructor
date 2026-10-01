import csv
import hashlib
import io
import json
import zipfile
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from test_api import FakeProvider

from portfolio_backend import analytics
from portfolio_backend.config import Settings
from portfolio_backend.database import AnalysisRecord
from portfolio_backend.main import create_app


@pytest.fixture
def export_case(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'exports.db'}", _env_file=None)
    provider = FakeProvider()
    with TestClient(create_app(settings=settings, provider=provider)) as client:
        response = client.post(
            "/api/v1/analyses",
            json={
                "tickers": ["BBB", "^AAA", "CCC"],
                "start_date": "2022-01-01",
                "end_date": "2022-06-30",
                "strategies": ["equal_weight", "minimum_variance"],
                "monte_carlo_samples": 4,
                "frontier_points": 3,
                "backtest": {"lookback_days": 60, "rebalance_every": 21},
            },
        )
        assert response.status_code == 201, response.text
        saved = response.json()
        base = f"/api/v1/analyses/{saved['id']}"
        snapshot = client.get(f"{base}/prices").json()
        yield client, provider, settings, saved, snapshot, base


def dataset_map(client, base):
    response = client.get(f"{base}/data")
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data) == {"datasets", "notes"}
    assert data["notes"]
    datasets = {table["id"]: table for table in data["datasets"]}
    assert len(datasets) == len(data["datasets"])
    for table in datasets.values():
        assert set(table) == {"id", "title", "category", "description", "columns", "rows"}
        assert table["category"] in {
            "Market data", "Risk & estimates", "Portfolios", "Backtests"
        }
        assert all(len(row) == len(table["columns"]) for row in table["rows"])
    return datasets, data


def replace_saved(settings, saved):
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                update(AnalysisRecord)
                .where(AnalysisRecord.id == saved["id"])
                .values(result=saved)
            )
    finally:
        engine.dispose()


def test_new_analyses_persist_exact_optimizer_estimates(export_case, monkeypatch):
    client, provider, _, saved, snapshot, base = export_case
    estimates = saved["results"]["estimation"]
    assert estimates["tickers"] == snapshot["tickers"]
    assert estimates["annualization_factor"] == 252
    assert estimates["covariance_estimator"] == "LedoitWolf"
    prices = np.asarray(snapshot["prices"])
    returns = prices[1:] / prices[:-1] - 1
    means, covariance = analytics._estimate(returns)
    np.testing.assert_array_equal(estimates["expected_annual_returns"], means)
    np.testing.assert_array_equal(estimates["optimizer_covariance_annual"], covariance)
    for portfolio in saved["results"]["portfolios"]:
        weights = np.array([portfolio["weights"][ticker] for ticker in estimates["tickers"]])
        variance = weights @ covariance @ weights
        assert portfolio["metrics"]["expected_annual_return"] == pytest.approx(weights @ means)
        assert portfolio["metrics"]["annual_volatility"] == pytest.approx(np.sqrt(variance))
        np.testing.assert_allclose(
            [portfolio["risk_contributions"][ticker] for ticker in estimates["tickers"]],
            weights * (covariance @ weights) / variance,
        )
    assert client.get(base).json() == saved

    def forbidden(*args, **kwargs):
        pytest.fail("Exports must not refit persisted moments, optimize, backtest, or fetch")

    monkeypatch.setattr(analytics, "_estimate", forbidden)
    monkeypatch.setattr(analytics, "_weights", forbidden)
    monkeypatch.setattr(analytics, "_backtest", forbidden)
    monkeypatch.setattr(provider, "history", forbidden)
    tables, data = dataset_map(client, base)
    assert "persisted" in " ".join(data["notes"]).lower()
    assert client.get(f"{base}/export").status_code == 200
    assert client.get(f"{base}/export/optimizer_covariance_annual").status_code == 200
    np.testing.assert_array_equal(
        [row[1:] for row in tables["optimizer_covariance_annual"]["rows"]], covariance
    )
    assert provider.calls == 1


def test_tables_match_snapshot_sample_and_optimizer_estimators(export_case):
    client, _, _, saved, snapshot, base = export_case
    tables, _ = dataset_map(client, base)
    tickers = snapshot["tickers"]
    prices = np.asarray(snapshot["prices"])
    returns = prices[1:] / prices[:-1] - 1
    assert tables["adjusted_prices"]["columns"] == ["date", *tickers]
    assert tables["adjusted_prices"]["rows"] == [
        [day, *values] for day, values in zip(snapshot["dates"], snapshot["prices"], strict=True)
    ]
    assert tables["daily_returns"]["columns"] == ["date", *tickers]
    assert [row[0] for row in tables["daily_returns"]["rows"]] == snapshot["dates"][1:]
    np.testing.assert_array_equal(
        [row[1:] for row in tables["daily_returns"]["rows"]], returns
    )
    sample = np.cov(returns, rowvar=False, ddof=1)
    means, optimizer = analytics._estimate(returns)
    for table_id, expected in {
        "sample_covariance_daily": sample,
        "sample_covariance_annual": sample * 252,
        "optimizer_covariance_daily": optimizer / 252,
        "optimizer_covariance_annual": optimizer,
    }.items():
        assert tables[table_id]["columns"] == ["ticker", *tickers]
        assert [row[0] for row in tables[table_id]["rows"]] == tickers
        np.testing.assert_array_equal([row[1:] for row in tables[table_id]["rows"]], expected)
    assert not np.allclose(sample * 252, optimizer)
    assert "ddof=1" in tables["sample_covariance_daily"]["description"]
    assert "Ledoit-Wolf" in tables["optimizer_covariance_daily"]["description"]
    np.testing.assert_allclose(
        [row[1:] for row in tables["asset_estimates"]["rows"]],
        np.column_stack([means, returns.std(axis=0, ddof=1) * np.sqrt(252)]),
    )
    assert tables["correlation"]["rows"] == [
        [ticker, *[saved["results"]["correlation"][ticker][other] for other in tickers]]
        for ticker in tickers
    ]


def test_portfolios_backtests_and_rebalances_use_stored_results(export_case):
    client, _, _, saved, _, base = export_case
    tables, _ = dataset_map(client, base)
    tickers = saved["request"]["tickers"]
    for index, portfolio in enumerate(saved["results"]["portfolios"]):
        assert tables["strategy_weights"]["rows"][index] == [
            portfolio["strategy"], *[portfolio["weights"][ticker] for ticker in tickers]
        ]
        assert tables["risk_contributions"]["rows"][index] == [
            portfolio["strategy"],
            *[portfolio["risk_contributions"][ticker] for ticker in tickers],
        ]
        assert dict(zip(
            tables["strategy_metrics"]["columns"][1:],
            tables["strategy_metrics"]["rows"][index][1:], strict=True,
        )) == portfolio["metrics"]
    for name in ["efficient_frontier", "monte_carlo"]:
        for index, point in enumerate(saved["results"][name]):
            assert tables[name]["rows"][index] == [
                index, *point["metrics"].values(),
                *[point["weights"][ticker] for ticker in tickers],
            ]
    for backtest in saved["results"]["backtests"]:
        rows = [r for r in tables["backtest_equity"]["rows"] if r[0] == backtest["strategy"]]
        assert rows[0][-1] is None
        for index, point in enumerate(backtest["equity_curve"]):
            assert rows[index][:4] == [
                backtest["strategy"], point["date"], point["value"], point["drawdown"]
            ]
            if index:
                assert rows[index][-1] == (
                    point["value"] / backtest["equity_curve"][index - 1]["value"] - 1
                )
        events = [
            r for r in tables["backtest_rebalances"]["rows"] if r[0] == backtest["strategy"]
        ]
        assert events == [
            [backtest["strategy"], e["date"], e["turnover"], e["transaction_cost"],
             *[e["weights"][ticker] for ticker in tickers]]
            for e in backtest["rebalances"]
        ]
        metrics = next(
            r for r in tables["backtest_metrics"]["rows"] if r[0] == backtest["strategy"]
        )
        assert metrics[1:] == list(backtest["metrics"].values())


def test_legacy_estimates_are_explicitly_reconstructed_without_mutation(export_case, monkeypatch):
    client, provider, settings, saved, snapshot, base = export_case
    saved["results"].pop("estimation", None)
    replace_saved(settings, saved)
    assert client.get(base).json()["results"]["estimation"] is None
    estimator = analytics._estimate
    calls = []

    def estimate(returns):
        calls.append(returns.copy())
        return estimator(returns)

    def forbidden(*args, **kwargs):
        pytest.fail("Legacy export must not fetch, optimize, or backtest")

    monkeypatch.setattr(analytics, "_estimate", estimate)
    monkeypatch.setattr(analytics, "_weights", forbidden)
    monkeypatch.setattr(analytics, "_backtest", forbidden)
    monkeypatch.setattr(provider, "history", forbidden)
    tables, data = dataset_map(client, base)
    notes = " ".join(data["notes"]).lower()
    assert "reconstructed" in notes and "not originally persisted" in notes
    assert "current" in notes
    assert "reconstructed" in tables["optimizer_covariance_annual"]["description"].lower()
    assert len(calls) == 1
    prices = np.asarray(snapshot["prices"])
    np.testing.assert_array_equal(calls[0], prices[1:] / prices[:-1] - 1)
    np.testing.assert_array_equal(
        [r[1:] for r in tables["optimizer_covariance_annual"]["rows"]], estimator(calls[0])[1]
    )
    with zipfile.ZipFile(io.BytesIO(client.get(f"{base}/export").content)) as archive:
        assert json.loads(archive.read("analysis.json")) == saved
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["estimation"]["source"] == "reconstructed"
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            persisted = session.scalar(
                select(AnalysisRecord.result).where(AnalysisRecord.id == saved["id"])
            )
            assert "estimation" not in persisted["results"]
    finally:
        engine.dispose()
    assert provider.calls == 1


def test_zip_and_individual_csv_match_preview_with_precision_and_safe_headers(export_case):
    client, provider, _, saved, snapshot, base = export_case
    tables, data = dataset_map(client, base)
    response = client.get(f"{base}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment;" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.zip"')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "analysis.json", "prices.json", "manifest.json", *[f"{key}.csv" for key in tables]
        }
        assert json.loads(archive.read("analysis.json")) == saved
        assert json.loads(archive.read("prices.json")) == snapshot
        assert hashlib.sha256(archive.read("prices.json")).hexdigest() == (
            saved["data"]["snapshot_sha256"]
        )
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 1
        assert manifest["provenance"] == saved["data"]
        assert manifest["request"] == saved["request"]
        assert manifest["warnings"] == saved["results"]["warnings"]
        assert manifest["assumptions"] == saved["assumptions"]
        assert manifest["notes"] == data["notes"]
        assert manifest["estimation"]["source"] == "persisted"
        assert manifest["methods"] and manifest["units"]
        assert {d["id"] for d in manifest["datasets"]} == set(tables)
        for entry in manifest["datasets"]:
            assert set(entry["column_descriptions"]) == set(tables[entry["id"]]["columns"])
        for key, table in tables.items():
            single = client.get(f"{base}/export/{key}")
            assert single.status_code == 200
            assert single.headers["content-type"].startswith("text/csv")
            assert "attachment;" in single.headers["content-disposition"]
            assert single.content == archive.read(f"{key}.csv")
            rows = list(csv.reader(io.StringIO(single.text)))
            for expected_row, actual_row in zip(
                [table["columns"], *table["rows"]], rows, strict=True
            ):
                for expected, actual in zip(expected_row, actual_row, strict=True):
                    if expected is None:
                        assert actual == ""
                    elif isinstance(expected, (float, int)):
                        assert float(actual) == expected
                        assert not actual.startswith("'")
                    else:
                        assert actual == ("'" + expected if expected.startswith("^") else expected)
    assert provider.calls == 1


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n", "^", " ="])
def test_csv_escapes_only_text_without_losing_quoting_precision_or_null(prefix):
    from portfolio_backend.exports import render_csv
    from portfolio_backend.models import AnalysisDataset

    text = prefix + 'SUM(1,2)"\nnext'
    number = -0.12345678901234567
    dataset = AnalysisDataset(
        id="test", title="Test", category="Market data", description="Test",
        columns=[text, "number", "missing"], rows=[[text, number, None]],
    )
    rows = list(csv.reader(io.StringIO(render_csv(dataset).decode("utf-8"))))
    assert rows == [
        ["'" + text, "number", "missing"],
        ["'" + text, str(number), ""],
    ]


def test_disabled_and_omitted_results_are_empty_and_nulls_survive(export_case):
    client, _, settings, saved, _, base = export_case
    saved["request"]["backtest"]["enabled"] = False
    saved["results"]["backtests"] = []
    saved["results"]["monte_carlo"] = []
    saved["results"]["efficient_frontier"] = []
    saved["results"]["portfolios"][0]["metrics"]["sharpe_ratio"] = None
    saved["results"]["correlation"]["BBB"]["CCC"] = None
    replace_saved(settings, saved)
    tables, _ = dataset_map(client, base)
    for key in ["backtest_metrics", "backtest_equity", "backtest_rebalances",
                "monte_carlo", "efficient_frontier"]:
        assert tables[key]["rows"] == []
        assert len(list(csv.reader(io.StringIO(client.get(f"{base}/export/{key}").text)))) == 1
    assert tables["strategy_metrics"]["rows"][0][-1] is None
    assert tables["correlation"]["rows"][0][-1] is None
    assert client.get(f"{base}/export").status_code == 200


def test_disabled_backtest_and_sampling_at_creation(export_case):
    client, provider, _, saved, _, _ = export_case
    payload = saved["request"] | {
        "backtest": {"enabled": False}, "monte_carlo_samples": 0, "frontier_points": 0
    }
    response = client.post("/api/v1/analyses", json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["results"]["estimation"] is not None
    base = f"/api/v1/analyses/{result['id']}"
    tables, _ = dataset_map(client, base)
    for key in [
        "backtest_metrics", "backtest_equity", "backtest_rebalances",
        "monte_carlo", "efficient_frontier",
    ]:
        assert tables[key]["rows"] == []
    assert client.get(f"{base}/export").status_code == 200
    assert provider.calls == 2


def test_export_order_is_request_order_even_with_reordered_snapshots(export_case):
    from portfolio_backend.exports import build_data
    from portfolio_backend.models import AnalysisResponse, PriceSnapshot

    _, _, _, saved, snapshot, _ = export_case
    analysis = AnalysisResponse.model_validate(saved)
    prices = PriceSnapshot.model_validate(snapshot)
    expected = build_data(analysis, prices)
    order = [2, 0, 1]
    prices.tickers = [prices.tickers[index] for index in order]
    prices.prices = [[row[index] for index in order] for row in prices.prices]
    estimates = analysis.results.estimation
    estimates.tickers = [estimates.tickers[index] for index in order]
    estimates.expected_annual_returns = [estimates.expected_annual_returns[i] for i in order]
    estimates.optimizer_covariance_annual = [
        [estimates.optimizer_covariance_annual[i][j] for j in order] for i in order
    ]
    assert build_data(analysis, prices) == expected


@pytest.mark.parametrize("suffix", ["data", "export", "export/adjusted_prices"])
def test_export_missing_invalid_ids_and_auth(export_case, suffix):
    client, provider, settings, _, _, base = export_case
    missing = client.get(f"/api/v1/analyses/{uuid4()}/{suffix}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "analysis_not_found"
    assert client.get(f"/api/v1/analyses/not-a-uuid/{suffix}").status_code == 422
    assert client.get(f"{base}/export/unknown").status_code == 404
    settings.api_key = "export-test-key"
    with TestClient(create_app(settings=settings, provider=provider)) as protected:
        assert protected.get(f"{base}/{suffix}").status_code == 401
        assert protected.get(f"{base}/{suffix}", headers={"X-API-Key": "wrong"}).status_code == 401
        assert protected.get(
            f"{base}/{suffix}", headers={"X-API-Key": "export-test-key"}
        ).status_code == 200
    assert provider.calls == 1
