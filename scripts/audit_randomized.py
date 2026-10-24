#!/usr/bin/env python3
"""Reproduce the additional version 0.1.3 numerical audit.

The scalar and vectorised implementations are compared with separate 50-digit
Decimal calculations. Vectorised random shocks are disabled deliberately:
this checks accounting equations, not Monte Carlo calibration. A second
reference calculation checks nine rolling-origin history/horizon settings.
Only synthetic data are used. The seed and draw order reproduce the released
200-case, 2,658-month audit.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from decimal import Decimal, getcontext
from pathlib import Path

import numpy as np

from infra_cashflow import __version__
from infra_cashflow.data import AMOUNT_FIELDS, FLOW_COMPONENTS, add_months, make_demo_project, validate_project
from infra_cashflow.engine import cashflow_ledger
from infra_cashflow.forecasting import _cash_path_simulation, backtest, run_forecast

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SEED = 5310
CASE_COUNT = 200
DECIMAL_PRECISION = 50


def decimal(value) -> Decimal:
    return Decimal(str(value))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def audit_ledgers(rng: random.Random) -> dict:
    maximum_difference = 0.0
    months = 0
    zero_model = {"components": {
        component: {"conditional_log_noise_sd": 0.0, "parameter_log_noise_sd": 0.0}
        for component in FLOW_COMPONENTS
    }}
    for trial in range(CASE_COUNT):
        limit = float(rng.randrange(0, 2000))
        drawn = float(rng.randrange(0, int(limit) + 1))
        debt = float(rng.randrange(0, int(drawn) + 1))
        state = {"cash": float(rng.randrange(-500, 500)), "debt": debt, "cumulative_drawn": drawn}
        rate = rng.choice([0.0, 0.12, 0.35, 1.0])
        financing = {
            "opening_cash": 0.0, "opening_debt": debt, "opening_cumulative_drawn": drawn,
            "facility_limit": limit, "minimum_cash": float(rng.randrange(0, 150)),
            "annual_interest_rate": rate,
            "availability_end": add_months("2024-01", rng.randrange(0, 16)),
        }
        rows = []
        for t in range(rng.randrange(1, 25)):
            row = {key: float(rng.randrange(0, 200)) for key in AMOUNT_FIELDS}
            row["month"] = add_months("2024-01", t)
            if trial % 7 == 0:
                row.update({component: 0.0 for component in FLOW_COMPONENTS})
            rows.append(row)
        ledger = cashflow_ledger(rows, financing, state)
        cash_paths, fcf_paths, dscr_paths = _cash_path_simulation(rows, financing, state, zero_model, 3, trial)
        cash, loan, used = map(decimal, (state["cash"], state["debt"], state["cumulative_drawn"]))
        for i, row in enumerate(rows):
            cfads = decimal(row["receipts"]) - decimal(row["opex"]) - decimal(row["tax"]) - decimal(row["maintenance_capex"])
            fcf = cfads - decimal(row["capex"])
            interest = loan * decimal(rate) / decimal(12)
            principal = min(loan, decimal(row["principal"]))
            service = interest + principal
            cash = cash + fcf + decimal(row["equity"]) - service
            if row["month"] <= financing["availability_end"]:
                draw = min(max(decimal(financing["minimum_cash"]) - cash, decimal(0)),
                           max(decimal(limit) - used, decimal(0)))
            else:
                draw = decimal(0)
            cash += draw
            loan += draw - principal
            used += draw
            oracle = {
                "cfads": cfads, "free_cash_flow": fcf, "interest": interest,
                "principal": principal, "debt_draw": draw, "closing_cash": cash,
                "closing_debt": loan, "cumulative_drawn": used,
                "funding_gap": max(decimal(financing["minimum_cash"]) - cash, decimal(0)),
            }
            for field, value in oracle.items():
                difference = abs(ledger[i][field] - float(value))
                maximum_difference = max(maximum_difference, difference)
                require(difference < 1e-8, f"Scalar mismatch: case={trial}, month={i}, field={field}, difference={difference}")
            np.testing.assert_allclose(cash_paths[:, i], float(cash), rtol=0, atol=1e-8)
            np.testing.assert_allclose(fcf_paths[:, i], float(fcf), rtol=0, atol=1e-8)
            if service > decimal("1e-12"):
                np.testing.assert_allclose(dscr_paths[:, i], float(cfads / service), rtol=0, atol=1e-8)
            else:
                require(bool(np.isnan(dscr_paths[:, i]).all()), "Zero-service DSCR must be undefined")
            months += 1
    return {
        "cases": CASE_COUNT, "months": months, "paths_per_case": 3,
        "maximum_scalar_decimal_error": maximum_difference, "passed": True,
    }


def make_grid_fixture(rng: random.Random) -> dict:
    project = make_demo_project()
    project.update(as_of="2022-03", operations_start="2022-01")
    project["baseline"], project["actuals"] = [], []
    project["financing"] = {
        "opening_cash": 10000.0, "opening_debt": 0.0, "opening_cumulative_drawn": 0.0,
        "facility_limit": 0.0, "minimum_cash": 0.0, "annual_interest_rate": 0.0,
        "availability_end": "2030-12",
    }
    for i in range(30):
        month = add_months("2022-01", i)
        baseline = {key: float(rng.randrange(0, 100)) for key in AMOUNT_FIELDS}
        baseline.update(month=month, principal=0.0, equity=0.0)
        if i % 4 == 0:
            baseline["receipts"] = 0.0
        if i % 3 == 0:
            baseline["tax"] = 0.0
        actual = {component: float(rng.randrange(0, 150)) for component in FLOW_COMPONENTS}
        if i % 7 == 0:
            actual["receipts"] = baseline["receipts"] * 12.0
        actual.update(month=month, principal=0.0, equity=0.0, debt_draw=0.0, interest=0.0)
        project["baseline"].append(baseline)
        project["actuals"].append(actual)
    validate_project(project)
    return project


def reference_fcf(row) -> Decimal:
    return decimal(row["receipts"]) - sum(decimal(row[component]) for component in ("capex", "opex", "tax", "maintenance_capex"))


def audit_backtest_grid(project: dict) -> dict:
    maximum_difference = 0.0
    for min_train in (3, 12, 18):
        for horizon in (1, 3, 6):
            report = backtest(project, min_train, horizon)
            expected = {name: [] for name in ("plan", "last_observation", "adjusted")}
            for stop in range(min_train, len(project["actuals"]) - horizon + 1):
                factors = {}
                for component in FLOW_COMPONENTS:
                    pairs = [
                        min(decimal(actual[component]) / decimal(baseline[component]), decimal(5))
                        for actual, baseline in zip(project["actuals"][:stop], project["baseline"][:stop])
                        if decimal(baseline[component]) > decimal("1e-9")
                    ][-12:]
                    n = len(pairs)
                    weights = [decimal("0.85") ** i for i in range(n - 1, -1, -1)]
                    factors[component] = (
                        (decimal(n) * (sum(weight * ratio for weight, ratio in zip(weights, pairs)) / sum(weights)) + decimal(3))
                        / decimal(n + 3) if n else decimal(1)
                    )
                for target in range(stop, stop + horizon):
                    actual, baseline = project["actuals"][target], project["baseline"][target]
                    predictions = {
                        "plan": {component: decimal(baseline[component]) for component in FLOW_COMPONENTS},
                        "last_observation": {component: decimal(project["actuals"][stop - 1][component]) for component in FLOW_COMPONENTS},
                        "adjusted": {component: decimal(baseline[component]) * factors[component] for component in FLOW_COMPONENTS},
                    }
                    for name, prediction in predictions.items():
                        expected[name].append(reference_fcf(prediction) - reference_fcf(actual))
            for name, errors in expected.items():
                n = decimal(len(errors))
                values = {
                    "net_cashflow_mae": sum(abs(error) for error in errors) / n,
                    "net_cashflow_rmse": (sum(error * error for error in errors) / n).sqrt(),
                    "net_cashflow_bias": sum(errors) / n,
                }
                for field, value in values.items():
                    difference = abs(report["methods"][name][field] - float(value))
                    maximum_difference = max(maximum_difference, difference)
                    require(difference < 1e-9, f"Backtest mismatch: min_train={min_train}, horizon={horizon}, method={name}, field={field}")
    return {"configurations": 9, "methods": 3, "max_metric_difference": maximum_difference, "passed": True}


def audit_zero_flows(project: dict) -> dict:
    allzero = copy.deepcopy(project)
    for row in allzero["baseline"] + allzero["actuals"]:
        for component in AMOUNT_FIELDS:
            row[component] = 0.0
    allzero["financing"]["opening_cash"] = 0.0
    allzero["as_of"] = "2022-01"
    report = run_forecast(allzero, horizon=12, n_simulations=10)
    require(all(row["closing_cash"] == 0.0 and row["p10_cash"] == 0.0 and row["dscr"] is None for row in report["monthly"]),
            "Zero-flow forecast must retain zero cash and undefined DSCR")
    require(all(component["multiplier"] == 1.0 and component["active_observations"] == 0 for component in report["model"]["components"].values()),
            "No active history must retain the unit multiplier")
    evaluation = backtest(allzero, min_train=3, horizon=3)
    require(all(method["net_cashflow_mae"] == 0 and all(value is None for value in method["component_wape"].values())
                for method in evaluation["methods"].values()), "Zero targets must give zero MAE and undefined WAPE")
    return {"one_month_observed": True, "finite_forecast": True, "zero_metrics": True, "null_dscr_and_wape": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/additional-audits/randomized.json")
    args = parser.parse_args()
    getcontext().prec = DECIMAL_PRECISION
    rng = random.Random(AUDIT_SEED)
    ledger_result = audit_ledgers(rng)
    project = make_grid_fixture(rng)
    results = {
        "passed": True,
        "package_version": __version__,
        "audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "random_seed": AUDIT_SEED,
        "reference_decimal_precision": DECIMAL_PRECISION,
        "scope": "Separate Decimal arithmetic for synthetic scalar/vector ledgers and rolling-origin metrics; no stochastic calibration or real-project validation.",
        "random_decimal_scalar_vector": ledger_result,
        "independent_backtest_grid": audit_backtest_grid(project),
        "zero_history_zero_flows": audit_zero_flows(project),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
