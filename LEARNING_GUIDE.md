# Learning Guide: The Math Behind This App

A curriculum for understanding everything the analytics engine does, ordered so each
stage builds on the previous one. Companion to `PORTFOLIO_METHODOLOGY.md`, which
explains the methodology in detail — this file tells you *what to learn* and maps
each topic to the code.

> **Important:** the app does not use GARCH and does not forecast. The
> forward-looking feature is **block-bootstrap scenario simulation**, which
> resamples historical returns rather than predicting anything. Stage 8 explains
> the difference and where GARCH would fit if you added it later.

## Prerequisites

You can skip anything you already know.

- **Algebra & matrix notation:** vectors, dot products, matrix multiplication,
  transpose (`ᵀ`). The core formulas are `muᵀw` and `wᵀΣw`.
- **Basic statistics:** mean, variance, standard deviation, covariance,
  correlation, percentiles.
- **Basic optimization:** the idea of minimizing a function subject to
  constraints (bounds, equality constraints).
- **Python/NumPy:** array slicing, broadcasting, `a @ b` matrix multiplication.

## Stage 1 — Market data and returns

**What the code does:** fetches daily *adjusted* closing prices from Yahoo
Finance, aligns all assets on common dates, and converts prices to returns.
Code: `market_data.py`, `_validate` in `portfolio_backend/analytics.py`.

**Learn:**

- What an *adjusted close* is: prices corrected for splits and dividends, so a
  dividend payment doesn't look like a crash.
- **Simple (arithmetic) returns**: `r_t = P_t / P_{t-1} - 1`. The app uses
  these everywhere. Contrast with **log returns** (`ln(P_t / P_{t-1})`) — good
  to know both exist; simple returns are what a portfolio's wealth actually
  experiences per day.
- **Annualization conventions:** mean daily return × 252, volatility × √252.
  Understand why variance scales linearly with time under independence
  (which is why volatility scales by the square root). This is an
  approximation — worth understanding its limits.
- Why "keep only dates where every asset has a price" matters: correlation
  is only meaningful over matching periods.

**Check yourself:** an asset rises 10% then falls 10%. What's the arithmetic
average daily return? What happened to your money? (Answer: 0% average, but
100 → 99. This is the arithmetic vs. geometric distinction, central to
CAGR later.)

## Stage 2 — Correlation and covariance

**What the code does:** computes the Pearson correlation matrix of daily
returns for the heatmap, and estimates the covariance matrix (with shrinkage)
that drives all optimization.
Code: `analyze` (correlation block), `_estimate`.

**Learn:**

- **Covariance vs. correlation:** correlation is covariance rescaled to
  [−1, +1]: `ρ_AB = Cov(A,B) / (σ_A σ_B)`.
- The **covariance matrix** Σ: variances on the diagonal, covariances off it.
- **Why covariance is the heart of diversification:** two-asset portfolio
  variance is `w_A²σ_A² + w_B²σ_B² + 2w_Aw_Bρ_ABσ_Aσ_B`. The cross term is
  where diversification lives.
- **Estimation error:** a sample covariance matrix from limited data is noisy,
  and optimizers exploit that noise to produce fragile weights. This motivates:
- **Ledoit–Wolf shrinkage:** blend the empirical covariance with a simple
  structured target: `C_shrunk = (1−α)·C_empirical + α·τ·I`. Learn what the
  shrinkage intensity α means and why shrinking toward a diagonal target
  stabilizes results. (The original 2004 Ledoit & Wolf paper "A
  well-conditioned estimator for large-dimensional covariance matrices" is
  the canonical reference.)
- Note the subtlety: the **displayed correlation matrix is raw Pearson** — it
  is *not* derived from the shrunk covariance the optimizer uses. Two
  different views of the same data.

## Stage 3 — Portfolio math

**What the code does:** given a weight vector, computes expected return,
volatility, Sharpe ratio, and per-asset risk contributions.
Code: `_point`, `analyze` (risk contributions).

**Learn:**

- The three formulas the whole app is built on:
  - `expected return = muᵀw`
  - `variance = wᵀΣw`, `volatility = √(wᵀΣw)`
  - `Sharpe = (muᵀw − r_f) / √(wᵀΣw)`
- Why portfolio volatility is **not** the weighted average of individual
  volatilities.
- **Risk contribution:** asset `i`'s share of portfolio variance is
  `w_i · (Σw)_i / wᵀΣw`. These sum to 1. This is the foundation for the
  equal-risk-contribution strategy later.

## Stage 4 — The six allocation strategies

**What the code does:** produces a weight vector per strategy under common
bounds (`min_weight ≤ w_i ≤ max_weight`, weights sum to 1, long-only).
Code: `_weights` and its helpers.

Learn each strategy's idea and the math it requires:

| Strategy | Core idea | Math to learn |
| --- | --- | --- |
| Equal weight | `w_i = 1/N` | Nothing — but learn why equal weight ≠ equal risk |
| Buy and hold | Equal weight at entry, then drift | How weights drift as prices change |
| Inverse volatility | `w_i ∝ 1/σ_i`, clipped to bounds | Why it ignores correlations (uses only Σ's diagonal); the `brentq` root-find that rescales to a unit sum |
| Minimum variance | `min wᵀΣw` s.t. constraints | **Quadratic programming**; what `Σw` in the gradient means |
| Maximum Sharpe | `max (muᵀw − r_f)/√(wᵀΣw)` | The **fractional→QP transformation** (`y = w/(bᵀw)`) that converts a ratio maximization into a QP |
| Equal risk contribution | All assets contribute equal variance | The squared-deviation objective and its Jacobian |

**The deeper topic underneath:** constrained convex optimization. The app uses
SciPy's **SLSQP** (Sequential Least Squares Programming) with analytically
supplied gradients. Learn:

- What a convex quadratic program is and why `wᵀΣw` is convex when Σ is
  positive semidefinite.
- Why bounds and the `Σw_i = 1` constraint define a polytope (the "bounded
  simplex").
- Why the max-Sharpe problem needs the transformation trick: maximizing a
  ratio isn't a QP, but the positive-excess-return case can be transformed
  into one. `PORTFOLIO_METHODOLOGY.md` §6 walks through this.

## Stage 5 — Efficient frontier and Monte Carlo

**What the code does:** traces the efficient frontier by solving
minimum-variance problems at increasing return floors, and samples random
feasible portfolios for visualization.
Code: `_frontier`, `_sample`.

**Learn:**

- **Markowitz mean-variance theory:** the efficient frontier is the set of
  minimum-variance portfolios at each achievable return level. This is the
  conceptual framework behind Stages 3–5 — worth studying as a unit (it is
  *the* foundational result of portfolio theory).
- How "minimize variance subject to a return floor" is just Stage 4's QP plus
  one inequality constraint.
- **Hit-and-run sampling** (the Monte Carlo dots): pick a random direction,
  find the feasible interval along that line inside the bounded simplex, jump
  to a random point on it, repeat. Learn the ideas of *burn-in* and
  *thinning* — and why finite chains produce correlated, non-uniform samples
  (the app warns about this).

## Stage 6 — Backtesting

**What the code does:** simulates what each strategy *would have done*,
re-estimating weights on rolling lookback windows, executing at the next
close, and charging transaction costs.
Code: `_backtest`, `_backtest_metrics`, `_post_fee_wealth`.

**Learn:**

- **Walk-forward evaluation** and why it matters: in-sample weights are fit on
  all the data, so they can't be evaluated on that same data. Backtests use
  only past data at each decision point — this is the closest the app comes
  to an honest performance estimate.
- **Look-ahead bias and the execution lag:** estimates use data through the
  close *before* execution; the target earns only returns after the execution
  close. Learn why this subtlety is the difference between a realistic and a
  fantasy backtest.
- **Transaction costs:** basis points (1 bp = 0.01%), charged on full traded
  notional (buys + sells). The post-fee wealth is solved self-consistently
  with a 1-D root find (`brentq`) because the fee itself changes the wealth
  being allocated.
- **Turnover** and why it divides notional by pre-trade NAV.
- The **performance metrics** the backtest reports:
  - Total return and **CAGR** (geometric growth — contrast with Stage 1's
    arithmetic mean)
  - Realized volatility (sample std × √252 — note `ddof=1`, a different
    estimator than Ledoit–Wolf)
  - **Sharpe** vs **Sortino** (downside deviation only) vs **Calmar**
    (CAGR / max drawdown)
  - **Maximum drawdown** and drawdown duration
  - **Tracking error** and **information ratio** vs. a benchmark

## Stage 7 — Forward-looking: block bootstrap scenarios

**What the code does:** generates thousands of hypothetical future wealth
paths by stitching together randomly resampled blocks of historical returns,
then reports percentile bands (the fan chart), terminal-wealth statistics, and
drawdown distributions per strategy.
Code: `_scenarios`; frontend `ScenarioChart` / `ScenarioTable`.

**Learn:**

- **Bootstrapping** generally: resampling observed data with replacement to
  approximate a sampling distribution. The bootstrap answer to "what range of
  outcomes could history's return distribution produce?"
- Why **blocks** (`block_days`, default 5): single-day i.i.d. resampling would
  destroy the serial dependence real returns have (volatility clustering,
  short-term momentum/mean-reversion). Resampling *consecutive* blocks
  preserves cross-asset dependence and within-block serial structure.
- **Percentiles across paths:** the 5th-percentile wealth path is not "the
  portfolio's 5% scenario" in a causal sense — it's the cross-sectional
  quantile of resampled outcomes.
- Read the caveats the code itself prints: outcomes are **conditional on the
  fitted weights and the historical sample distribution**. If history contains
  no −30% day, no scenario will either. This is the key limitation to
  understand.

## Stage 8 — GARCH: what's *not* in the code

The app has **no volatility model** — no GARCH, no EWMA, no regime switching.
The bootstrap assumes the historical return distribution (within blocks) is a
good stand-in for the future, period.

**Where GARCH fits conceptually:**

- Real markets show **volatility clustering**: calm days follow calm days,
  crashes cluster. A block bootstrap partially preserves this *within* a
  block, but treats history as stationary and can't express "volatility is
  elevated *now*."
- **GARCH(1,1)** models conditional variance recursively:
  `σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}` — today's variance depends on
  yesterday's shock and yesterday's variance. Learn: what ε (the residual)
  is, why α and β sum to less than 1 for stationarity, and how the model is
  fit by maximum likelihood.
- If you ever extended this app: a GARCH-filtered bootstrap (resample
  standardized residuals, scale by forecast σ) would produce paths that
  reflect *current* volatility conditions rather than unconditional history.
  That's the natural next step from `_scenarios` toward actual forecasting.

**Topics to learn if you go this direction:** conditional vs. unconditional
variance, maximum likelihood estimation, standardized residuals, and the
stationarity/ARCH-effect tests that justify the model.

## Stage 9 — Supporting engineering concepts

These appear throughout `analytics.py` and are worth knowing:

- **`brentq` / numerical root-finding:** used for inverse-volatility rescaling
  and the transaction-cost equation — a 1-D solver for "find x such that
  f(x) = 0."
- **Numerical conditioning:** covariance matrices are scaled before
  optimization (multiplying an objective by a positive constant doesn't
  change the argmin), tolerances like `1e-7` guard feasibility checks.
- **Seeded RNGs:** `np.random.default_rng(seed)` makes Monte Carlo and
  bootstrap results reproducible.
- **Pydantic validation:** `models.py` encodes domain constraints (e.g.
  `N × min_weight ≤ 1 ≤ N × max_weight` feasibility, 20-year window cap)
  declaratively.
- **Snapshots & provenance:** the export system saves the price snapshot and
  its SHA-256 so an analysis is reproducible — exports never recompute
  (`exports.py`).

## Suggested order of study

1. Stage 1 (returns) → Stage 2 (correlation/covariance) — the data layer
2. Stage 3 (portfolio math) — the three formulas
3. Stage 4 (strategies), reading `_weights` alongside
4. Stage 6 (backtesting) — before Stage 5 if you're short on time; it matters more practically
5. Stage 5 (frontier/Monte Carlo)
6. Stage 7 (bootstrap scenarios)
7. Stage 8 (GARCH) only if you want to extend the engine

**Reference texts:** for Stages 2–5, any Markowitz/modern-portfolio-theory
treatment (e.g. chapters of Bodie, Kane & Marcus, *Investments*); for Stage 7,
Efron & Tibshirani's bootstrap literature; for Stage 8, Engle's original ARCH
paper or the `arch` Python package docs.
