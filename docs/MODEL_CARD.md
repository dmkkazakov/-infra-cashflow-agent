# Model card

## Intended use

Version 0.1.1 is a research prototype for analysing monthly infrastructure-project cash flows. It forecasts a supplied schedule, estimates recent component deviations, evaluates fixed assumptions, and reports unmet financing needs. It is not a deployed treasury system or an estimate of default probability.

Author: Dmitry Kazakov. No employer or university is identified as endorsing the work.

## Model

Five cash components are adapted separately: receipts, construction CAPEX, OPEX, supplied cash taxes, and maintenance CAPEX. For each, eligible observations have positive baseline value. At most the latest 12 active observations are used; their actual/plan ratios are clipped to [0,5]. Recency weights decline by 0.85 and are normalised to sum to the number of observations. A prior with weight 3 and ratio 1 shrinks the correction toward the plan. With no active history, the multiplier equals 1.

Equity and principal schedules are not statistically adjusted. A zero in the future baseline remains zero in the point forecast and Monte Carlo paths. The model cannot discover a new expenditure or a missing commissioning event solely by multiplying the existing schedule.

The ledger preserves cash and debt balances. Interest uses beginning debt and annual rate /12. The credit facility is nonrevolving and bounded by cumulative drawings and an availability date. Additional equity and refinancing are never inserted automatically. Observed principal is always treated as an actual payment, even when recorded interest and drawings are absent. An observed payment exceeding opening debt is rejected, not capped. Only a future scheduled principal amount is capped by opening debt.

## Scenarios

| Assumption | Baseline | Downside | Stress |
|---|---:|---:|---:|
| Shift of remaining physical/operating cash schedules | 0 months | 3 months | 6 months |
| Receipts multiplier | 1.00 | 0.90 | 0.80 |
| Construction and maintenance CAPEX multiplier | 1.00 | 1.10 | 1.20 |
| OPEX multiplier | 1.00 | 1.05 | 1.10 |
| Annual interest-rate change | 0 pp | +2 pp | +4 pp |

The shift is a suspension of remaining activity. It shifts CAPEX, receipts, OPEX, taxes and maintenance CAPEX together; equity, principal and credit availability remain fixed. It does not simulate every contractual consequence of delayed commissioning. Taxes are an exogenous cash schedule, not a tax-law calculation. Amounts pushed beyond the selected horizon are disclosed separately.

## Conditional uncertainty

Monte Carlo multiplies cash components by mean-one lognormal factors. The assumed AR(1) coefficient is 0.65, and the common innovation variance share is 0.35. Persistent multiplier uncertainty is added separately. Dispersion is estimated from prior deviations with explicit floors/priors and a ceiling of 0.60. These modelling choices have not been calibrated to real infrastructure assets.

P10/P50/P90 are percentiles of the conditional model distribution. A pointwise percentile sequence need not be one coherent scenario. The central ledger evaluates central component forecasts; with nonlinear credit constraints its ending cash is not necessarily the mean or median simulated cash.

## Evaluation

The released experiment uses seeds 1 through 12 on a common 84-month synthetic template. Four seeds have an unbiased noisy plan, four persistent component bias, and four an operating-regime reversal. The minimum training history is 12 months. There are 70 rolling forecast origins per seed and three targets per origin: 840 origins and 2,520 origin-target pairs. Adjacent windows overlap.

The target is free cash flow before financing. Pooled MAE is 20.677587 million RUB for the unchanged plan, 24.374843 for last observation, and 10.291092 for the corrected plan. Correction improves 8 cases and worsens 4. These are executed simulation results, not externally validated business effects. There is no hypothesis-test significance claim and no measured incremental forecasting benefit of the LLM planner.

## Information boundary

All future actual rows are removed before fitting and state reconstruction. The schema uses economic month and one frozen plan vintage; it does not store when each fact became available or how it was revised. Production evaluation requires archived source vintages and availability timestamps. A content hash establishes reproducibility, not truth or authorisation of the underlying data.

## Implementation verification

68 unit tests passed on the release implementation, including hand-calculated cash/DSCR cases, nonrevolving headroom, facility expiry, exact recorded principal, future-observation invariance, delayed-tail conservation, horizon validation, unsafe tool rejection and mocked model transport. A wheel was built and its demo run outside the source checkout. The live model provider path was not exercised.

Every central scenario ledger receives independent reconciliation. Simulation paths use the same financial identities in a vectorised implementation; an independent audit of every stochastic path is not claimed. SHA-256 manifests detect alteration relative to the retained manifest; they are not signed records and cannot prevent an actor replacing both files and manifest.

## Practical limits

One currency; monthly periods; one debt facility. There is no accrual accounting, detailed VAT/tax model, daily liquidity, multiple debt tranches, hedging, reserve accounts, fees, capitalised interest, dividends, covenant interpretation, automatically inferred construction network, or guarantee-call model. Source preparation must reflect these omissions. Before use on a real transaction, reconcile the ledger to its accepted financial model and evaluate accuracy on dated historical forecasts.
