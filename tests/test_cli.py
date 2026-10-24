"""CLI regression for applying an explicit historical information cutoff."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from infra_cashflow.cli import main
from infra_cashflow.data import make_demo_project


class CutoffCLITests(unittest.TestCase):
    def test_malformed_api_key_does_not_appear_in_cli_error(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"CASHFLOW_LLM_API_KEY": "DUMMY_SECRET\n"}), \
                patch("urllib.request.build_opener") as opener, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            status = main(["demo", "--mode", "llm", "--allow-network", "--llm-model", "mock",
                           "--llm-base-url", "http://127.0.0.1:1/v1", "--output", temporary])
        self.assertEqual(status, 2)
        self.assertNotIn("DUMMY_SECRET", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        opener.assert_not_called()

    def test_malformed_cache_is_a_cli_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = ["demo", "--simulations", "10", "--horizon", "1", "--output", temporary]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(command), 0)
            latest = json.loads((root / "latest.json").read_text())
            (root / latest["run_id"] / "manifest.json").write_text("[]")
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                status = main(command)
            self.assertEqual(status, 2)
            self.assertIn("Cached artifacts are incomplete or invalid", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_requested_cutoff_excludes_future_financing_contradiction(self):
        project = make_demo_project()
        future = next(row for row in project["actuals"] if row["month"] == "2023-06")
        future["principal"] = 1_000_000.0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "project.json"
            source.write_text(json.dumps(project))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = main(["run", str(source), "--as-of", "2022-12", "--simulations", "32",
                               "--output", str(root / "results")])
            self.assertEqual(status, 0)
            latest = json.loads((root / "results/latest.json").read_text())
            report = json.loads((root / "results" / latest["run_id"] / "report.json").read_text())
            self.assertEqual(report["as_of"], "2022-12")
            for forecast in report["forecasts"].values():
                self.assertEqual(forecast["actual_ledger"][-1]["month"], "2022-12")


if __name__ == "__main__":
    unittest.main()
