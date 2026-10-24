#!/usr/bin/env python3
"""Independently recalculate released central forecasts and point-error metrics.

Uses Decimal and standard-library sums. It does not import the forecasting,
financial-engine or harness implementations. The synthetic fixture generator
is used only to recreate the twelve disclosed benchmark data sets.
"""
from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 40
D = lambda x: Decimal(str(x))
FLOW = ("receipts", "capex", "opex", "tax", "maintenance_capex")
MONEY = FLOW + ("equity", "principal")
ROOT = Path(__file__).resolve().parents[1]


def corrected_factors(plan, observed):
    factors = {}
    for component in FLOW:
        pairs = [min(D(row[component]) / D(plan[row["month"]][component]), D(5))
                 for row in observed if D(plan[row["month"]][component]) > D("1e-9")][-12:]
        n = len(pairs)
        if not n:
            factors[component] = D(1)
            continue
        weights = [D("0.85") ** (n - 1 - k) for k in range(n)]
        mean_ratio = sum(w * r for w, r in zip(weights, pairs)) / sum(weights)
        factors[component] = (D(n) * mean_ratio + D(3)) / D(n + 3)
    return factors


def fcf(row):
    return D(row["receipts"]) - sum(D(row[k]) for k in ("capex", "opex", "tax", "maintenance_capex"))


def next_month(month, delta=1):
    year, mon = map(int, month.split("-"))
    number = year * 12 + mon - 1 + delta
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


def ledger(rows, financing, opening=None, actual=False):
    cash, debt, drawn = opening if opening is not None else tuple(D(financing[k]) for k in (
        "opening_cash", "opening_debt", "opening_cumulative_drawn"))
    floor, limit = D(financing["minimum_cash"]), D(financing["facility_limit"])
    outputs = []
    for row in rows:
        amounts = {k: D(row[k]) for k in MONEY}
        interest = D(row["interest"]) if actual and "interest" in row else debt * D(financing["annual_interest_rate"]) / D(12)
        principal = amounts["principal"] if actual else min(amounts["principal"], debt)
        if principal > debt:
            raise AssertionError("An observed principal payment exceeds opening debt")
        cfads = amounts["receipts"] - amounts["opex"] - amounts["tax"] - amounts["maintenance_capex"]
        before = cash + cfads - amounts["capex"] + amounts["equity"] - interest - principal
        draw = D(row["debt_draw"]) if actual and "debt_draw" in row else (
            min(max(floor - before, D(0)), max(limit - drawn, D(0)))
            if row["month"] <= financing["availability_end"] else D(0))
        service = interest + principal
        output = {"month": row["month"], "opening_cash": cash, "opening_debt": debt,
                  **amounts, "scheduled_principal": amounts["principal"], "principal": principal,
                  "cfads": cfads, "free_cash_flow": cfads - amounts["capex"],
                  "debt_draw": draw, "interest": interest, "debt_service": service,
                  "closing_cash": before + draw, "closing_debt": debt + draw - principal,
                  "cumulative_drawn": drawn + draw, "unused_facility": max(limit - drawn - draw, D(0)),
                  "funding_gap": max(floor - before - draw, D(0)),
                  "dscr": cfads / service if service > D("1e-12") else None}
        outputs.append(output)
        cash, debt, drawn = output["closing_cash"], output["closing_debt"], output["cumulative_drawn"]
    return outputs, (cash, debt, drawn)


def assert_close(expected, actual, label, residuals):
    if expected is None or actual is None:
        if expected is not None or actual is not None:
            raise AssertionError(f"{label}: null mismatch")
        return
    difference = abs(D(expected) - D(actual))
    residuals.append(float(difference))
    if difference > D("1e-8"):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def audit_forecasts(project, report):
    observed = [row for row in project["actuals"] if row["month"] <= report["as_of"]]
    plan = {row["month"]: row for row in project["baseline"]}
    multipliers = corrected_factors(plan, observed)
    history, opening = ledger(observed, project["financing"], actual=True)
    results = {}
    for name, forecast in report["forecasts"].items():
        scenario = forecast["scenario"]
        rows, residuals = [], []
        for reported in forecast["monthly"]:
            month = reported["month"]
            source_month = next_month(month, -scenario["delay_months"])
            source = plan.get(source_month, {}) if source_month > report["as_of"] else {}
            row = {"month": month}
            for component in FLOW:
                multiplier = scenario["capex_multiplier"] if component in ("capex", "maintenance_capex") else (
                    scenario["receipts_multiplier"] if component == "receipts" else
                    scenario["opex_multiplier"] if component == "opex" else 1)
                row[component] = D(source.get(component, 0)) * multipliers[component] * D(multiplier)
            row.update({k: D(plan.get(month, {}).get(k, 0)) for k in ("equity", "principal")})
            rows.append(row)
        financing = dict(project["financing"])
        financing["annual_interest_rate"] = D(financing["annual_interest_rate"]) + D(scenario["annual_rate_shift"])
        recalculated, _ = ledger(rows, financing, opening=opening)
        for expected, actual in zip(recalculated, forecast["monthly"]):
            for key, value in expected.items():
                if key != "month":
                    assert_close(value, actual[key], f"{name}/{actual['month']}/{key}", residuals)
        for expected, actual in zip(history, forecast["actual_ledger"]):
            for key in ("closing_cash", "closing_debt", "interest", "principal", "debt_draw"):
                assert_close(expected[key], actual[key], f"{name}/history/{actual['month']}/{key}", residuals)
        lowest = min(recalculated, key=lambda r: r["closing_cash"])
        first_gap = next((r["month"] for r in recalculated if r["funding_gap"] > D("1e-7")), None)
        results[name] = {"months_checked": len(recalculated), "maximum_absolute_difference": max(residuals),
                         "minimum_cash_month": lowest["month"], "min_cash": float(lowest["closing_cash"]),
                         "max_funding_gap": float(max(r["funding_gap"] for r in recalculated)),
                         "terminal_cash": float(recalculated[-1]["closing_cash"]), "first_gap_month": first_gap}
    return results


def audit_benchmark(released):
    # The generator supplies data only; forecasts and metrics are recomputed here.
    from infra_cashflow.data import make_demo_project
    errors = {method: [] for method in ("plan", "last_observation", "adjusted")}
    residuals, origins, wins = [], 0, 0
    for published in released["per_project"]:
        project = make_demo_project(seed=published["seed"])
        plan = {row["month"]: row for row in project["baseline"]}
        actuals = project["actuals"]
        local = {method: [] for method in errors}
        for stop in range(released["min_train_months"], len(actuals) - released["horizon_months"] + 1):
            origins += 1
            multipliers = corrected_factors(plan, actuals[:stop])
            for actual in actuals[stop:stop + released["horizon_months"]]:
                base = plan[actual["month"]]
                adjusted = {c: D(base[c]) * multipliers[c] for c in FLOW}
                candidates = {"plan": base, "last_observation": actuals[stop - 1], "adjusted": adjusted}
                for method, candidate in candidates.items():
                    error = float(fcf(candidate) - fcf(actual))
                    local[method].append(error)
                    errors[method].append(error)
        for method in errors:
            mae = math.fsum(abs(e) for e in local[method]) / len(local[method])
            rmse = math.sqrt(math.fsum(e * e for e in local[method]) / len(local[method]))
            assert_close(mae, published["methods"][method]["net_cashflow_mae"], f"seed/{published['seed']}/{method}/MAE", residuals)
            assert_close(rmse, published["methods"][method]["net_cashflow_rmse"], f"seed/{published['seed']}/{method}/RMSE", residuals)
        wins += sum(abs(e) for e in local["adjusted"]) < sum(abs(e) for e in local["plan"])
    aggregate = {}
    for method, values in errors.items():
        aggregate[method] = {"predictions": len(values),
                             "mae": math.fsum(abs(e) for e in values) / len(values),
                             "rmse": math.sqrt(math.fsum(e * e for e in values) / len(values))}
        for label in ("mae", "rmse"):
            assert_close(aggregate[method][label], released["aggregate"][method]["net_cashflow_" + label], method + label, residuals)
    if origins != released["total_origins"] or wins != released["adjusted_wins_vs_plan"]:
        raise AssertionError("Benchmark counts differ")
    return {"origins": origins, "adjusted_wins_vs_plan": wins, "aggregate": aggregate,
            "maximum_absolute_metric_difference": max(residuals)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results/independent_audit.json")
    args = parser.parse_args()
    project = json.loads((ROOT / "examples/demo_project.json").read_text())
    latest = json.loads((ROOT / "results/demo/latest.json").read_text())
    report = json.loads((ROOT / "results/demo" / latest["run_id"] / "report.json").read_text())
    benchmark = json.loads((ROOT / "results/benchmark.json").read_text())
    result = {"passed": True, "reference_arithmetic": "Decimal, precision 40; standard-library metric aggregation",
              "scope": "All seven central scenarios, historical opening states and all twelve point-forecast benchmark fixtures. Monte Carlo calibration is not assessed.",
              "run_id": report["run_id"], "forecasts": audit_forecasts(project, report),
              "benchmark": audit_benchmark(benchmark)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
