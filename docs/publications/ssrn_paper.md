# An Auditable Agent Harness for Infrastructure Cash-Flow Forecasting: A Reproducible Synthetic Experiment

**Dmitry Kazakov**

24 October 2026

## Abstract

Infrastructure cash-flow forecasts must account for uncertain construction and operating outcomes within contractual financing limits. This study presents a reproducible prototype combining a cash-and-debt ledger, a statistical correction to an existing project plan, and an agent harness that controls tool use and records results. An experiment with twelve seeded realisations of three synthetic regimes uses 840 rolling forecast origins and pools lead times of one to three months. The corrected plan achieves MAE of RUB 10.29 million, compared with RUB 20.68 million for the unchanged plan and RUB 24.37 million for a last-observation benchmark. Correction improves eight realisations but worsens all four unbiased-plan cases. A separate scenario illustration identifies a funding shortfall despite positive terminal cash. Simulated cash-balance quantiles describe the assumed model; their empirical coverage has not been established. The results demonstrate reproducible calculations and the behaviour of a simple adaptive rule on synthetic data. They do not establish accuracy on actual infrastructure projects or the quality of a live language-model planner.

**Keywords:** infrastructure finance; cash-flow forecasting; project finance; agent harness; auditability; scenario analysis; time-series evaluation.

## 1. The forecasting problem

Positive lifetime value does not ensure that a project can meet each payment when it falls due. Construction outflows may precede operating receipts, while credit availability can expire before delayed work is completed. A useful forecast must therefore connect project performance with the timing and limits of financing.

The World Bank distinguishes construction, operating, demand and collection risks [2]. Its project-finance guidance defines periodic debt-service coverage by relating available cash to interest and principal obligations over the same period [1]. These distinctions guide the model's economic structure.

The study examines whether an explicit ledger, a simple plan correction and controlled tool execution can produce a forecast that can be reconstructed and checked. It also tests when recent component deviations improve an unchanged plan. The method combines established techniques. The contribution is their executable integration and a controlled account of its strengths and failures.

## 2. Cash and debt model

Let T denote the forecast origin and t a subsequent month. R_t denotes operating cash receipts, O_t cash operating expenditure, T_t cash taxes, M_t maintenance CAPEX and K_t construction CAPEX. Financing comprises equity E_t, debt drawings D_t, interest I_t and principal service P_t. C_t and B_t are closing cash and debt.

`CFADS_t = R_t - O_t - T_t - M_t`.

`FCF_t = CFADS_t - K_t`.

`C_t = C_(t-1) + FCF_t + E_t + D_t - I_t - P_t`.

`B_t = B_(t-1) + D_t - P_t`.

`DSCR_t = CFADS_t / (I_t + P_t)`.

The chosen CFADS definition deducts maintenance CAPEX and excludes construction CAPEX. A transaction-specific implementation must follow the financing documents, including their treatment of reserves and adjustments. Equity and borrowing provide liquidity but do not enter operating receipts or CFADS.

Interest equals opening debt multiplied by the nominal annual rate divided by twelve. Month-end drawings affect interest from the following month. Future scheduled principal is capped by opening debt. An observed principal payment above opening debt is rejected, including when historical drawings and interest must be reconstructed. Cash shortage does not reduce scheduled service to manufacture a better DSCR. Where service is zero, DSCR is null.

The facility is non-revolving: headroom depends on cumulative drawings, and repayment does not restore commitment. Drawings also cease after the availability date. The reported funding gap measures the shortfall against a minimum cash target, which can occur while cash remains positive. Negative projected cash records unmet financing; the engine does not insert uncommitted equity, refinancing or an authorised overdraft.

Monthly DSCR is a diagnostic. A covenant may require a different cash definition and quarterly, semiannual, annual or forward-looking aggregation. Cash and obligations should be aggregated to that period; averaging monthly ratios generally gives a different answer.

## 3. Information and estimation

### 3.1 Data available at each origin

The inputs comprise a frozen plan p_(j,t) and observed components x_(j,t). Only observations through T enter correction estimates and starting-state reconstruction. Future synthetic outcomes are retained for evaluation.

Plan revisions also carry information. Using a later revised plan at an earlier origin introduces hindsight even if future actuals are excluded. The experiment fixes the plan before generating observations. The current schema checks the plan vintage and filters actuals by economic month, but does not store each observation's availability timestamp or a history of plan revisions. Reporting lags and historical availability must be controlled upstream.

Inputs use nonnegative amounts for separately identified inflows and outflows, all in millions of roubles. Validation checks dates, ordering, required fields, numerical finiteness and financing parameters. Recorded historical drawings and interest can be supplied; otherwise the model reconstructs financing and flags that assumption. Input hashes, settings, the cutoff and software version allow reconstruction of a run, without certifying the truth of the source records.

### 3.2 Component correction

For planned values above 10⁻⁹, define:

`r_(j,t) = x_(j,t) / p_(j,t)`.

The estimator retains the twelve most recent eligible observations and clips ratios to [0, 5], recording the number clipped. Weights decrease by 0.85 per older active observation and are normalised to sum to n. A prior weight of three at ratio one limits changes supported by a short history:

`m_(j,T) = 1 + lambda_(j,T) * (rbar_(j,T) - 1)`,

`lambda_(j,T) = n / (n + 3)`.

Here rbar is the weighted mean of clipped ratios. Future component forecasts equal the scenario-adjusted plan multiplied by m_(j,T). When n is zero, the multiplier is one. The rule applies separately to receipts, construction CAPEX, OPEX, cash taxes and maintenance CAPEX. Equity and principal schedules remain explicit commitments or scenario assumptions.

This estimator can track persistent deviations, but it does not identify their causes. Before operations begin, there is no project-specific receipt history to learn from. Multiplication also preserves a zero future plan value, so unexpected expenditure or a new commissioning date requires an explicit schedule change. The numerical ledger can be retained when replacing this baseline with a different estimator.

## 4. Scenarios and uncertainty

The delay_months parameter shifts all remaining construction and operating cash schedules, including CAPEX, receipts, OPEX, taxes and maintenance. Equity, principal dates and facility availability remain fixed. It represents a suspension of remaining activity, not every possible form of commissioning delay.

The CAPEX multiplier affects construction and maintenance expenditure. Receipt and OPEX multipliers and an annual-rate shift are separate inputs. Collection lags, work-package dependencies, standby costs, penalties and compensation require more detailed schedules. Any cash flows shifted beyond the reporting horizon are disclosed separately, so a deferred obligation is not mistaken for a saving.

For uncertainty analysis, correlated lognormal perturbations modify projected components before they enter the financial equations. Normal innovations combine common and component-specific factors, with common variance share 0.35. A stationary AR(1) process with coefficient 0.65 supplies temporal dependence. A persistent perturbation represents uncertainty in the component multiplier. The exponent adjustment gives multiplicative shocks unit expectation under this Gaussian construction.

Relative dispersion of historical ratios provides a heuristic log-noise scale, subject to component floors and a ceiling of 0.60. Unobserved components receive prior dispersion. These settings are demonstration assumptions, not an estimated structural model of infrastructure risk.

The tenth and ninetieth percentiles define a central 80% interval within the simulated distribution. Empirical coverage requires separate out-of-sample evaluation [4]. Frequencies of simulated funding gaps are not real-project default probabilities. Moreover, marginal monthly quantiles can originate from different paths. Financial equations are applied to complete paths before quantiles are extracted; component quantiles cannot simply be added into a coherent cash scenario. Shared random draws and fixed seeds make scenario comparisons reproducible.

## 5. What the harness controls

The harness provides a deterministic local workflow and an optional planner through a compatible HTTP model interface. This distinction matters: a workflow follows prescribed paths, while a model-directed agent chooses actions [3]. The local workflow reproduces the financial experiment without contacting a model.

Both modes require validation, the information cutoff, baseline calculation and reconciliation. Diagnostic tools compare the baseline with a three-month suspension, a 10% CAPEX increase, a 10% receipt reduction or a two-percentage-point annual-rate increase. These are sensitivities to specified assumptions, not causal explanations of observed outcomes.

The local mode runs all four diagnostics. The optional planner must complete downside and stress scenarios and inspect at least one driver. Tool schemas and call limits constrain its actions. It cannot change the financial arithmetic, invent financing, execute arbitrary shell code or bypass failed checks. Network access is opt-in.

Reports use structured numerical outputs with evidence locations. Free-form model numbers do not replace calculated values. Each run preserves machine-readable results, a summary and an action log. External state and progress records are consistent with engineering guidance for long-running agents [5]. Here their purpose is traceability. Numerical correctness, forecasting accuracy and orchestration quality remain separate evaluation targets; this study does not measure live-model planning performance.

## 6. Experiment design

### 6.1 Synthetic projects

The experiment comprises twelve seeded realisations of one template, each covering 84 months from January 2022 through December 2028: 30 construction months and 54 operating months. The frozen plan is dated December 2021. The default illustration uses a December 2023 cutoff.

Planned construction CAPEX totals RUB 6,000 million, with RUB 2,000 million of initial equity. Opening cash is RUB 100 million, the facility limit RUB 4,700 million and the cash target RUB 75 million. The annual rate is 12%; availability ends in December 2024. Principal service of RUB 110 million per month starts in January 2025, capped by outstanding debt.

Operating receipts ramp toward RUB 260 million per month before 2% annual escalation and 6% sinusoidal seasonality. Operating and maintenance expenses follow specified schedules. The generator's 12% cash-tax proxy is illustrative and does not represent a statutory rate.

Seeds one through twelve supply four realisations of each regime. The unbiased regime centres component deviations on one. Persistent bias uses receipt multipliers between 0.89 and 0.95 and construction CAPEX multipliers between 1.08 and 1.15, with separate deviations for other components. The reversal regime begins similarly but changes receipt bias to 1.07 from January 2027 and resets other operating biases to one.

Synthetic observations use lognormal perturbations with AR(1) coefficient 0.45, common innovation variance share 0.25 and component scales from 0.025 to 0.045. Thus the generator differs from the forecast simulation, although its multiplicative structure favours the correction rule. These are twelve realisations of one artificial design, not twelve independently sampled infrastructure projects. The design was not externally preregistered.

### 6.2 Evaluation

Three methods use identical forecast origins: the unchanged plan, repetition of the last observed components, and the corrected plan. Rolling-origin evaluation refits the correction using only preceding observations [4]. After twelve initial months, each origin contributes lead times of one, two and three months. Seventy origins per realisation, from December 2022 through September 2028, produce 840 origins and 2,520 origin-target pairs. Scores pool all three lead times.

The target is cash flow before financing, preventing debt drawings from concealing operational forecast error. For e_i = yhat_i - y_i:

`MAE = mean(abs(e_i))`.

`RMSE = sqrt(mean(e_i^2))`.

Both metrics are in millions of roubles. Component WAPE divides total absolute error by total absolute actual values when the denominator is positive. Percentage errors are less useful for net flows near zero or changing sign. Pooled RMSE uses all squared errors rather than averaging project-level RMSE. Overlapping origins and target months are dependent; the reported scores do not imply independent-sample confidence intervals.

Quantile calibration is outside this experiment. A later study should assess coverage and pinball loss, defined as tau times positive underprediction error plus (1 - tau) times positive overprediction error [6]. Under this convention, median pinball loss equals one-half of MAE.

## 7. Results

### 7.1 Point-forecast accuracy

**Table 1. Pooled errors, RUB million**

| Method | MAE | RMSE | Origin-target pairs |
|---|---:|---:|---:|
| Unchanged plan | 20.6776 | 25.1087 | 2,520 |
| Last observation | 24.3748 | 41.4297 | 2,520 |
| Corrected plan | 10.2911 | 13.7464 | 2,520 |

![Pooled and per-realisation forecast errors in the synthetic experiment](figures/benchmark.png)

**Figure 1.** Forecast errors for twelve seeded realisations of the synthetic design.

The corrected plan reduces pooled MAE by 50.23% relative to the unchanged plan. This percentage describes the chosen generator, regime mixture and evaluation window. It is not an expected gain for a real portfolio.

**Table 2. Errors by regime, RUB million**

| Regime | Method | MAE | RMSE |
|---|---|---:|---:|
| Persistent component bias | Unchanged plan | 28.4082 | 30.8653 |
| Persistent component bias | Last observation | 23.0518 | 40.3450 |
| Persistent component bias | Corrected plan | 10.7621 | 13.5408 |
| Operating regime reversal | Unchanged plan | 25.8197 | 28.8220 |
| Operating regime reversal | Last observation | 25.5222 | 41.7177 |
| Operating regime reversal | Corrected plan | 11.9675 | 16.3867 |
| Unbiased noisy plan | Unchanged plan | 7.8049 | 10.3906 |
| Unbiased noisy plan | Last observation | 24.5505 | 42.2038 |
| Unbiased noisy plan | Corrected plan | 8.1436 | 10.7245 |

Each regime contributes four realisations and 840 pairs. Correction improves eight of twelve realisations but worsens all four unbiased cases. Their pooled MAE increases from 7.8049 to 8.1436 million. Adaptation carries a cost when random deviations are mistaken for persistent signals.

The last-observation benchmark ignores the known transition from construction to operations. Its resulting errors make the unchanged plan the more informative comparator. No neural-network, gradient-boosting or foundation-model forecaster was evaluated. Full origin-level results and component WAPE are retained in the machine-readable report.

### 7.2 Liquidity scenarios

The illustration uses seed seven, a December 2023 cutoff and forecasts through December 2028. At the cutoff, cash is RUB 75 million and debt RUB 4,110.4358 million. The downside combines a three-month suspension, receipt multiplier 0.90, CAPEX multiplier 1.10, OPEX multiplier 1.05 and annual-rate increase 0.02. Stress uses six months, multipliers 0.80, 1.20 and 1.10 respectively, and rate increase 0.04.

**Table 3. Point-projection outcomes, RUB million**

| Scenario | Minimum cash | Peak gap to cash target | Terminal cash | Minimum operating DSCR |
|---|---:|---:|---:|---:|
| Baseline | -301.2287 | 376.2287 | 2,178.6664 | 0.9252 |
| Downside | -1,111.1786 | 1,186.1786 | -275.5203 | 0.6948 |
| Stress | -2,979.1790 | 3,054.1790 | -2,511.7870 | 0.3013 |

![Cash-balance forecasts for the synthetic project under stated scenarios](figures/forecast.png)

**Figure 2.** Central cash projections and conditional simulation bands under the specified scenarios.

With a RUB 75 million reserve target, the peak gap equals 75 minus the minimum projected cash: 75 - (-301.2287) = RUB 376.2287 million in the baseline. These are point-component ledger results, not simulated medians. Constrained drawings make the financing calculation nonlinear, so cash calculated from expected components need not equal expected cash across simulations.

Positive baseline terminal cash coexists with an earlier shortage. The reported minimum DSCR covers operating months after effective commissioning; the output also retains an all-period diagnostic. Downside defers RUB 801.0833 million of receipts beyond December 2028, while stress defers RUB 1,407.1310 million. Associated expense tails are disclosed too. Terminal comparisons therefore depend on the horizon.

The simulation uses 1,000 paths and random seed 42. Every path in each of the three scenarios crosses below zero in this run. This is a conditional simulation frequency, not evidence that a real project will certainly default.

### 7.3 Verification

The verification run passes 68 tests covering ledger identities, financing constraints, future-observation exclusion and mocked planner interactions. A standalone Decimal reference independently recalculated all seven central scenarios and the benchmark, using the generator only for synthetic fixtures, without assessing Monte Carlo calibration. The live language-model interface has not been evaluated.

## 8. Implications and next steps

The prototype makes several consequential assumptions visible. Borrowing cannot be counted as operating income; principal repayment cannot restore a non-revolving commitment; a delay cannot silently extend credit availability. Deferred obligations remain visible beyond the forecast horizon. These rules make a funding alert traceable to the cash component, date and financing constraint that produced it.

Scope remains limited to a monthly, single-currency model with one simplified facility. Fees, daily accrual, multiple tranches, hedging, reserve accounts, dividend restrictions, detailed taxation and automatic refinancing are excluded. The model reads structured schedules, not contracts or construction imagery. Neither a correct ledger nor a low synthetic error removes the need to verify source data and transaction definitions.

The next empirical test should use dated plan versions and cash histories from several infrastructure sectors, reserving projects and periods for untouched evaluation. Besides average error, it should examine the largest liquidity-shortfall months, warning lead time and empirical quantile coverage. Live-model testing should separately assess tool selection, evidence fidelity, latency and cost.

The current evidence supports a narrower conclusion: the implementation can expose unmet financing, preserve accounting identities and reconstruct a forecast from recorded inputs. Its adaptive rule helps under persistent synthetic deviations but can damage an already useful plan. Establishing practical forecasting value requires historical project evidence.

## References

[1] World Bank. Key Issues in Developing Project Financed Transactions. PPP Resource Center. https://ppp.worldbank.org/financing/issues-in-project-financed-transactions. Accessed 24 October 2026.

[2] World Bank. Identifying Risks. PPP Resource Center. https://ppp.worldbank.org/identifying-risks. Accessed 24 October 2026.

[3] Anthropic. Building effective agents. 19 December 2024. https://www.anthropic.com/research/building-effective-agents. Accessed 24 October 2026.

[4] Hyndman, R. J., and Athanasopoulos, G. Forecasting: Principles and Practice, third edition, Chapter 5: The forecaster's toolbox. OTexts. https://otexts.com/fpp3/toolbox.html. Accessed 24 October 2026.

[5] Anthropic. Effective harnesses for long-running agents. 26 November 2025. https://www.anthropic.com/research/effective-harnesses-for-long-running-agents. Accessed 24 October 2026.

[6] scikit-learn developers. Metrics and scoring: quantifying the quality of predictions. Section on pinball loss. https://scikit-learn.org/stable/modules/model_evaluation.html. Accessed 24 October 2026.

## Appendix. Reproduction

The package contains source code, synthetic fixtures, tests and machine-readable experimental outputs. No confidential client or borrower data are included. From the project directory:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
infra-cashflow demo --simulations 1000 --seed 42 --output results/demo
python scripts/generate_demo.py --benchmark --benchmark-output results/benchmark.json
python scripts/audit_release.py
```

The checks cover cash and debt reconciliation, non-revolving headroom, availability dates, information cutoffs, undefined service ratios, deferred cash flows, repeatable simulation seeds and harness completion gates. Reproducing a result confirms the recorded computation, not the suitability of its assumptions for a particular asset.

**Generative AI disclosure.** Generative AI assisted with literature discovery, software implementation, test development, computational checks, translation and drafting. This assistance was substantial. The study uses synthetic data and executable calculations.
