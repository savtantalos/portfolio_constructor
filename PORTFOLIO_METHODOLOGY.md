# How Your App Builds Portfolios

A learning guide to **equal weight**, **minimum variance**, and **maximum Sharpe ratio**, based on this project's implementation.

The central question is: **What fraction of your money should go into each asset?** Each strategy answers that question differently.

| Strategy | Question it answers | Inputs used to choose weights |
| --- | --- | --- |
| Equal weight | What if I divide my money equally? | Number of assets |
| Minimum variance | Which allowed combination has the lowest estimated volatility? | Covariance matrix and weight limits |
| Maximum Sharpe | Which allowed combination has the highest estimated excess return per unit of volatility? | Expected returns, covariance matrix, risk-free rate, and weight limits |

All three use the same return and covariance estimates when the app calculates their displayed risk and return metrics. Equal weight does not need those estimates to **choose its allocation**.

## 1. Vocabulary and notation

- **Asset:** an equity or ETF you select.
- **Weight (`w_i`):** the fraction of portfolio value allocated to asset `i`. A weight of `0.25` means 25%.
- **Return (`r`):** percentage change in value, expressed as a decimal in the calculations.
- **Expected return (`mu_i` or `μ_i`):** here, an estimate calculated from historical average returns, not a guaranteed future return.
- **Variance:** a measure of how widely returns fluctuate around their average.
- **Volatility (`sigma` or `σ`):** the square root of variance. It measures both upward and downward fluctuations, not just losses.
- **Covariance:** how two assets' returns move together; it includes their individual scales of volatility.
- **Correlation (`rho` or `ρ`):** a standardized measure of co-movement between −1 and +1, when defined.
- **Risk-free rate (`r_f`):** an annual reference return used to calculate excess return.
- **`Σ` (capital sigma):** the covariance matrix, not a summation symbol in the matrix formulas below.

A weight is an allocation of **money**, not a count of shares. Equal dollar allocations usually buy different numbers of shares.

## 2. From prices to the inputs used by the strategies

### Step A: Obtain comparable historical prices

The Yahoo Finance provider uses daily **adjusted closing prices**, accounting for splits and cash dividends under the provider's adjustment convention. Dividends are therefore not added a second time.

The app:

1. Requires every instrument to be quoted in the selected base currency; it does not convert currencies.
2. Keeps only dates with prices for every selected asset.
3. Does not forward-fill missing prices.
4. Requires at least 61 complete price observations, giving 60 returns. An enabled backtest needs more history, as explained later.

This common set of dates is important: covariance should compare returns over matching periods.

### Step B: Calculate simple returns

For asset `i` at observation `t`:

```text
r[t, i] = P[t, i] / P[t−1, i] − 1
```

For example, an adjusted price rising from 100 to 102 produces:

```text
102 / 100 − 1 = 0.02 = 2%
```

These are **simple/arithmetic returns**, not logarithmic returns. After date alignment, consecutive observations can occasionally span more than one trading day; the app still treats each as one return observation.

### Step C: Estimate annual expected returns

For each asset, average its observed returns and multiply by 252:

```text
mu_i = 252 × mean(r[:, i])
```

A mean daily return of `0.0004` gives an estimated annual arithmetic return of `0.1008`, or 10.08%.

**This is not CAGR.** It does not compound the daily average. For example, +10% followed by −10% has a zero arithmetic average, but wealth falls from 100 to 99. Arithmetic averages and compounded growth answer different questions.

### Step D: Estimate covariance with Ledoit–Wolf shrinkage

The covariance matrix contains:

- Each asset's variance on the diagonal.
- Covariance between different assets off the diagonal.

A covariance matrix estimated directly from limited data can be noisy, particularly when assets behave similarly. An optimizer can exploit that noise and produce fragile weights.

The app uses scikit-learn's **Ledoit–Wolf estimator**, which blends the empirical covariance matrix with a simpler target:

```text
C_shrunk = (1 − alpha) × C_empirical + alpha × tau × I

tau   = average diagonal variance of C_empirical
I     = identity matrix
alpha = shrinkage intensity estimated from the data
```

The target has equal diagonal variances and zero off-diagonal covariances. Shrinkage pulls the empirical estimates toward that target; it does not assume the actual assets are independent. Scikit-learn centers returns and uses an empirical covariance normalization of `1 / number_of_observations` here, so this is not just the usual sample covariance with a `1 / (n−1)` denominator.

The app then annualizes:

```text
Σ = 252 × LedoitWolf().fit(returns).covariance_
```

This is intended to stabilize risk estimation. It does not remove estimation error or guarantee a nonsingular matrix for every possible dataset.

The factor 252 assumes approximately 252 trading observations per year. Linear variance scaling, and therefore square-root-of-time volatility scaling, are approximations that can be affected by serial dependence and missing-date alignment.

## 3. Shared allocation rules and portfolio metrics

### Allowed weights

All strategies are long-only and fully invested:

```text
w_1 + w_2 + ... + w_N = 1
min_weight <= w_i <= max_weight
```

The backend defaults are `min_weight = 0` and `max_weight = 1`. You can change them. The same lower and upper limits apply to every asset.

- No negative weights: no short selling.
- Weights sum to 100%: no borrowing or separate cash allocation in the constructed portfolio.
- Fractional allocations are allowed: the app does not round to whole shares.

Feasible common bounds must satisfy:

```text
N × min_weight <= 1 <= N × max_weight
```

For example, four assets with a maximum of 20% each are infeasible: they can hold only 80% in total. Because the limits are common to all assets, feasible bounds also contain the equal-weight allocation `1/N`, apart from tiny validation tolerances.

### Metrics for any weight vector

```text
Estimated annual return = muᵀw = sum_i(mu_i × w_i)
Annual variance         = wᵀΣw
Annual volatility       = sqrt(wᵀΣw)
Sharpe ratio            = (muᵀw − r_f) / sqrt(wᵀΣw)
```

The superscript `ᵀ` means transpose. In Python/NumPy, these calculations use `mu @ weights` and `weights @ covariance @ weights`.

**Portfolio volatility is not generally the weighted average of individual volatilities.** Covariances matter. For two assets:

```text
Portfolio variance = w_A² × sigma_A²
                   + w_B² × sigma_B²
                   + 2 × w_A × w_B × rho_AB × sigma_A × sigma_B
```

This last term explains diversification: assets that do not move perfectly together can reduce combined volatility.

The backend's default annual risk-free rate is `0.02`, or 2%. It is an input, not a live interest-rate feed, and it is not an extra asset in the allocation. The app reports Sharpe as undefined (`None`/JSON `null`) when volatility is at most `1e−12`.

## 4. Equal-weight portfolio

### Idea

Give every asset the same share of the money:

```text
w_i = 1 / N
```

With four assets and a portfolio worth 10,000, each receives 25%, or 2,500.

### What the app does

It constructs the weights directly:

```python
equal = np.full(count, 1 / count)
```

There is no optimizer and no ranking of assets. Historical returns and covariance are used afterward to calculate the portfolio's estimated metrics.

### What to learn from it

- It is simple and does not depend on estimated expected returns to choose weights.
- It is a useful benchmark for judging whether optimization adds value.
- **Equal weight does not mean equal risk.** A volatile asset can contribute much more risk than a stable asset with the same weight.
- It does not promise the lowest risk or the highest return.

In the backtest, equal weights are restored at scheduled rebalances. Between rebalances, weights drift as prices change.

## 5. Minimum-variance portfolio

### Idea

Choose the allowed allocation with the smallest estimated portfolio variance:

```text
minimize    wᵀΣw

subject to  sum_i(w_i) = 1
            min_weight <= w_i <= max_weight
```

Minimizing variance also minimizes volatility because the square root is increasing.

Notice what is absent from the objective: **expected returns and the risk-free rate**. The standalone minimum-variance strategy does not try to reach a target return.

### What the app does

1. Starts from equal weights.
2. Uses SciPy's SLSQP constrained optimizer.
3. Supplies the variance objective and its gradient, `2 × Σ × w`.
4. Enforces the weight sum and limits.
5. Checks that the resulting weights are finite, sum to one, and satisfy the limits within numerical tolerance.

The covariance matrix is divided by a positive scale for numerical stability. Multiplying the entire objective by a positive constant does not change the minimizing weights. The solver uses `ftol=1e−12` and up to 1,000 iterations; ordinary weight feasibility checks allow a tolerance of `1e−7`.

If the constraints effectively fix the allocation, or the covariance matrix is entirely zero, the implementation can return the initial feasible allocation without an optimizer run. A zero covariance matrix makes every feasible allocation equally good for this objective.

### What to learn from it

It does **not** simply choose the least volatile asset. An asset with higher individual volatility can still reduce overall variance if its co-movement with the others is favorable.

It minimizes the risk measure used by this model, not every form of financial risk. It does not directly minimize maximum drawdown, losses during a crash, or the probability of losing money.

## 6. Maximum-Sharpe-ratio portfolio

### Idea

Choose the allowed allocation with the highest estimated excess return per unit of volatility:

```text
maximize    (muᵀw − r_f) / sqrt(wᵀΣw)

subject to  sum_i(w_i) = 1
            min_weight <= w_i <= max_weight
```

For example, estimated return of 10%, risk-free rate of 2%, and volatility of 16% gives:

```text
Sharpe = (0.10 − 0.02) / 0.16 = 0.50
```

Sharpe is a ratio, not a percentage. A value of 0.50 means 0.5 units of estimated excess return per unit of volatility.

**Maximum Sharpe is not maximum return.** A portfolio with a lower expected return can have a higher Sharpe ratio if its volatility is sufficiently lower.

### First: check whether positive excess return is feasible

The app defines each asset's excess return:

```text
a_i = mu_i − r_f
```

Because weights sum to one, portfolio excess return is `aᵀw`.

The code first finds the highest achievable excess return under the weight limits. It starts at the minimum weights and assigns remaining capacity to assets with the highest excess returns.

If this maximum is at most `1e−12`, the app **omits maximum Sharpe and returns a warning**. Even if one asset beats the risk-free rate, the weight limits may force enough money into other assets that no feasible portfolio does.

This is an implementation choice: the app does not attempt to select the best negative-Sharpe portfolio.

### Then: solve an equivalent quadratic problem

This is the more technical part; you can skip to the worked example on a first reading.

Instead of directly optimizing a ratio, the app transforms the positive-excess-return problem. Let:

```text
E = highest feasible portfolio excess return
b = a / E
Q = Σ / max(maximum absolute entry of Σ, 1e−30)
```

It solves for temporary variables `y`:

```text
minimize    yᵀQy

subject to  bᵀy = 1
            y_i >= 0
            y_i >= min_weight × sum_j(y_j)
            y_i <= max_weight × sum_j(y_j)
```

Then it converts back to portfolio weights:

```text
w_i = y_i / sum_j(y_j)
```

Why this works: any feasible weight vector with positive excess return can be transformed by `y = w / (bᵀw)`. Before the harmless covariance scaling:

```text
yᵀΣy = E² × (wᵀΣw) / (aᵀw)²
       = E² / Sharpe(w)²
```

For positive Sharpe and nonzero variance, minimizing this objective is equivalent to maximizing Sharpe. The transformed weight limits ensure normalization produces an allowed portfolio.

This is a convex quadratic formulation with linear constraints for the estimated positive-semidefinite covariance matrix. The app solves it with SLSQP, then validates the transformed solution and the final weights. It does **not** choose the highest-Sharpe point from random Monte Carlo samples.

### What to learn from it

Maximum Sharpe depends on both estimated returns and covariance. Historical average returns can be particularly noisy, so small changes to the date range or asset list can materially change the weights. The highest in-sample Sharpe is not a guarantee of the best future performance.

## 7. Worked example: the same two assets, three different answers

These are **invented annual inputs for teaching**, not actual market data or recommendations. Treat the covariance matrix as an already-estimated input; a real analysis would estimate it from prices using Ledoit–Wolf.

| Input | Asset A | Asset B |
| --- | ---: | ---: |
| Estimated annual return | 8% | 14% |
| Annual volatility | 10% | 20% |

Assume correlation is `0.20`, the annual risk-free rate is 2%, and weights may range from 0% to 100%.

The covariance is:

```text
Cov(A, B) = 0.20 × 0.10 × 0.20 = 0.004

Σ = [ 0.010   0.004 ]
    [ 0.004   0.040 ]
```

### Equal weight

```text
w_A = 0.50
w_B = 0.50

Return   = 0.50 × 0.08 + 0.50 × 0.14 = 0.11
Variance = 0.50² × 0.01 + 0.50² × 0.04 + 2 × 0.50 × 0.50 × 0.004
         = 0.0145
Vol      = sqrt(0.0145) ≈ 0.120416
Sharpe   = (0.11 − 0.02) / 0.120416 ≈ 0.7474
```

### Minimum variance

For two assets, with neither weight limit binding, the solution can be written as:

```text
w_A = (variance_B − covariance_AB)
      / (variance_A + variance_B − 2 × covariance_AB)

    = (0.040 − 0.004) / (0.010 + 0.040 − 0.008)
    = 6/7 ≈ 0.857143

w_B = 1/7 ≈ 0.142857
```

The app uses constrained optimization rather than this special two-asset formula. Here, both give the same answer.

### Maximum Sharpe

For this example, the solution is:

```text
w_A = 2/3 ≈ 0.666667
w_B = 1/3 ≈ 0.333333
```

One way to check this special case is to calculate `z = inverse(Σ) × (mu − r_f)` and normalize `z` to sum to one. Here, `z = [5, 2.5]`, giving `[2/3, 1/3]`.

That shortcut requires an invertible covariance matrix, a suitable positive-excess solution, and weights that satisfy the limits. It is **not** the general constrained method used by the app.

### Compare the results

The following values were checked using the project's actual allocation and metric functions with the inputs above:

| Strategy | Weight A | Weight B | Estimated annual return | Annual volatility | Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| Equal weight | 50.00% | 50.00% | 11.00% | 12.04% | 0.7474 |
| Minimum variance | 85.71% | 14.29% | 8.86% | 9.56% | 0.7171 |
| Maximum Sharpe | 66.67% | 33.33% | 10.00% | 10.33% | 0.7746 |

The lessons:

- Minimum variance has the lowest volatility, even lower than Asset A alone.
- Maximum Sharpe has the highest Sharpe, but not the highest expected return.
- Equal weight has the highest expected return **among these three portfolios in this example**, not among every feasible portfolio: 100% in B would have a 14% expected return.
- These rankings are not predictions. Only the optimized objective is targeted, using the supplied estimates and constraints.

## 8. Estimated metrics versus the rolling backtest

The app produces two different kinds of results. Do not interpret them as interchangeable.

### Full-window portfolio estimates

The main allocation weights and their expected return, volatility, and Sharpe are calculated from **all observations in your selected historical window**.

They answer: “Which allocation looks best under estimates from this dataset?” They are in-sample estimates, not a simulation of what you could have known at the beginning of that window.

### Walk-forward backtest

The backtest repeatedly estimates weights using only earlier data, then applies those weights to subsequent returns.

Backend defaults, unless overridden:

| Setting | Default |
| --- | --- |
| Backtest enabled | Yes |
| Lookback | 252 return observations |
| Rebalance interval | 21 trading observations |
| Transaction cost | 10 basis points of traded notional |

One basis point is 0.01%, so 10 basis points is 0.10%, or `0.001`.

At a rebalance:

1. Estimate returns and covariance from the trailing lookback window ending at the observation **before** execution.
2. Calculate the strategy's target weights.
3. Execute at the next observed close, excluding the return into that execution close from the estimation window.
4. Charge the modeled trading fee.
5. Let the new holdings earn only subsequent returns and drift until the next rebalance.

For example, if training data end at Monday's close and Tuesday is the next observation, the target is executed at Tuesday's close. It does not receive Monday-to-Tuesday gains; it starts earning returns after Tuesday's close.

The backtest needs at least `lookback_days + 3` prices: 255 at the default lookback. This includes estimation history, the execution lag, and at least one subsequent realized return.

Initial wealth is normalized to 1 and stays in cash until entry. The entry fee is charged on initial capital before investing the remainder. At later rebalances, fees are charged on the **sum of the absolute buy and sell amounts**, with post-fee holdings solved consistently. Selling 10 units and buying 10 units is 20 units of traded notional, not 10.

Weight limits apply to target allocations, not continuously to weights that drift between rebalances. Transaction costs affect backtest wealth but are not included in the allocation optimizer's objective.

If a rolling maximum-Sharpe window fails, including when no positive excess return is feasible, the app omits that strategy's entire backtest with a warning rather than silently switching to another strategy.

### Backtest metrics are calculated from realized net returns

```text
net_return[t] = wealth[t] / wealth[t−1] − 1

Realized annual volatility = sample_std(net_returns) × sqrt(252)
Realized Sharpe            = (mean(net_returns) − r_f / 252) × 252
                             / realized_annual_volatility
CAGR                       = final_wealth^(365.25 / elapsed_calendar_days) − 1
```

CAGR assumes the starting wealth of 1 used by the app. Realized volatility uses sample standard deviation (`ddof=1`), not the Ledoit–Wolf covariance estimate used for the main portfolio metrics. The Sharpe calculation uses arithmetic mean returns, **not CAGR**.

## 9. How the other charts relate to these methods

- **Efficient frontier:** starts at the minimum-variance portfolio. The app then solves minimum-variance problems with increasing expected-return floors. Its last point is the lowest-variance allocation among those attaining the maximum feasible estimated return.
- **Monte Carlo points:** sampled feasible weight combinations that help visualize alternatives. These use seeded hit-and-run sampling; they are not guaranteed independent uniform draws and are not the method used to find the optimized portfolios.
- **Correlation matrix:** ordinary historical return correlations. The displayed correlations are not derived from the shrunk covariance matrix, so combining that chart with volatility estimates may not reconstruct the optimizer's covariance exactly.
- **Risk contributions:** calculated as `w_i × (Σw)_i / (wᵀΣw)`. They are signed fractions of total portfolio variance, not capital weights. They sum to one for non-negligible variance and can be negative when an asset offsets risk; the app reports zeros when variance is negligible.

## 10. How to interpret the results responsibly

1. **Historical averages are estimates, not forecasts.** A different sample can produce different allocations.
2. **Diversification depends on co-movement.** More tickers do not necessarily mean meaningfully different exposures.
3. **Volatility is only one risk measure.** It does not fully describe crash risk, liquidity risk, or the size of possible losses.
4. **Constraints matter.** Tight weight limits can make strategies more similar and can prevent positive excess return.
5. **Optimization does not remove overfitting.** Choosing assets and dates after seeing their performance can bias conclusions, even with a rolling backtest.
6. **The simulation has limits.** It omits taxes, whole-share rounding, execution slippage, and market impact. It uses a fixed input risk-free rate and today's selected asset list, which can introduce selection/survivorship bias.

A useful learning exercise is to keep the assets and dates fixed, then change one input at a time:

- Increase the risk-free rate: equal-weight and minimum-variance **weights** should stay unchanged, but their Sharpe metrics change. Maximum-Sharpe weights may change, or the strategy may become unavailable.
- Tighten the maximum weight while keeping the bounds feasible: observe how it limits concentration.
- Change the date window: observe how historical estimation affects the optimized weights.
- Increase transaction costs: full-window allocation weights stay unchanged, but net backtest performance changes.

## 11. Where to read the implementation

Paths below are relative to this document.

| Topic | Source and function/class |
| --- | --- |
| Adjusted prices, common dates, currency checks | [portfolio_backend/market_data.py](portfolio_backend/market_data.py): `YahooFinanceProvider.history`, `_prices`, `_instrument` |
| Strategy names, defaults, feasible bounds | [portfolio_backend/models.py](portfolio_backend/models.py): `Strategy`, `AnalysisRequest`, `BacktestConfig` |
| Price-to-return calculation | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `_validate` |
| Annual means and Ledoit–Wolf covariance | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `_estimate` |
| Equal weight and maximum Sharpe | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `_weights`, `_max_return` |
| Minimum variance and optimizer | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `_minimum_variance`, `_solve` |
| Estimated portfolio metrics | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `_point` |
| Walk-forward backtest and fees | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `_backtest`, `_post_fee_wealth` |
| Integration, warnings, risk contributions | [portfolio_backend/analytics.py](portfolio_backend/analytics.py): `analyze` |
| Automated methodology checks | [tests/test_analytics.py](tests/test_analytics.py) |

**The short version:** equal weight divides capital equally; minimum variance minimizes estimated fluctuations; maximum Sharpe maximizes estimated excess return per unit of those fluctuations. The app evaluates all three using a shared historical-data pipeline, but none guarantees future performance.
