import csv
import io
import json
import math
import zipfile
from typing import Any

import numpy as np

from portfolio_backend import __version__, analytics
from portfolio_backend.errors import PortfolioError
from portfolio_backend.models import (
    AnalysisData,
    AnalysisDataset,
    AnalysisResponse,
    BacktestMetrics,
    PriceSnapshot,
    RiskMetrics,
)

METHODS = {
    "daily_returns": "P[t] / P[t-1] - 1, dated at the end of each observation interval.",
    "expected_annual_return": "Arithmetic mean of daily returns multiplied by 252.",
    "sample_volatility": "Sample daily standard deviation (ddof=1) multiplied by sqrt(252).",
    "sample_covariance": "Sample daily covariance (ddof=1); annual covariance is daily times 252.",
    "optimizer_covariance": "Ledoit-Wolf shrinkage covariance, not sample covariance; "
    "annual covariance is daily times 252.",
    "correlation": "Stored Pearson sample correlation of arithmetic daily returns.",
    "risk_contributions": "Stored signed fractions of portfolio variance; zero for negligible "
    "variance, not percentage-point volatility contributions.",
    "portfolio_metrics": "Stored in-sample arithmetic return, volatility and Sharpe estimates; "
    "no optimization, frontier sampling, or backtests are rerun during export.",
    "backtest_returns": "Consecutive stored net equity values: V[t] / V[t-1] - 1. "
    "Initial return is null; entry and rebalance fees remain included.",
    "backtest_metrics": "Stored realized metrics. CAGR uses calendar days/365.25; volatility "
    "uses sample daily net returns and sqrt(252); Sharpe uses annual risk-free rate/252. "
    "Sortino uses the root mean squared negative daily excess return across all observations, "
    "annualized by sqrt(252). Calmar is CAGR / absolute maximum drawdown. Drawdown duration "
    "counts calendar days from a peak to recovery or evaluation end. Undefined ratios and "
    "metrics absent from legacy analyses are null. Benchmark comparisons use aligned net "
    "returns: tracking error is sample active-return volatility, information ratio is annual "
    "mean active return / tracking error, and excess total return is the difference in net "
    "cumulative returns (not CAGR).",

    "turnover": "Full traded notional / pretrade NAV, not half turnover; entry turnover is 1.",
    "transaction_cost": "Absolute deduction in initial-wealth units, not a return or basis points.",
    "scenario": "Block-bootstrap resampling of consecutive historical daily return blocks "
    "with replacement, preserving cross-asset dependence and serial structure within each "
    "block. Paths are conditional on the fitted weights and the sample return "
    "distribution; they are not forecasts or probability predictions.",
}

UNITS = {
    "prices": "Adjusted closing prices in the analysis base currency.",
    "returns_volatility_weights": "Decimal fractions, not percentages.",
    "covariance": "Squared decimal returns, daily or annual as labeled.",
    "correlation_sharpe": "Dimensionless.",
    "equity_transaction_cost": "Initial-wealth units; initial NAV is 1.",
    "drawdown": "Decimal fraction, nonpositive below the running peak.",
    "dates": "ISO 8601 calendar dates; adjacent observations may span multiple calendar days.",
    "scenario": "Simulated wealth in initial-wealth units starting at 1; percentile is a "
    "cross-path level between 0 and 1.",
}


def _cell(value: Any) -> str | int | float | None:
    if isinstance(value, float | np.floating):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def build_data(analysis: AnalysisResponse, snapshot: PriceSnapshot) -> AnalysisData:
    tickers = analysis.request.tickers
    if set(snapshot.tickers) != set(tickers) or len(snapshot.tickers) != len(tickers):
        raise PortfolioError("invalid_snapshot", "Saved price ticker order is invalid.")
    values = np.asarray(snapshot.prices, dtype=float)
    if values.shape != (len(snapshot.dates), len(tickers)) or len(values) < 2:
        raise PortfolioError("invalid_snapshot", "Saved price matrix dimensions are invalid.")
    prices = np.ascontiguousarray(
        values[:, [snapshot.tickers.index(ticker) for ticker in tickers]]
    )
    returns = prices[1:] / prices[:-1] - 1
    estimation = analysis.results.estimation
    if estimation is None:
        means, optimizer_covariance = analytics._estimate(returns)
        estimation_note = (
            "Optimizer moments reconstructed from saved prices with the current engine's "
            f"_estimate (engine {__version__}, Ledoit-Wolf); not originally persisted. "
            "They are not guaranteed to match the original engine's estimates."
        )
        estimation_label = "reconstructed, not originally persisted"
    else:
        if (
            set(estimation.tickers) != set(tickers)
            or len(estimation.tickers) != len(tickers)
            or len(estimation.expected_annual_returns) != len(tickers)
            or np.asarray(estimation.optimizer_covariance_annual).shape
            != (len(tickers), len(tickers))
        ):
            raise PortfolioError("invalid_snapshot", "Saved estimator dimensions are invalid.")
        order = [estimation.tickers.index(ticker) for ticker in tickers]
        means = np.asarray(estimation.expected_annual_returns)[order]
        optimizer_covariance = np.asarray(estimation.optimizer_covariance_annual)[
            np.ix_(order, order)
        ]
        estimation_note = (
            "Optimizer moments use the exact persisted estimation snapshot from the original "
            f"analysis (engine {analysis.engine_version}); no estimator refit was performed."
        )
        estimation_label = "persisted original estimates"
    with np.errstate(over="ignore", invalid="ignore"):
        sample_covariance = np.cov(returns, rowvar=False, ddof=1)
        sample_volatility = returns.std(axis=0, ddof=1) * np.sqrt(252)
    notes = [
        "All tables derive exclusively from the saved analysis and its saved adjusted prices; "
        "no provider calls, optimization, Monte Carlo sampling, or backtest reruns occur.",
        estimation_note,
        "Ticker columns and matrix rows follow the original analysis request ticker order.",
        "Daily arithmetic returns are dated at the end of each observation interval; "
        "the first price has no return. Missing dates are not filled.",
        "Sample covariance and sample volatility use ddof=1 and are distinct from the "
        "optimizer's Ledoit-Wolf covariance. Annualization uses 252 observations per year.",
        "Stored correlation, allocations, risk contributions, metrics, frontier and Monte Carlo "
        "points, equity, drawdowns, and rebalance records are exported without recomputation. "
        "Backtest net daily returns alone are derived from consecutive stored equity values.",
        "Disabled or omitted results have empty tables. Undefined or nonfinite values are null "
        "in previews and blank in CSV; the initial backtest daily return is null.",
        "CSV numeric cells retain full round-trip float precision. Formula-leading text cells "
        "and headers (=, +, -, @, ^, tab, CR, LF, including after spaces) receive a leading "
        "apostrophe for spreadsheet safety; numeric negatives are unchanged. JSON retains "
        "original text. CSV uses UTF-8, comma delimiters, and CRLF record endings.",
        "analysis.json contains the original stored response. prices.json is the canonical "
        "saved snapshot (sorted keys and compact JSON), verifiable against snapshot_sha256.",
    ]
    datasets = []

    def add(dataset_id, title, category, description, columns, rows):
        datasets.append(AnalysisDataset(
            id=dataset_id,
            title=title,
            category=category,
            description=description,
            columns=columns,
            rows=[[_cell(value) for value in row] for row in rows],
        ))

    add(
        "adjusted_prices", "Adjusted closing prices", "Market data",
        f"Saved adjusted prices in {analysis.data.currency}; {analysis.data.adjustment}.",
        ["date", *tickers],
        [[day.isoformat(), *row] for day, row in zip(snapshot.dates, prices.tolist(), strict=True)],
    )
    add(
        "daily_returns", "Daily arithmetic returns", "Market data", METHODS["daily_returns"],
        ["date", *tickers],
        [[day.isoformat(), *row]
         for day, row in zip(snapshot.dates[1:], returns.tolist(), strict=True)],
    )
    add(
        "asset_estimates", "Annual asset estimates", "Risk & estimates",
        f"Annual arithmetic expected means ({estimation_label}) and sample volatility "
        "(ddof=1), in decimal fractions; not forecasts.",
        ["ticker", "expected_annual_return", "sample_annual_volatility"],
        [[ticker, means[index], sample_volatility[index]] for index, ticker in enumerate(tickers)],
    )
    for dataset_id, title, matrix, description in [
        ("sample_covariance_daily", "Sample covariance (daily)", sample_covariance,
         "Daily sample covariance (ddof=1) of arithmetic returns; not optimizer covariance."),
        ("sample_covariance_annual", "Sample covariance (annual)", sample_covariance * 252,
         "Annual sample covariance (ddof=1), daily times 252; not optimizer covariance."),
        ("optimizer_covariance_daily", "Optimizer covariance (daily)", optimizer_covariance / 252,
         f"Daily Ledoit-Wolf optimizer covariance ({estimation_label}), annual divided by 252."),
        ("optimizer_covariance_annual", "Optimizer covariance (annual)", optimizer_covariance,
         f"Annual Ledoit-Wolf optimizer covariance ({estimation_label}), daily times 252."),
    ]:
        add(
            dataset_id, title, "Risk & estimates", description, ["ticker", *tickers],
            [[ticker, *matrix[index].tolist()] for index, ticker in enumerate(tickers)],
        )
    add(
        "correlation", "Stored sample correlation", "Risk & estimates", METHODS["correlation"],
        ["ticker", *tickers],
        [[ticker, *[analysis.results.correlation[ticker].get(other) for other in tickers]]
         for ticker in tickers],
    )
    portfolios = analysis.results.portfolios
    metric_columns = list(RiskMetrics.model_fields)
    add(
        "strategy_weights", "Strategy weights", "Portfolios",
        "Stored fully invested target weights as decimal fractions.", ["strategy", *tickers],
        [[p.strategy.value, *[p.weights.get(ticker) for ticker in tickers]] for p in portfolios],
    )
    add(
        "strategy_metrics", "Strategy risk metrics", "Portfolios", METHODS["portfolio_metrics"],
        ["strategy", *metric_columns],
        [[p.strategy.value, *[getattr(p.metrics, column) for column in metric_columns]]
         for p in portfolios],
    )
    add(
        "risk_contributions", "Strategy risk contributions", "Portfolios",
        METHODS["risk_contributions"], ["strategy", *tickers],
        [[p.strategy.value, *[p.risk_contributions.get(ticker) for ticker in tickers]]
         for p in portfolios],
    )
    for dataset_id, title in [
        ("efficient_frontier", "Efficient frontier"), ("monte_carlo", "Monte Carlo portfolios")
    ]:
        add(
            dataset_id, title, "Portfolios",
            "Stored in-sample points, with zero-based point index, estimated metrics and "
            "fractional weights; empty when disabled or omitted.",
            ["point", *metric_columns, *[f"weight:{ticker}" for ticker in tickers]],
            [[index, *[getattr(point.metrics, column) for column in metric_columns],
              *[point.weights.get(ticker) for ticker in tickers]]
             for index, point in enumerate(getattr(analysis.results, dataset_id))],
        )
    backtests = analysis.results.backtests
    backtest_columns = list(BacktestMetrics.model_fields)
    add(
        "backtest_metrics", "Backtest performance metrics", "Backtests",
        METHODS["backtest_metrics"],
        ["strategy", *backtest_columns],
        [[b.strategy.value, *[getattr(b.metrics, column) for column in backtest_columns]]
         for b in backtests],
    )
    add(
        "backtest_equity", "Backtest equity, drawdown and net returns", "Backtests",
        "Stored equity (initial NAV 1) and fractional drawdown. " + METHODS["backtest_returns"],
        ["strategy", "date", "equity", "drawdown", "net_daily_return"],
        [[b.strategy.value, point.date.isoformat(), point.value, point.drawdown,
          point.value / b.equity_curve[index - 1].value - 1 if index else None]
         for b in backtests for index, point in enumerate(b.equity_curve)],
    )
    add(
        "backtest_rebalances", "Backtest rebalances", "Backtests",
        "Stored execution-close target weights and fees. " + METHODS["turnover"] + " "
        + METHODS["transaction_cost"],
        ["strategy", "date", "turnover", "transaction_cost",
         *[f"weight:{ticker}" for ticker in tickers]],
        [[b.strategy.value, event.date.isoformat(), event.turnover, event.transaction_cost,
          *[event.weights.get(ticker) for ticker in tickers]]
         for b in backtests for event in b.rebalances],
    )
    scenarios = analysis.results.scenarios or []
    if scenarios:
        notes.append(
            "Scenario tables store block-bootstrap resamples of historical returns. "
            "scenario_fan gives the wealth percentile across simulated paths per date; "
            "scenario_percentiles gives terminal-date metrics per percentile; "
            "scenario_summary gives cross-path statistics. All are conditional on fitted "
            "weights and sample history, not forecasts."
        )
        add(
            "scenario_summary", "Scenario cross-path summary statistics", "Portfolios",
            "Cross-path statistics for each strategy's simulated horizon paths. "
            "Terminal wealth starts at 1; worst-5% drawdown is the mean of the worst "
            "5% of path max drawdowns.",
            [
                "strategy", "terminal_wealth_mean", "terminal_wealth_median",
                "terminal_return_5pct", "terminal_return_95pct",
                "max_drawdown_worst_5pct",
            ],
            [
                [
                    scenario.strategy.value,
                    scenario.summary_statistics.terminal_wealth_mean,
                    scenario.summary_statistics.terminal_wealth_median,
                    scenario.summary_statistics.terminal_return_5pct,
                    scenario.summary_statistics.terminal_return_95pct,
                    scenario.summary_statistics.max_drawdown_worst_5pct,
                ]
                for scenario in scenarios
            ],
        )
        add(
            "scenario_percentiles", "Scenario terminal metrics by percentile", "Portfolios",
            "Terminal-date metrics at each requested cross-path percentile. " +
            METHODS["scenario"],
            [
                "strategy", "percentile", "terminal_return", "max_drawdown",
                "terminal_wealth", "cagr",
            ],
            [
                [
                    scenario.strategy.value,
                    level,
                    metrics.terminal_return,
                    metrics.max_drawdown,
                    metrics.terminal_wealth,
                    metrics.cagr,
                ]
                for scenario in scenarios
                for level, metrics in scenario.percentiles.items()
            ],
        )
        add(
            "scenario_fan", "Scenario wealth fan paths", "Portfolios",
            "Cross-path wealth percentile on each simulated calendar date. " +
            METHODS["scenario"],
            ["strategy", "percentile", "date", "wealth"],
            [
                [scenario.strategy.value, path.percentile, day, value]
                for scenario in scenarios
                for path in scenario.fan_paths
                for day, value in zip(path.dates, path.values, strict=True)
            ],
        )
    benchmark = analysis.results.benchmark
    benchmark_snapshot = analysis.benchmark_snapshot
    if benchmark is not None:
        notes.append(
            "Benchmark results are saved buy-and-hold results on the same evaluation dates "
            "and entry-fee convention as portfolios; no terminal liquidation fee is charged. "
            "Benchmark prices are separate from portfolio inputs and do not enter the optimizer. "
            "benchmark_prices.json is the canonical saved benchmark snapshot, verifiable "
            "against benchmark_provenance.snapshot_sha256 in manifest.json."
        )
        if (
            benchmark_snapshot is None
            or benchmark_snapshot.tickers != [benchmark.ticker]
            or benchmark_snapshot.dates != snapshot.dates
            or len(benchmark_snapshot.prices) != len(snapshot.dates)
            or any(len(row) != 1 for row in benchmark_snapshot.prices)
        ):
            raise PortfolioError(
                "invalid_snapshot", "Saved benchmark price dimensions are invalid."
            )
        add(
            "benchmark_prices", "Benchmark adjusted prices", "Market data",
            "Saved benchmark adjusted closing prices on common analysis dates; not optimizer "
            "inputs.",
            ["date", benchmark.ticker],
            [[day.isoformat(), *row] for day, row in zip(
                benchmark_snapshot.dates, benchmark_snapshot.prices, strict=True
            )],
        )
        def metrics_row(metrics, ticker):
            return [ticker, *[getattr(metrics, column) for column in backtest_columns]]

        add(
            "benchmark_metrics", "Benchmark performance metrics", "Backtests",
            METHODS["backtest_metrics"], ["ticker", *backtest_columns],
            [metrics_row(benchmark.metrics, benchmark.ticker)],
        )
        add(
            "benchmark_equity", "Benchmark equity, drawdown and net returns", "Backtests",
            "Stored buy-and-hold benchmark equity. " + METHODS["backtest_returns"],
            ["ticker", "date", "equity", "drawdown", "net_daily_return"],
            [[benchmark.ticker, point.date.isoformat(), point.value, point.drawdown,
              point.value / benchmark.equity_curve[index - 1].value - 1 if index else None]
             for index, point in enumerate(benchmark.equity_curve)],
        )
        add(
            "benchmark_trades", "Benchmark entry trade", "Backtests",
            "Single benchmark entry; no subsequent rebalances. " + METHODS["transaction_cost"],
            ["ticker", "date", "turnover", "transaction_cost", f"weight:{benchmark.ticker}"],
            [[benchmark.ticker, event.date.isoformat(), event.turnover, event.transaction_cost,
              event.weights.get(benchmark.ticker)] for event in benchmark.rebalances],
        )
    return AnalysisData(datasets=datasets, notes=notes)


def _spreadsheet_cell(value: str | int | float | None) -> str | int | float | None:
    if isinstance(value, str) and value.lstrip(" ").startswith(
        ("=", "+", "-", "@", "^", "\t", "\r", "\n")
    ):
        return "'" + value
    return value


def render_csv(dataset: AnalysisDataset) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow([_spreadsheet_cell(column) for column in dataset.columns])
    writer.writerows([_spreadsheet_cell(value) for value in row] for row in dataset.rows)
    return stream.getvalue().encode("utf-8")


def _column_description(dataset: AnalysisDataset, column: str, currency: str) -> str:
    descriptions = {
        "date": "ISO 8601 observation date (returns use interval end; rebalances execution close).",
        "ticker": "Row instrument identifier in analysis request order.",
        "strategy": "Stored allocation strategy identifier.",
        "point": "Zero-based index in the stored sequence of portfolio points.",
        "expected_annual_return": "Annual arithmetic expected return, decimal fraction.",
        "sample_annual_volatility": "Sample daily standard deviation (ddof=1) times sqrt(252).",
        "annual_volatility": "Annual volatility, decimal fraction; estimated for portfolios, "
        "realized sample volatility of net returns for backtests.",
        "sharpe_ratio": "Annualized excess return / volatility, dimensionless; null if undefined.",
        "sortino_ratio": "Annualized mean excess return / annualized downside deviation, "
        "using all daily observations and annual risk-free rate/252; dimensionless.",
        "calmar_ratio": "CAGR / absolute maximum drawdown; dimensionless; null if undefined.",
        "max_drawdown_duration_days": "Longest calendar peak-to-recovery or peak-to-end "
        "drawdown duration, including unrecovered drawdowns; zero if never underwater.",
        "tracking_error": "Sample standard deviation of aligned daily net portfolio minus "
        "benchmark returns times sqrt(252), decimal fraction.",
        "information_ratio": "Annualized mean net active return / tracking error; "
        "dimensionless; null without a benchmark or with negligible tracking error.",
        "excess_total_return": "Net cumulative portfolio return minus benchmark return, "
        "decimal fraction; multiply by 100 for percentage points, not relative percent gain.",
        "total_return": "Realized net total return, decimal fraction.",
        "cagr": "Realized compound annual growth using calendar days/365.25, decimal fraction.",
        "max_drawdown": "Worst realized fractional drawdown; nonpositive.",
        "total_turnover": "Sum of full-notional turnover fractions across execution events.",
        "total_transaction_cost": "Sum of transaction fees in initial-wealth units.",
        "equity": "Stored net wealth in initial-wealth units; initial value 1.",
        "drawdown": "Stored equity / running peak - 1, decimal fraction.",
        "net_daily_return": "Net equity / prior net equity - 1; null on initial date.",
        "turnover": METHODS["turnover"],
        "transaction_cost": METHODS["transaction_cost"],
    }
    if column in descriptions:
        return descriptions[column]
    if column.startswith("weight:") or dataset.id == "strategy_weights":
        return f"Target portfolio weight for {column.removeprefix('weight:')}, decimal fraction."
    if dataset.id in {"adjusted_prices", "benchmark_prices"}:
        return f"Saved adjusted closing price of {column}, in {currency}."
    if dataset.id == "daily_returns":
        return f"Arithmetic interval return of {column}, decimal fraction."
    if "covariance" in dataset.id:
        return f"Covariance with {column}, squared decimal returns. {dataset.description}"
    if dataset.id == "correlation":
        return f"Stored correlation with {column}, dimensionless; null if undefined."
    if dataset.id == "risk_contributions":
        return f"Signed fraction of portfolio variance attributable to {column}."
    if dataset.id in {"scenario_summary", "scenario_percentiles", "scenario_fan"}:
        scenario_columns = {
            "strategy": "Allocation strategy whose fitted weights drive the scenarios.",
            "percentile": "Cross-path percentile level as a fraction between 0 and 1.",
            "date": "Projected calendar date following the last observed price date.",
            "wealth": "Simulated wealth percentile, initial-wealth units starting at 1.",
            "terminal_return": "Terminal simulated return at the percentile, decimal fraction.",
            "terminal_wealth": "Terminal simulated wealth at the percentile; initial value 1.",
            "max_drawdown": "Path maximum drawdown at the percentile; nonpositive fraction.",
            "cagr": "Compound annual growth implied by terminal wealth over the horizon; "
                    "null when nonpositive or undefined.",
            "terminal_wealth_mean": "Mean terminal simulated wealth; initial value 1.",
            "terminal_wealth_median": "Median terminal simulated wealth; initial value 1.",
            "terminal_return_5pct": "5th percentile terminal return, decimal fraction.",
            "terminal_return_95pct": "95th percentile terminal return, decimal fraction.",
            "max_drawdown_worst_5pct": "Mean of the worst 5% of path maximum drawdowns, "
                                       "nonpositive fraction.",
        }
        return scenario_columns.get(column, dataset.description)
    return dataset.description


def build_manifest(analysis: AnalysisResponse, data: AnalysisData) -> dict[str, Any]:
    estimation = analysis.results.estimation
    return {
        "schema": "portfolio-analysis-export",
        "schema_version": 1,
        "analysis_id": analysis.id,
        "created_at": analysis.created_at.isoformat(),
        "analysis_engine_version": analysis.engine_version,
        "export_engine_version": __version__,
        "provenance": analysis.data.model_dump(mode="json"),
        "benchmark_provenance": (
            analysis.benchmark_data.model_dump(mode="json") if analysis.benchmark_data else None
        ),
        "request": analysis.request.model_dump(mode="json"),
        "ticker_order": analysis.request.tickers,
        "estimation": {
            "source": "persisted" if estimation is not None else "reconstructed",
            "originally_persisted": estimation is not None,
            "engine_version": analysis.engine_version if estimation is not None else __version__,
            "annualization_factor": 252,
            "mean_estimator": "arithmetic_daily_mean",
            "covariance_estimator": "LedoitWolf",
            "note": data.notes[1],
        },
        "notes": data.notes,
        "methods": METHODS,
        "units": UNITS,
        "warnings": analysis.results.warnings,
        "assumptions": analysis.assumptions,
        "datasets": [
            {
                "id": dataset.id,
                "filename": f"{dataset.id}.csv",
                "title": dataset.title,
                "category": dataset.category,
                "description": dataset.description,
                "columns": dataset.columns,
                "row_count": len(dataset.rows),
                "column_descriptions": {
                    column: _column_description(dataset, column, analysis.data.currency)
                    for column in dataset.columns
                },
            }
            for dataset in data.datasets
        ],
    }


def render_archive(
    stored_analysis: dict[str, Any], stored_prices: dict[str, Any], data: AnalysisData
) -> bytes:
    analysis = AnalysisResponse.model_validate(stored_analysis)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for dataset in data.datasets:
            archive.writestr(f"{dataset.id}.csv", render_csv(dataset))
        json_files = [
            ("analysis.json", stored_analysis),
            ("prices.json", stored_prices),
            ("manifest.json", build_manifest(analysis, data)),
        ]
        if stored_analysis.get("benchmark_snapshot") is not None:
            json_files.append(("benchmark_prices.json", stored_analysis["benchmark_snapshot"]))
        for filename, content in json_files:
            archive.writestr(
                filename,
                json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False),
            )
    return stream.getvalue()
