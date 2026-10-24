# Infrastructure cash-flow forecast

As of: 2023-12. Amounts: RUB million.
Run: `d12d12f84b28449f2713`; mode: `offline_workflow`.

Numbers below come from checked local calculations. Inputs are explicitly synthetic.

| Scenario | Minimum cash | Terminal cash | Model-conditional shortfall frequency | Minimum operating-month DSCR |
|---|---:|---:|---:|---:|
| baseline | -301.229 | 2,178.666 | 100.0% | 0.925 |
| downside | -1,111.179 | -275.520 | 100.0% | 0.695 |
| stress | -2,979.179 | -2,511.787 | 100.0% | 0.301 |
| sensitivity_delay | -429.957 | 1,661.688 | 100.0% | 0.917 |
| sensitivity_capex | -369.776 | 2,081.903 | 100.0% | 0.922 |
| sensitivity_receipts | -301.229 | 725.455 | 100.0% | 0.764 |
| sensitivity_rate | -346.696 | 1,914.915 | 100.0% | 0.883 |

## Evidence

Every metric is identified by its JSON pointer in `report.json`:

- `/forecasts/baseline/summary/min_cash` = -301.229
- `/forecasts/baseline/summary/terminal_cash` = 2,178.666
- `/forecasts/baseline/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/baseline/summary/min_dscr` = 0.925
- `/forecasts/downside/summary/min_cash` = -1,111.179
- `/forecasts/downside/summary/terminal_cash` = -275.520
- `/forecasts/downside/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/downside/summary/min_dscr` = 0.695
- `/forecasts/stress/summary/min_cash` = -2,979.179
- `/forecasts/stress/summary/terminal_cash` = -2,511.787
- `/forecasts/stress/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/stress/summary/min_dscr` = 0.301
- `/forecasts/sensitivity_delay/summary/min_cash` = -429.957
- `/forecasts/sensitivity_delay/summary/terminal_cash` = 1,661.688
- `/forecasts/sensitivity_delay/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/sensitivity_delay/summary/min_dscr` = 0.917
- `/forecasts/sensitivity_capex/summary/min_cash` = -369.776
- `/forecasts/sensitivity_capex/summary/terminal_cash` = 2,081.903
- `/forecasts/sensitivity_capex/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/sensitivity_capex/summary/min_dscr` = 0.922
- `/forecasts/sensitivity_receipts/summary/min_cash` = -301.229
- `/forecasts/sensitivity_receipts/summary/terminal_cash` = 725.455
- `/forecasts/sensitivity_receipts/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/sensitivity_receipts/summary/min_dscr` = 0.764
- `/forecasts/sensitivity_rate/summary/min_cash` = -346.696
- `/forecasts/sensitivity_rate/summary/terminal_cash` = 1,914.915
- `/forecasts/sensitivity_rate/summary/probability_min_cash_below_floor` = 1.000
- `/forecasts/sensitivity_rate/summary/min_dscr` = 0.883

## Interpretation and limitations

- delay sensitivity: change in minimum cash -128.728; change in terminal cash -516.978. One-factor model comparison, not a measured causal effect.
- capex sensitivity: change in minimum cash -68.547; change in terminal cash -96.763. One-factor model comparison, not a measured causal effect.
- receipts sensitivity: change in minimum cash 0.000; change in terminal cash -1,453.211. One-factor model comparison, not a measured causal effect.
- rate sensitivity: change in minimum cash -45.468; change in terminal cash -263.751. One-factor model comparison, not a measured causal effect.
- Conditional simulation ranges are not empirically calibrated confidence intervals.
- Synthetic demonstration results do not establish real-project forecasting accuracy.
- The fixed forecast horizon can leave delayed cash flows outside the reported period.
- Scenario probabilities are model-conditional, not credit default probabilities.
- Monthly DSCR is illustrative; contractual covenant definitions require separate implementation.
- LLM mode only chooses predefined tool actions; all published figures come from verified code.

## Reproducibility

- Input SHA-256: `ff23ca9a83f8c2f76cfc656c0b0b9fc30394e08ca314958e33b4bfe8aa763ed3`.
- Source SHA-256: `5a91862731fd9ab0a6cdb7caa3d502ebce420bda93268b3482079ba7b0303b32`.
- Manifest contains artifact checksums. Audit records all calculation and verification steps.
