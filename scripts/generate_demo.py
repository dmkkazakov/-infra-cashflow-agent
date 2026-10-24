#!/usr/bin/env python3
"""Create reproducible synthetic fixtures and an optional 12-seed benchmark."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from infra_cashflow.data import AMOUNT_FIELDS, make_demo_project
from infra_cashflow.forecasting import backtest


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def benchmark(seeds: list[int], min_train: int = 12, horizon: int = 3) -> dict:
    results = []
    for seed in seeds:
        project = make_demo_project(seed=seed)
        result = backtest(project, min_train=min_train, horizon=horizon)
        result["seed"] = seed
        result["regime"] = project["synthetic_design"]["regime"]
        results.append(result)
    aggregate = {}
    for method in ("plan", "last_observation", "adjusted"):
        n = sum(r["methods"][method]["predictions"] for r in results)
        absolute = sum(r["methods"][method]["absolute_error_sum"] for r in results)
        squared = sum(r["methods"][method]["squared_error_sum"] for r in results)
        aggregate[method] = {"net_cashflow_mae": absolute / n, "net_cashflow_rmse": math.sqrt(squared / n), "predictions": n}
    return {
        "experiment": "fixed_design_synthetic_rolling_origin_v1", "synthetic_data": True,
        "seeds": seeds, "projects": len(results), "amount_unit": "million", "currency": "RUB",
        "min_train_months": min_train, "horizon_months": horizon,
        "total_origins": sum(r["rolling_origins"] for r in results),
        "aggregate": aggregate,
        "adjusted_wins_vs_plan": sum(r["methods"]["adjusted"]["net_cashflow_mae"] < r["methods"]["plan"]["net_cashflow_mae"] for r in results),
        "per_project": results,
        "interpretation": "Synthetic design only. No empirical real-project accuracy, significance or uncertainty-band coverage claim. Shared design across seeds is not external validation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("examples/demo_project.json"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--benchmark-output", type=Path, default=Path("artifacts/synthetic_benchmark.json"))
    args = parser.parse_args()
    project = make_demo_project(seed=args.seed)
    write_json(args.output, project)
    for name, rows in (("baseline", project["baseline"]), ("actuals", project["actuals"])):
        path = args.output.with_name(f"demo_{name}.csv")
        columns = ["month", *AMOUNT_FIELDS] + (["debt_draw", "interest"] if name == "actuals" else [])
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    if args.benchmark:
        report = benchmark(list(range(1, 13)))
        write_json(args.benchmark_output, report)
        print(json.dumps({"aggregate": report["aggregate"], "adjusted_wins_vs_plan": report["adjusted_wins_vs_plan"], "projects": report["projects"]}, indent=2))
    print(f"Synthetic project saved: {args.output}")


if __name__ == "__main__":
    main()
