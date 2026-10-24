import copy
import json
from pathlib import Path
import tempfile
import unittest

from infra_cashflow.data import add_months, load_project, month_number, observed_project, rows_from_csv, validate_project


def row(month, **values):
    return {"month": month, "receipts": 0.0, "capex": 0.0, "opex": 0.0, "tax": 0.0,
            "maintenance_capex": 0.0, "equity": 0.0, "principal": 0.0, **values}


def project():
    return {
        "schema_version": "1.0", "project_id": "validation-regression", "synthetic_data": True,
        "currency": "RUB", "amount_unit": "million", "baseline_vintage": "2021-12", "as_of": "2022-01",
        "financing": {"opening_cash": 100.0, "opening_debt": 40.0, "opening_cumulative_drawn": 40.0,
                      "facility_limit": 100.0, "annual_interest_rate": 0.12, "minimum_cash": 0.0,
                      "availability_end": "2022-12"},
        "baseline": [row("2022-01"), row("2022-02"), row("2022-03")],
        "actuals": [row("2022-01")],
    }


class InputIntegrityTests(unittest.TestCase):
    def test_zero_historical_draws_and_facility_cannot_hide_positive_opening_balances(self):
        for balances in ({"opening_debt": 5e-10, "opening_cumulative_drawn": 0.0},
                         {"opening_debt": 0.0, "opening_cumulative_drawn": 5e-10, "facility_limit": 0.0}):
            with self.subTest(balances=balances):
                p = project()
                p["financing"].update(balances)
                with self.assertRaisesRegex(ValueError, "Opening"):
                    validate_project(p)

    def test_actual_principal_cannot_be_silently_capped_in_validation(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded):
                p = project()
                p["actuals"][0]["principal"] = 50.0
                if recorded:
                    p["actuals"][0].update(debt_draw=0.0, interest=0.4)
                with self.assertRaisesRegex(ValueError, "actual principal"):
                    validate_project(p)

    def test_recorded_draw_limit_and_availability_checked_in_validation(self):
        p = project()
        p["actuals"][0].update(debt_draw=61.0, interest=0.4)
        with self.assertRaisesRegex(ValueError, "facility"):
            validate_project(p)
        p["actuals"][0]["debt_draw"] = 10.0
        p["financing"]["availability_end"] = "2021-12"
        with self.assertRaisesRegex(ValueError, "availability"):
            validate_project(p)

    def test_history_holes_and_missing_start_rejected(self):
        p = project()
        p["actuals"] = [row("2022-01"), row("2022-03")]
        p["as_of"] = "2022-03"
        with self.assertRaisesRegex(ValueError, "consecutive"):
            validate_project(p)
        p = project()
        p["actuals"] = [row("2022-02")]
        p["as_of"] = "2022-02"
        with self.assertRaisesRegex(ValueError, "start"):
            validate_project(p)

    def test_unknown_financial_row_field_not_silently_ignored(self):
        p = project()
        p["actuals"][0]["closing_cash"] = 999.0
        with self.assertRaisesRegex(ValueError, "unsupported"):
            validate_project(p)

    def test_duplicate_json_amount_rejected_instead_of_last_value_wins(self):
        text = json.dumps(project()).replace('"capex": 0.0', '"capex": 100.0, "capex": 0.0', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                load_project(path)

    def test_valid_json_round_trip_keeps_cash_values(self):
        expected = project()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.json"
            path.write_text(json.dumps(expected), encoding="utf-8")
            self.assertEqual(load_project(path), expected)

    def test_load_project_validates_requested_cutoff_before_later_financing(self):
        p = project()
        p["actuals"].append(row("2022-02", principal=999.0, debt_draw=0.0, interest=0.0))
        p["as_of"] = "2022-02"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "later_bad_financing.json"
            path.write_text(json.dumps(p), encoding="utf-8")
            earlier = load_project(path, as_of="2022-01")
            self.assertEqual(earlier["as_of"], "2022-01")
            with self.assertRaisesRegex(ValueError, "actual principal"):
                load_project(path)
            with self.assertRaisesRegex(ValueError, "actual principal"):
                load_project(path, as_of="2022-02")

    def test_csv_duplicate_and_missing_columns_rejected(self):
        header = "month,receipts,capex,opex,tax,maintenance_capex,equity,principal"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text(header + ",capex\n2022-01,0,100,0,0,0,0,0,0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                rows_from_csv(path)
            path.write_text("month,receipts\n2022-01,100\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required"):
                rows_from_csv(path)

    def test_csv_nonfinite_blank_and_misaligned_amounts_rejected(self):
        header = "month,receipts,capex,opex,tax,maintenance_capex,equity,principal\n"
        bad_rows = ["2022-01,nan,0,0,0,0,0,0\n", "2022-01,0,,0,0,0,0,0\n", "2022-01,0,0,0,0,0,0,0,999\n"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            for values in bad_rows:
                with self.subTest(values=values):
                    path.write_text(header + values, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        rows_from_csv(path)

    def test_csv_missing_month_cannot_remove_interest_period(self):
        header = "month,receipts,capex,opex,tax,maintenance_capex,equity,principal\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gap.csv"
            path.write_text(header + "2022-01,0,0,0,0,0,0,0\n2022-03,0,0,0,0,0,0,0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "consecutive"):
                rows_from_csv(path)

    def test_explicit_empty_cutoff_does_not_fall_back_to_a_different_date(self):
        with self.assertRaises(ValueError):
            observed_project(project(), "")

    def test_months_use_one_ascii_format_and_bounded_integer_arithmetic(self):
        with self.assertRaises(ValueError):
            month_number("٢٠٢٢-01")
        with self.assertRaises(ValueError):
            add_months("2022-01", True)
        with self.assertRaises(ValueError):
            add_months("1900-01", -1)
        self.assertEqual(add_months("2022-12", 1), "2023-01")

    def test_financing_validation_uses_only_observed_prefix(self):
        p = project()
        p["actuals"].append(row("2022-02", principal=999.0, debt_draw=0.0, interest=0.0))
        self.assertTrue(validate_project(p)["valid"])
        p["as_of"] = "2022-02"
        with self.assertRaisesRegex(ValueError, "actual principal"):
            validate_project(p)


if __name__ == "__main__":
    unittest.main()
