# Model card

## Intended use

Version 0.1.3 is a research prototype for analysing monthly infrastructure-project cash flows. It forecasts a supplied schedule, estimates recent component deviations, evaluates fixed assumptions, and reports unmet financing needs. It is not a deployed treasury system or an estimate of default probability.

Author: Dmitry Kazakov. No employer or university is identified as endorsing the work.

## Model

Five cash components are adapted separately: receipts, construction CAPEX, OPEX, supplied cash taxes, and maintenance CAPEX. For each, eligible observations have positive baseline value. At most the latest 12 active observations are used; their actual/plan ratios are clipped to [0,5]. Recency weights decline by 0.85 and are normalised to sum to the number of observations. A prior with weight 3 and ratio 1 shrinks the correction toward the plan. With no active history, the multiplier equals 1.

Equity and principal schedules are not statistically adjusted. A zero in the future baseline remains zero in the point forecast and Monte Carlo paths. The model cannot discover a new expenditure or a missing commissioning event solely by multiplying the existing schedule.

The ledger preserves cash and debt balances. Interest uses beginning debt and annual rate /12. The credit facility is nonrevolving and bounded by cumulative drawings and an availability date. Additional equity and refinancing are never inserted automatically. Observed principal is always treated as an actual payment, even when recorded interest and drawings are absent. An observed payment exceeding opening debt beyond machine rounding is rejected, not capped. Only a future scheduled principal amount is capped by opening debt.

Positive balance comparisons allow at most the smaller of 2,400 ULP at the historical financing scale and 1e-9 times the larger compared amount. This bounds accumulated rounding over the supported 600 input months and works when a ledger resumes from its closing state. Only a negative derived debt residue within this allowance is normalised to zero; recorded payments and drawings remain unchanged. A zero debt balance never permits positive observed principal. Zero headroom and expired availability never permit positive drawings. The detailed convention is in [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

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

The released experiment uses seeds 1 through 12 on a common 84-month synthetic template. Four seeds have an unbiased noisy plan, four persistent component bias, and four an operating-regime reversal. The minimum training history is 12 months. There are 70 rolling forecast origins per seed and three targets per origin: 840 origins and 2,520 origin-target pairs. Adjacent windows overlap. Reference artifacts retain their original version 0.1.1 provenance; version 0.1.3 adds input, numerical-boundary and runtime corrections without changing the financial assumptions or the published experimental results.

The target is free cash flow before financing. Pooled MAE is 20.677587 million RUB for the unchanged plan, 24.374843 for last observation, and 10.291092 for the corrected plan. Correction improves 8 cases and worsens 4. These are executed simulation results, not externally validated business effects. There is no hypothesis-test significance claim and no measured incremental forecasting benefit of the LLM planner.

## Information boundary

All future actual rows are removed before fitting and state reconstruction. The schema uses economic month and one frozen plan vintage; it does not store when each fact became available or how it was revised. Production evaluation requires archived source vintages and availability timestamps. A content hash establishes reproducibility, not truth or authorisation of the underlying data.

## Implementation verification

The test suite covers hand-calculated cash/DSCR cases, nonrevolving headroom, facility expiry, exact recorded payments, future-observation invariance, delayed-tail conservation, horizon validation, numerical overflow, unsafe tool rejection and mocked model transport. Runtime regressions cover repeated attempts, configuration snapshots, incomplete caches, failed writes and credential-safe errors. The current count and executed release checks are recorded in [VERIFICATION.md](VERIFICATION.md). A live language-model provider has not been tested.

Every central scenario ledger receives independent reconciliation. Simulation paths use the same financial identities in a vectorised implementation; an independent audit of every stochastic path is not claimed. SHA-256 manifests detect alteration relative to the retained manifest; they are not signed records and cannot prevent an actor replacing both files and manifest.

An additional audit compared the scalar and vectorised ledgers against 50-digit Decimal arithmetic on 200 random configurations covering 2,658 months. The vectorised check used zero random shocks to isolate the accounting equations. The largest scalar difference was approximately 1.82e-12 in the input money unit. This checks implementation consistency, not uncertainty calibration. Independent rolling-origin calculations across nine history/horizon settings also agreed within floating-point rounding.

A complete adapter-to-harness cycle was also exercised against a local HTTP server with scripted responses. An early finalization request was rejected; the required scenarios, a rate sensitivity and report persistence completed successfully. This checks the integration contract, not the decision quality of a live language model.

## Practical limits

One currency; monthly periods; one debt facility. There is no accrual accounting, detailed VAT/tax model, daily liquidity, multiple debt tranches, hedging, reserve accounts, fees, capitalised interest, dividends, covenant interpretation, automatically inferred construction network, or guarantee-call model. Source preparation must reflect these omissions. Before use on a real transaction, reconcile the ledger to its accepted financial model and evaluate accuracy on dated historical forecasts.
