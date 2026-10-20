"""Grounding material for the research assistant: analysis summaries and prompts."""

from importlib import resources
from typing import Any

from portfolio_backend.exports import METHODS, UNITS
from portfolio_backend.models import AnalysisResponse, AnalysisSummary, BacktestMetrics
from portfolio_backend.service import ASSUMPTIONS

MAX_CORRELATION_TICKERS = 12
MAX_WARNINGS = 20

SYSTEM_PROMPT = """You are the research assistant inside Portfolio Lab, a web tool that compares \
long-only portfolio allocation strategies on historical daily prices, runs walk-forward backtests, \
and simulates block-bootstrap scenarios. Your job is to help users understand and use the tool.

What you do:
- Explain what the methodology does and why, using the methodology brief below.
- Interpret saved analyses: read the actual numbers with your tools and explain what they mean, \
what drives them, and what their limitations are.
- Help users configure a sensible analysis (tickers, window, bounds, backtest settings) and run it \
with the run_analysis tool when they ask you to.
- Suggest research experiments (change one input at a time) and compare saved analyses.

Hard rules:
- Ground every number in tool output or the provided analysis context. Never invent, estimate, or \
recall market figures from memory. If a value is not available, say so or fetch it with a tool.
- Always distinguish in-sample estimates (full-window weights and metrics), walk-forward backtest \
results (net of fees, lagged), and bootstrap scenarios (conditional resampling, not forecasts).
- Mention the analysis's own warnings when they affect the interpretation.
- This is an educational research tool. Do not give personalized investment advice, do not tell \
the user what to buy, sell, or hold, and do not predict future prices or returns. Present \
trade-offs and let the user decide. If asked for a recommendation, explain what the data shows \
and the limitations instead.
- Before calling run_analysis, make sure the parameters are explicit in the conversation (restate \
them briefly). Prefer modest settings (monte_carlo_samples <= 1000, scenario paths <= 1000). If a \
run fails validation or exceeds a budget, fix the request based on the error and explain the change.
- After run_analysis succeeds, summarize the key results and give the link /analysis/<id>.
- Tickers must be uppercase provider symbols; use search_assets when a company name or an \
uncertain symbol is given.

Style:
- Be concise and concrete. Present fractions as percentages with one or two decimals \
(0.1234 -> 12.34%), ratios as plain numbers, drawdowns as negative percentages.
- Use short paragraphs and "-" bullet lists. Use **bold** sparingly and `code` for identifiers. \
Do not use markdown tables or headings.
- Do not repeat the disclaimer in every message; the interface already shows it.
"""


def load_knowledge() -> str:
    """Return the packaged methodology brief plus engine method and unit definitions."""
    brief = (resources.files("portfolio_backend") / "knowledge" / "methodology.md").read_text(
        encoding="utf-8"
    )
    methods = "\n".join(f"- {key}: {value}" for key, value in METHODS.items())
    units = "\n".join(f"- {key}: {value}" for key, value in UNITS.items())
    assumptions = "\n".join(f"- {item}" for item in ASSUMPTIONS)
    return (
        f"{brief}\n\n## Engine method definitions\n\n{methods}\n\n## Units\n\n{units}\n\n"
        f"## Assumptions shown to users\n\n{assumptions}\n"
    )


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _round_map(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 6) for key, value in values.items()}


def _backtest_metrics(metrics: BacktestMetrics) -> dict[str, Any]:
    return {key: _round(value) for key, value in metrics.model_dump().items()}


def summarize_analysis(analysis: AnalysisResponse) -> dict[str, Any]:
    """Build a compact, token-bounded view of a saved analysis for the model.

    Equity curves, fan paths, Monte Carlo points, frontier points, and price
    snapshots are omitted; the model can request datasets separately.
    """
    request = analysis.request
    results = analysis.results
    data = analysis.data
    tickers = request.tickers
    summary: dict[str, Any] = {
        "analysis_id": analysis.id,
        "created_at": analysis.created_at.isoformat(),
        "link": f"/analysis/{analysis.id}",
        "request": {
            "tickers": tickers,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "base_currency": request.base_currency,
            "strategies": [s.value for s in request.strategies],
            "benchmark_ticker": request.benchmark_ticker,
            "min_weight": request.min_weight,
            "max_weight": request.max_weight,
            "risk_free_rate": request.risk_free_rate,
            "monte_carlo_samples": request.monte_carlo_samples,
            "frontier_points": request.frontier_points,
            "backtest": request.backtest.model_dump(),
            "scenario": request.scenario.model_dump(exclude={"percentile_levels", "random_seed"}),
        },
        "data": {
            "provider": data.provider,
            "effective_start": data.effective_start.isoformat(),
            "effective_end": data.effective_end.isoformat(),
            "price_observations": data.price_observations,
            "return_observations": data.return_observations,
            "currency": data.currency,
            "adjustment": data.adjustment,
            "instruments": [
                {"symbol": i.symbol, "name": i.name, "exchange": i.exchange}
                for i in data.instruments
            ],
        },
        "in_sample_portfolios": [
            {
                "strategy": p.strategy.value,
                "weights": _round_map(p.weights),
                "expected_annual_return": _round(p.metrics.expected_annual_return),
                "annual_volatility": _round(p.metrics.annual_volatility),
                "sharpe_ratio": _round(p.metrics.sharpe_ratio),
                "risk_contributions": _round_map(p.risk_contributions),
            }
            for p in results.portfolios
        ],
        "backtests": [
            {
                "strategy": b.strategy.value,
                "metrics": _backtest_metrics(b.metrics),
                "rebalance_count": len(b.rebalances),
                "first_date": b.equity_curve[0].date.isoformat() if b.equity_curve else None,
                "last_date": b.equity_curve[-1].date.isoformat() if b.equity_curve else None,
            }
            for b in results.backtests
        ],
        "benchmark": (
            {
                "ticker": results.benchmark.ticker,
                "metrics": _backtest_metrics(results.benchmark.metrics),
            }
            if results.benchmark
            else None
        ),
        "scenarios": [
            {
                "strategy": s.strategy.value,
                "summary_statistics": {
                    key: _round(value) for key, value in s.summary_statistics.model_dump().items()
                },
                "percentiles": {
                    str(level): {key: _round(value) for key, value in metrics.model_dump().items()}
                    for level, metrics in s.percentiles.items()
                },
            }
            for s in results.scenarios or []
        ],
        "efficient_frontier_points": len(results.efficient_frontier),
        "monte_carlo_points": len(results.monte_carlo),
        "estimation": (
            "persisted optimizer moments available"
            if results.estimation
            else "legacy analysis: optimizer moments not persisted"
        ),
        "warnings": results.warnings[:MAX_WARNINGS],
        "warnings_truncated": max(0, len(results.warnings) - MAX_WARNINGS),
    }
    if len(tickers) <= MAX_CORRELATION_TICKERS:
        summary["correlation"] = {
            row: {col: _round(value, 3) for col, value in cols.items()}
            for row, cols in results.correlation.items()
        }
    else:
        summary["correlation"] = (
            f"omitted ({len(tickers)} tickers); request the 'correlation' dataset if needed"
        )
    return summary


def summarize_listing(items: list[AnalysisSummary]) -> list[dict[str, Any]]:
    """Render analysis summaries for the list_analyses tool."""
    return [
        {
            "analysis_id": item.id,
            "created_at": item.created_at.isoformat(),
            "tickers": item.tickers,
            "start_date": item.start_date.isoformat(),
            "end_date": item.end_date.isoformat(),
            "link": f"/analysis/{item.id}",
        }
        for item in items
    ]
