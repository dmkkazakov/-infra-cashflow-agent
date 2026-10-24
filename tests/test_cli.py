"""CLI regression for applying an explicit historical information cutoff."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from infra_cashflow.cli import main
from infra_cashflow.data import make_demo_project


class CutoffCLITests(unittest.TestCase):
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
