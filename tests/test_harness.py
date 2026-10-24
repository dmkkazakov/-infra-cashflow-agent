import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from infra_cashflow import harness as harness_module
from infra_cashflow.harness import (ForecastHarness, HarnessError, SCENARIOS, SENSITIVITY_SCENARIOS,
                                   render_report, validate_tool_call, verify_accounting)
from infra_cashflow.llm import PlannerError


def fixture_report():
    rows = []
    for i, month in enumerate(("2024-01", "2024-02")):
        cash = 10 + i * 6
        row = {"month": month, "opening_cash": cash, "receipts": 20.0, "capex": 5.0,
               "maintenance_capex": 1.0, "opex": 4.0, "tax": 1.0, "equity": 0.0,
               "cfads": 14.0, "free_cash_flow": 9.0, "interest": 1.0, "principal": 2.0,
               "debt_draw": 0.0, "debt_service": 3.0, "opening_debt": 20.0 - i * 2, "closing_debt": 18.0 - i * 2,
               "cumulative_drawn": 20.0, "unused_facility": 80.0, "closing_cash": cash + 6,
               "funding_gap": 0.0, "dscr": 14 / 3, "p10_cash": cash + 4,
               "p50_cash": cash + 6, "p90_cash": cash + 8}
        rows.append(row)
    return {"monthly": rows, "summary": {"min_cash": 16.0, "terminal_cash": 22.0,
            "probability_min_cash_below_floor": 0.2, "min_dscr": 14 / 3},
            "model": {}, "assumptions": {}}


def call(name, arguments, id="call-one"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def response(name, arguments, id):
    return {"role": "assistant", "content": "Fabricated text that must not enter the report.",
            "tool_calls": [call(name, arguments, id)]}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = {"as_of": "2023-12", "synthetic_data": True,
                        "actuals": [{"month": "2023-12", "receipts": 1}, {"month": "2024-01", "receipts": 999}]}
        self.validate = patch("infra_cashflow.harness.validate_project", return_value={"valid": True}).start()
        self.forecast = patch("infra_cashflow.harness.run_forecast", side_effect=lambda *args, **kwargs: fixture_report()).start()
        self.addCleanup(patch.stopall)

    def harness(self, **kwargs):
        return ForecastHarness(self.project, self.temporary.name, n_simulations=10, **kwargs)

    def test_offline_reports_reconcile_and_cached_run_avoids_recompute(self):
        harness = self.harness()
        with patch("urllib.request.build_opener") as network:
            result = harness.run()
            network.assert_not_called()
        self.assertEqual(result["mode"], "offline_workflow")
        self.assertEqual(self.forecast.call_count, 7)
        self.assertEqual(len(result["diagnostics"]), 4)
        self.assertEqual(result["provenance"]["observed_rows"], 1)
        self.assertTrue(all(check["passed"] for check in result["accounting_checks"].values()))
        self.assertEqual(len(list(harness.output_path.glob("forecast_*.csv"))), 7)
        before = self.forecast.call_count
        cached = self.harness().run()
        self.assertEqual(cached, result)
        self.assertEqual(self.forecast.call_count, before)

    def test_cache_detects_modified_csv(self):
        harness = self.harness()
        harness.run()
        (harness.output_path / "forecast_baseline.csv").write_text("altered")
        with self.assertRaises(HarnessError):
            self.harness().run()

    def test_cached_run_becomes_latest_after_another_run(self):
        first = self.harness(horizon=12)
        first_result = first.run()
        second = self.harness(horizon=24)
        second.run()
        latest_path = Path(self.temporary.name) / "latest.json"
        self.assertEqual(json.loads(latest_path.read_text())["run_id"], second.run_id)
        calls_before_cache_hit = self.forecast.call_count

        cached = self.harness(horizon=12).run()

        self.assertEqual(cached, first_result)
        self.assertEqual(self.forecast.call_count, calls_before_cache_hit)
        latest = json.loads(latest_path.read_text())
        self.assertEqual(latest["run_id"], first.run_id)
        self.assertEqual(latest["report"], f"{first.run_id}/report.json")

    def test_successful_retry_removes_previous_failure_marker(self):
        failed_planner = Mock(model="mock-model", endpoint="https://example.test/v1/chat/completions")
        failed_planner.next_action.return_value = response("shell", {}, "rejected")
        failed = self.harness(planner=failed_planner)
        with self.assertRaises(HarnessError):
            failed.run()
        failure_path = failed.output_path / "failure.json"
        self.assertTrue(failure_path.exists())

        planner = Mock(model="mock-model", endpoint="https://example.test/v1/chat/completions")
        planner.next_action.side_effect = [
            response("diagnose_driver", {"driver": "rate"}, "a"),
            response("run_scenario", {"scenario": "stress"}, "b"),
            response("run_scenario", {"scenario": "downside"}, "c"),
            response("finalize", {}, "d"),
        ]
        retry = self.harness(planner=planner)
        self.assertEqual(retry.run_id, failed.run_id)

        result = retry.run()

        self.assertEqual(result["status"], "complete")
        self.assertEqual(json.loads((retry.output_path / "manifest.json").read_text())["status"], "complete")
        self.assertFalse(failure_path.exists())

    def test_same_instance_retry_resets_attempt_state(self):
        planner = Mock(model="mock-model", endpoint="https://example.test/v1/chat/completions")
        planner.next_action.side_effect = [
            response("run_scenario", {"scenario": "downside"}, "a"),
            PlannerError("Temporary provider error"),
        ]
        harness = self.harness(planner=planner)
        with self.assertRaises(PlannerError):
            harness.run()
        planner.next_action.side_effect = [
            response("run_scenario", {"scenario": "downside"}, "a"),
            response("diagnose_driver", {"driver": "rate"}, "b"),
            response("run_scenario", {"scenario": "stress"}, "c"),
            response("finalize", {}, "d"),
        ]

        result = harness.run()

        self.assertEqual(result["status"], "complete")
        self.assertEqual(harness.tool_count, 4)
        self.assertEqual(self.forecast.call_count, 6)
        self.assertNotIn("run_failed", [event["operation"] for event in harness.events])
        self.assertFalse((harness.output_path / "failure.json").exists())

    def test_failed_pointer_write_does_not_leave_a_complete_cache(self):
        harness = self.harness()
        original_write = harness_module._atomic_write

        def fail_pointer(root, name, data):
            if name == "latest.json":
                raise OSError("Simulated pointer write failure")
            original_write(root, name, data)

        with patch("infra_cashflow.harness._atomic_write", side_effect=fail_pointer), self.assertRaises(OSError):
            harness.run()
        self.assertFalse((harness.output_path / "manifest.json").exists())
        self.assertTrue((harness.output_path / "failure.json").exists())

        result = harness.run()

        self.assertEqual(result["status"], "complete")
        self.assertFalse((harness.output_path / "failure.json").exists())
        self.assertEqual(self.harness().run(), result)

    def test_scenario_snapshot_and_returned_result_do_not_share_mutable_state(self):
        harness = self.harness()
        initial_id = harness.run_id
        with patch.dict(SCENARIOS["downside"], {"receipts_multiplier": 0.5}), \
                patch.dict(SENSITIVITY_SCENARIOS["rate"], {"annual_rate_shift": 0.30}):
            result = harness.run()
        used = {call.kwargs["scenario"]["name"]: call.kwargs["scenario"]
                for call in self.forecast.call_args_list}
        self.assertEqual(used["downside"]["receipts_multiplier"], 0.9)
        self.assertEqual(used["sensitivity_rate"]["annual_rate_shift"], 0.02)
        self.assertEqual(harness.run_id, initial_id)
        result["configuration"]["scenario_definitions"]["downside"]["receipts_multiplier"] = 0.4
        result["forecasts"]["baseline"]["summary"]["min_cash"] = 0
        self.assertEqual(harness.run_config["scenario_definitions"]["downside"]["receipts_multiplier"], 0.9)
        self.assertEqual(harness.reports["baseline"]["summary"]["min_cash"], 16.0)
        self.assertEqual(harness.run()["forecasts"]["baseline"]["summary"]["min_cash"], 16.0)

    def test_mutating_run_inputs_requires_a_new_instance(self):
        changes = [
            lambda h: h.project["actuals"][0].update(receipts=2),
            lambda h: setattr(h, "horizon", 24),
            lambda h: setattr(h, "objective", "Different task"),
            lambda h: h.run_config["scenario_definitions"]["downside"].update(receipts_multiplier=0.5),
            lambda h: setattr(h, "planner", Mock(model="other-model")),
        ]
        for change in changes:
            with self.subTest(change=change):
                harness = self.harness()
                change(harness)
                with self.assertRaisesRegex(HarnessError, "inputs or configuration changed"):
                    harness.run()
        self.forecast.assert_not_called()

    def test_corrupt_or_incomplete_cache_is_rejected_without_recalculation(self):
        harness = self.harness()
        harness.run()
        manifest = harness.output_path / "manifest.json"
        original = json.loads(manifest.read_text())
        missing_csv = copy.deepcopy(original)
        del missing_csv["artifact_sha256"]["forecast_sensitivity_rate.csv"]
        invalid = [[], {}, {**original, "artifact_sha256": {}},
                   {**original, "artifact_sha256": []},
                   {**original, "input_sha256": "different"}, missing_csv]
        calls_before = self.forecast.call_count
        for value in invalid:
            with self.subTest(manifest=value):
                manifest.write_text(json.dumps(value))
                with self.assertRaisesRegex(HarnessError, "Cached artifacts are incomplete or invalid"):
                    self.harness().run()
        self.assertEqual(self.forecast.call_count, calls_before)

    def test_explicit_empty_or_nontext_cutoff_is_not_replaced_by_default(self):
        for cutoff in ("", False, 0):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                self.harness(as_of=cutoff)

    def test_invalid_cash_identity_prevents_success_artifact(self):
        broken = fixture_report()
        broken["monthly"][0]["closing_cash"] += 1
        self.forecast.side_effect = lambda *args, **kwargs: copy.deepcopy(broken)
        harness = self.harness()
        with self.assertRaises(HarnessError):
            harness.run()
        self.assertFalse((harness.output_path / "manifest.json").exists())
        self.assertFalse((harness.output_path / "report.json").exists())
        self.assertTrue((harness.output_path / "failure.json").exists())

    def test_optional_planner_selects_diagnostic_with_checked_results(self):
        planner = Mock(model="mock-model", endpoint="https://example.test/v1/chat/completions")
        planner.next_action.side_effect = [
            response("diagnose_driver", {"driver": "rate"}, "a"),
            response("run_scenario", {"scenario": "stress"}, "b"),
            response("run_scenario", {"scenario": "downside"}, "c"),
            response("finalize", {}, "d"),
        ]
        harness = self.harness(planner=planner)
        result = harness.run()
        self.assertEqual(result["mode"], "llm_planned")
        self.assertEqual(set(result["diagnostics"]), {"rate"})
        self.assertNotIn("Fabricated text", (harness.output_path / "report.json").read_text())
        self.assertNotIn("Fabricated text", (harness.output_path / "audit.jsonl").read_text())
        first_messages = planner.next_action.call_args_list[0].args[0]
        self.assertNotIn('"actuals"', json.dumps(first_messages))

    def test_planner_cannot_skip_required_checks(self):
        planner = Mock(model="mock-model")
        planner.next_action.side_effect = [response("finalize", {}, str(i)) for i in range(3)]
        harness = self.harness(planner=planner, max_model_rounds=3)
        with self.assertRaises(HarnessError):
            harness.run()
        self.assertEqual(planner.next_action.call_count, 3)
        self.assertFalse((harness.output_path / "report.json").exists())

    def test_arbitrary_tool_or_financial_values_are_rejected(self):
        cases = [("shell", {"command": "bad"}), ("run_scenario", {"scenario": "downside", "capex": 0}),
                 ("diagnose_driver", {"driver": "override"}), ("finalize", {"cash": 100}),
                 ("run_scenario", {"scenario": []})]
        for tool, args in cases:
            with self.subTest(tool=tool, args=args), self.assertRaises(HarnessError):
                validate_tool_call(call(tool, args))

    def test_nonfinite_and_unordered_intervals_are_rejected(self):
        report = fixture_report()
        report["summary"]["terminal_cash"] = float("nan")
        with self.assertRaises(HarnessError):
            verify_accounting(report)
        report = fixture_report()
        report["monthly"][0]["p10_cash"] = 999
        with self.assertRaises(HarnessError):
            verify_accounting(report)

    def test_zero_debt_service_requires_null_dscr(self):
        report = fixture_report()
        row = report["monthly"][0]
        row.update(interest=0, principal=0, debt_service=0, closing_cash=19, closing_debt=20, dscr=None)
        report["monthly"] = [row]
        report["summary"].update(min_cash=19, terminal_cash=19, min_dscr=None)
        self.assertTrue(verify_accounting(report)["passed"])
        row["dscr"] = 0
        with self.assertRaises(HarnessError):
            verify_accounting(report)

    def test_first_month_debt_and_summary_are_independently_verified(self):
        report = fixture_report()
        report["monthly"][0]["opening_debt"] += 1
        with self.assertRaises(HarnessError):
            verify_accounting(report)
        report = fixture_report()
        report["summary"]["min_cash"] = 9000
        with self.assertRaises(HarnessError):
            verify_accounting(report)

    def test_false_funding_gap_or_dscr_summary_is_rejected(self):
        report = fixture_report()
        report["summary"]["minimum_cash_floor"] = 0.0
        report["monthly"][0]["funding_gap"] = 987654.0
        with self.assertRaisesRegex(HarnessError, "funding_gap"):
            verify_accounting(report)
        report = fixture_report()
        report["summary"]["min_dscr"] = 12345.0
        with self.assertRaisesRegex(HarnessError, "min_dscr"):
            verify_accounting(report)

    def test_operating_dscr_is_checked_separately_from_all_period_dscr(self):
        report = fixture_report()
        # One operating month, with a different ratio from construction month.
        row = report["monthly"][1]
        row.update(receipts=23.0, cfads=17.0, free_cash_flow=12.0, closing_cash=25.0, dscr=17 / 3)
        report["summary"].update(effective_operations_start="2024-02", terminal_cash=25.0,
                                  min_dscr=17 / 3, min_dscr_all_periods=14 / 3)
        self.assertTrue(verify_accounting(report)["passed"])
        report["summary"]["min_dscr_all_periods"] = 17 / 3
        with self.assertRaisesRegex(HarnessError, "min_dscr_all_periods"):
            verify_accounting(report)

    def test_generated_report_dscr_header_discloses_operating_scope(self):
        result = self.harness().run()
        text = render_report(result)
        self.assertIn("Minimum operating-month DSCR", text)
        self.assertNotIn("| Minimum monthly DSCR |", text)

    def test_balanced_but_wrong_interest_fails_independent_financing_gate(self):
        report = fixture_report()
        report["monthly"] = report["monthly"][:1]
        report["summary"]["terminal_cash"] = 16.0
        report["monthly"][0]["scheduled_principal"] = 2.0
        financing = {"annual_interest_rate": 0.60, "minimum_cash": 0.0,
                     "facility_limit": 100.0, "availability_end": "2024-12"}
        self.assertTrue(verify_accounting(report, financing=financing)["passed"])
        # Update every dependent ledger total to make the wrong interest
        # arithmetically self-consistent: the external rate must still catch it.
        row = report["monthly"][0]
        row.update(interest=2.0, debt_service=4.0, closing_cash=15.0, dscr=3.5)
        report["summary"].update(min_cash=15.0, terminal_cash=15.0, min_dscr=3.5)
        with self.assertRaisesRegex(HarnessError, "interest_convention"):
            verify_accounting(report, financing=financing)


if __name__ == "__main__":
    unittest.main()
