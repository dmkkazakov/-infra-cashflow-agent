#!/usr/bin/env python3
"""Reproduce a five-request local HTTP adapter-to-harness integration audit.

Only a loopback server with scripted responses and an explicit dummy API key is
used. No external model endpoint is contacted. This tests the protocol and
completion gates, not the decisions of a live language model. Generated run
files are temporary under the output directory; the compact audit is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from infra_cashflow.data import load_project
from infra_cashflow.harness import ForecastHarness
from infra_cashflow.llm import ChatCompletionsPlanner

ROOT = Path(__file__).resolve().parents[1]
DUMMY_API_KEY = "local-integration-test-key-not-a-real-credential"
UNTRUSTED_TEXT = "FABRICATED_FINANCIAL_RESULT_1000000000000"
SCRIPTED_RESPONSES = (
    ("finalize", {}),
    ("diagnose_driver", {"driver": "rate"}),
    ("run_scenario", {"scenario": "downside"}),
    ("run_scenario", {"scenario": "stress"}),
    ("finalize", {}),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def audit(output_parent: Path) -> dict:
    requests = []
    protocol_errors = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                require(self.path == "/v1/chat/completions", "Unexpected audit endpoint")
                require(self.headers.get("Authorization") == "Bearer " + DUMMY_API_KEY, "Dummy credential was not transmitted as expected")
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                index = len(requests)
                require(index < len(SCRIPTED_RESPONSES), "Unexpected additional model request")
                requests.append(payload)
                name, arguments = SCRIPTED_RESPONSES[index]
                body = json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": UNTRUSTED_TEXT,
                    "tool_calls": [{"id": f"call-{index}", "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(arguments)}}],
                }}]}).encode("utf-8")
            except (AssertionError, ValueError, TypeError, KeyError) as exc:
                protocol_errors.append(type(exc).__name__)
                self.send_error(400, "Invalid scripted audit request")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    project = load_project(ROOT / "examples/demo_project.json")
    require(project.get("synthetic_data") is True, "The integration audit requires the synthetic fixture")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="http-harness-", dir=output_parent) as temporary:
            planner = ChatCompletionsPlanner(
                f"http://127.0.0.1:{server.server_port}/v1", "local-stub-tools",
                api_key=DUMMY_API_KEY, allow_network=True,
            )
            harness = ForecastHarness(project, temporary, n_simulations=10, horizon=12, planner=planner)
            report = harness.run()
            require(not protocol_errors, "The local server rejected an audit request")
            require(report["status"] == "complete" and report["mode"] == "llm_planned", "The scripted run did not complete")
            require(len(requests) == 5 and harness.tool_count == 5, "Expected five requests and five validated tool calls")
            require(set(report["forecasts"]) == {"baseline", "downside", "stress", "sensitivity_rate"}, "Unexpected forecast set")
            require(set(report["diagnostics"]) == {"rate"}, "Unexpected diagnostic set")
            require(all(value["passed"] for value in report["accounting_checks"].values()), "Accounting reconciliation failed")
            pending = json.loads(requests[1]["messages"][-1]["content"])
            require(pending["status"] == "required_scenarios_pending", "Premature finalisation was not rejected")
            require(set(pending["missing"]) == {"downside", "stress", "at_least_one_driver_diagnostic"}, "Missing requirements were not identified")
            require(all(payload["tool_choice"] == "required" and payload["parallel_tool_calls"] is False for payload in requests),
                    "The adapter did not request one required tool call")
            require(all('"actuals":' not in json.dumps(payload["messages"]) for payload in requests), "Raw actual rows were included in the planner payload")
            output_text = "".join(path.read_text(encoding="utf-8") for path in harness.output_path.iterdir() if path.is_file())
            require(UNTRUSTED_TEXT not in output_text, "Free-form fabricated model output was persisted")
            require(DUMMY_API_KEY not in output_text, "The dummy credential was persisted")
            latest = json.loads((Path(temporary) / "latest.json").read_text(encoding="utf-8"))
            require(latest["run_id"] == report["run_id"], "The latest pointer does not identify the successful run")
            return {
                "passed": True,
                "scope": "Real local HTTP transport plus adapter, harness, numerical engine and file publication; scripted stub responses, no live LLM.",
                "package_version": report["provenance"]["package_version"],
                "audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "requests": len(requests), "tool_calls": harness.tool_count,
                "premature_finalization_rejected": True,
                "mandatory_scenarios_verified": True,
                "all_accounting_checks_passed": True,
                "raw_actuals_sent": False,
                "model_text_or_api_key_persisted": False,
                "mode": report["mode"],
                "forecasts": sorted(report["forecasts"]),
                "diagnostics": sorted(report["diagnostics"]),
            }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/additional-audits/http_harness.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = audit(args.output.parent)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
