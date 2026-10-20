# Portfolio Lab methodology brief

Portfolio Lab is a research tool for daily equity/ETF portfolio construction. It
compares long-only, fully invested allocation strategies on a shared historical
dataset, runs a walk-forward backtest, and optionally simulates forward
scenarios by block bootstrap. It is not an investment recommendation engine.

## Data pipeline

- Daily dividend- and split-adjusted closing prices from the configured provider
  (Yahoo Finance by default). All instruments must share the base currency; no FX
  conversion is performed.
- Only dates with a price for every selected asset are kept; missing dates are not
  forward-filled. Consecutive observations may therefore span several calendar days
  but each counts as one return observation.
- Simple (arithmetic) daily returns: `r[t] = P[t] / P[t-1] - 1`.
- At least 61 prices (60 returns) are required. An enabled backtest needs at least
  `lookback_days + 3` prices.
- Expected annual return per asset: arithmetic mean of daily returns times 252. This
  is an arithmetic estimate, not a CAGR, and not a forecast.
- Optimizer covariance: Ledoit-Wolf shrinkage of the daily covariance (blended toward
  a scaled identity), annualized by 252. Displayed correlations are ordinary sample
  Pearson correlations of daily returns, not derived from the shrunk matrix.
- Annualization assumes 252 trading observations per year; square-root-of-time
  volatility scaling is an approximation.

## Allocation rules shared by every strategy

- `sum(w) = 1`, `min_weight <= w_i <= max_weight` for every asset; long-only; no
  leverage, cash sleeve, taxes, or whole-share rounding.
- Bounds must satisfy `N * min_weight <= 1 <= N * max_weight`; the same bounds apply to
  every asset, so equal weight is always feasible.
- Portfolio metrics for any weight vector: return `mu . w`, variance `w' S w`,
  volatility `sqrt(w' S w)`, Sharpe `(mu . w - r_f) / volatility`. Sharpe is reported
  as null when volatility is at most 1e-12. The risk-free rate is an annual input
  (default 2%), not a live rate and not an asset.
- Risk contributions: `w_i * (S w)_i / (w' S w)`, signed fractions of portfolio
  variance that sum to one; they are not capital weights.

## The six strategies

| Strategy | How weights are chosen | Notes |
| --- | --- | --- |
| equal_weight | `w_i = 1/N` | No estimates needed to choose weights. Equal weight is not equal risk. Rebalanced back to equal at each backtest rebalance. |
| buy_and_hold | Equal weights at entry, then never rebalanced | Weights drift with prices; only the entry fee is charged. |
| inverse_volatility | `w_i` proportional to `1 / sigma_i` from the covariance diagonal, clipped to bounds and rescaled to sum to one | Ignores correlations. |
| minimum_variance | Minimize `w' S w` subject to the bounds (SLSQP) | Ignores expected returns and the risk-free rate. Minimizes the model's variance, not drawdown or crash risk. Does not simply pick the least volatile asset. |
| maximum_sharpe | Maximize `(mu . w - r_f) / sqrt(w' S w)` subject to bounds, via an equivalent quadratic program | Omitted with a warning when no feasible portfolio has positive excess return. Sensitive to noisy mean estimates; small changes in dates or assets can change weights materially. Maximum Sharpe is not maximum return. |
| equal_risk_contribution | Choose weights so every asset contributes equal variance, using the full covariance matrix | Approximate when bounds bind. |

## In-sample estimates versus walk-forward backtest

Two kinds of results exist and must not be conflated:

1. **Full-window (in-sample) portfolio estimates.** Weights and their expected
   return / volatility / Sharpe use every observation in the selected window. They
   answer "which allocation looks best under estimates from this dataset" and are
   not a simulation of what could have been known at the start.
2. **Walk-forward backtest.** At each rebalance the engine estimates returns and
   covariance from the trailing `lookback_days` return observations ending the
   observation before execution, computes target weights, executes at the next
   observed close, charges fees, and lets holdings drift until the next rebalance
   (every `rebalance_every` observations). Wealth starts at 1 in cash; the entry fee
   is charged on initial capital. Fees are `transaction_cost_bps` basis points of the
   full traded notional (buys plus sells); 10 bps = 0.10%. Turnover is full traded
   notional divided by pre-trade wealth, so the entry turnover is 1. Weight bounds
   apply to target weights at rebalances, not to drifting weights. If a rolling
   maximum-Sharpe fit fails, that strategy's whole backtest is omitted with a warning.

Backtest metrics use realized net returns `V[t] / V[t-1] - 1`:

- total_return: final wealth minus one.
- cagr: `final_wealth ^ (365.25 / elapsed_calendar_days) - 1` (geometric).
- annual_volatility: sample standard deviation of daily net returns times sqrt(252).
- sharpe_ratio: annualized mean excess daily return / annual volatility (arithmetic
  mean, not CAGR).
- sortino_ratio: like Sharpe but divides by downside deviation (root mean squared
  negative daily excess return across all observations, annualized).
- max_drawdown: most negative fraction below the running wealth peak (nonpositive).
- calmar_ratio: CAGR / |max_drawdown|.
- max_drawdown_duration_days: calendar days from a peak to recovery or to the end.
- total_turnover, total_transaction_cost: accumulated turnover and fees in
  initial-wealth units.
- Benchmark comparisons (when a benchmark ticker is set): the benchmark is a single
  buy-and-hold position on the same dates with the same entry fee. tracking_error is
  the sample volatility of active (portfolio minus benchmark) returns,
  information_ratio is annual mean active return / tracking error, and
  excess_total_return is the difference in net cumulative returns (not CAGR).
  Selecting a benchmark can shorten the common history.

## Efficient frontier and Monte Carlo

- The efficient frontier starts at the minimum-variance portfolio and solves
  minimum-variance problems at increasing expected-return floors up to the maximum
  feasible estimated return. All frontier points are in-sample.
- Monte Carlo points are feasible weight vectors from seeded hit-and-run sampling,
  shown to visualize alternatives; they are correlated, not uniform draws, and are
  not used to find the optimized portfolios.

## Block-bootstrap scenarios (forward-looking, not forecasts)

- Consecutive blocks of `block_days` historical daily returns are resampled with
  replacement to build `paths` hypothetical wealth paths over `horizon_days` calendar
  days for each strategy's fitted weights. Blocks preserve cross-asset dependence and
  short-run serial structure within a block.
- Fan-chart bands are cross-path wealth percentiles on each date. Percentile metrics
  (terminal return, terminal wealth, CAGR, max drawdown) are cross-sectional quantiles
  of resampled outcomes, not causal "5% scenarios".
- Outcomes are conditional on the fitted weights and the historical sample: if history
  contains no -30% day, no scenario will either. There is no volatility model (no
  GARCH/EWMA/regime switching); history is treated as stationary.

## Request parameters (AnalysisRequest)

- tickers: 2-30 uppercase provider symbols, unique. start_date/end_date: inclusive
  window, end not in the future, at most 20 years.
- base_currency: 3-letter code (default USD); every instrument must trade in it.
- strategies: one or more of the six names. min_weight (default 0), max_weight
  (default 1), risk_free_rate (annual fraction, default 0.02).
- monte_carlo_samples (0-5000, default 1000), frontier_points (0-50, default 20),
  random_seed (default 42).
- backtest: enabled (default true), lookback_days (60-1260 observations, default 252),
  rebalance_every (1-252 observations, default 21), transaction_cost_bps (0-500,
  default 10). A rebalance budget limits how many rebalances a run may require;
  lengthen rebalance_every or shorten the window if it is exceeded.
- benchmark_ticker: optional, requires an enabled backtest.
- scenario: enabled (default false in the API, true in the web form), horizon_days
  (21-1260 calendar days, default 252), block_days (1-63, default 5), paths
  (100-5000, default 1000), percentile_levels (default 5/25/50/75/95%).

## Interpreting results responsibly

- Historical averages are estimates, not forecasts; a different sample can produce
  different allocations.
- Diversification depends on co-movement; more tickers do not guarantee different
  exposures. Check the correlation matrix and risk contributions.
- Volatility is one risk measure; it does not fully describe crash, liquidity, or
  tail risk.
- Tight bounds make strategies more similar and can make positive excess return
  infeasible.
- Optimization does not remove overfitting or selection/survivorship bias from
  choosing assets and dates after seeing their performance.
- The simulation omits taxes, whole-share rounding, slippage, and market impact.
- Useful experiments: change one input at a time. Raising the risk-free rate leaves
  equal-weight and minimum-variance weights unchanged but changes their Sharpe;
  tightening max_weight limits concentration; changing the window shows estimation
  sensitivity; raising transaction costs leaves in-sample weights unchanged but lowers
  net backtest performance.
