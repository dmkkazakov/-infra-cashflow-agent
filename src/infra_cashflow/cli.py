"""Command-line interface; offline by default, without credentials or network."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .data import load_project
from .forecasting import backtest
from .harness import ForecastHarness, HarnessError, _atomic_write, canonical_json
from .llm import ChatCompletionsPlanner, PlannerError


def _run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, default=Path("outputs/runs"), help="Parent directory for run artifacts")
    parser.add_argument("--as-of", help="Last observed month YYYY-MM; future actuals are excluded")
    parser.add_argument("--horizon", type=int, help="Number of future monthly forecast periods")
    parser.add_argument("--simulations", type=int, default=1000, help="Monte Carlo paths (default: 1000)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mode", choices=["offline", "llm"], default="offline")
    parser.add_argument("--allow-network", action="store_true", help="Explicitly permit model HTTP requests in llm mode")
    parser.add_argument("--llm-base-url", default=os.environ.get("CASHFLOW_LLM_BASE_URL"), help="API base URL ending in /v1")
    parser.add_argument("--llm-model", default=os.environ.get("CASHFLOW_LLM_MODEL"), help="Explicit model identifier")
    parser.add_argument("--objective", default="Assess infrastructure-project liquidity under baseline, downside and stress.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infra-cashflow", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Forecast a supplied project JSON")
    run.add_argument("project", type=Path)
    _run_options(run)
    demo = commands.add_parser("demo", help="Run the explicitly synthetic example")
    demo.add_argument("--project", type=Path, help="Optional alternative synthetic project JSON")
    _run_options(demo)
    evaluate = commands.add_parser("evaluate", help="Run rolling-origin evaluation on observed data")
    evaluate.add_argument("project", type=Path)
    evaluate.add_argument("--output", type=Path, default=Path("outputs/evaluation.json"))
    evaluate.add_argument("--min-train", type=int, default=12)
    evaluate.add_argument("--horizon", type=int, default=3)
    return parser


def _demo_project(as_of: str | None = None) -> dict:
    # Source checkouts use the versioned fixture; installed distributions can
    # generate the same fixture via the core's deterministic generator.
    source_fixture = Path(__file__).resolve().parents[2] / "examples" / "demo_project.json"
    if source_fixture.is_file():
        return load_project(source_fixture, as_of=as_of)
    from .data import make_demo_project
    return make_demo_project(as_of=as_of or "2023-12")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "evaluate":
            project = load_project(args.project)
            result = backtest(project, min_train=args.min_train, horizon=args.horizon)
            _atomic_write(args.output.resolve().parent, args.output.name,
                          canonical_json(result, pretty=True) + "\n")
            print(canonical_json({"status": "complete", "evaluation": str(args.output.resolve())}, pretty=True))
            return 0
        project = (load_project(args.project, as_of=args.as_of) if args.project else _demo_project(args.as_of))
        planner = None
        if args.mode == "llm":
            if not args.allow_network:
                raise ValueError("LLM mode requires --allow-network; financial summaries will be sent to the configured endpoint.")
            if not args.llm_base_url or not args.llm_model:
                raise ValueError("LLM mode requires an explicit --llm-base-url and --llm-model (or matching environment variables).")
            planner = ChatCompletionsPlanner(
                base_url=args.llm_base_url, model=args.llm_model,
                api_key=os.environ.get("CASHFLOW_LLM_API_KEY", ""), allow_network=True,
            )
        harness = ForecastHarness(project, args.output, as_of=args.as_of, horizon=args.horizon,
                                  n_simulations=args.simulations, seed=args.seed, planner=planner,
                                  objective=args.objective)
        result = harness.run()
        print(canonical_json({"status": result["status"], "mode": result["mode"], "run_id": result["run_id"],
                              "output_directory": str(harness.output_path),
                              "summaries": {key: value["summary"] for key, value in result["forecasts"].items()}}, pretty=True))
        return 0
    except (ValueError, OSError, HarnessError, PlannerError, KeyError) as exc:
        print(f"infra-cashflow: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
