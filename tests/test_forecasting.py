import copy
import json
import math
import unittest
from decimal import Decimal
from fractions import Fraction
from unittest.mock import patch

import numpy as np

from infra_cashflow.data import AMOUNT_FIELDS, add_months, make_demo_project, observed_project, validate_project
from infra_cashflow.forecasting import _cash_path_simulation, backtest, fit_corrections, run_forecast


def small_cash_fixture(months=6, observed=3, start="2022-01"):
    baseline = [{"month": add_months(start, i), **{c: 0.0 for c in AMOUNT_FIELDS}} for i in range(months)]
    return {
        "schema_version": "1.0", "project_id": "numerical-boundary", "synthetic_data": True,
        "currency": "RUB", "amount_unit": "million", "baseline_vintage": start,
        "as_of": add_months(start, observed - 1), "baseline": baseline,
        "actuals": [{**r, "debt_draw": 0.0, "interest": 0.0} for r in baseline],
        "financing": {"opening_cash": 0.0, "opening_debt": 0.0, "opening_cumulative_drawn": 0.0,
                      "facility_limit": 0.0, "minimum_cash": 0.0, "annual_interest_rate": 0.0,
                      "availability_end": add_months(start, months - 1)},
    }


class ForecastEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = make_demo_project()

    def test_future_outcome_changes_cannot_change_forecast(self):
        changed = copy.deepcopy(self.project)
        for row in changed["actuals"]:
            if row["month"] > changed["as_of"]:
                row["receipts"] = row["receipts"] * 1000.0 + 123.0
                row["capex"] = row["capex"] * 50.0 + 321.0
        one = run_forecast(self.project, horizon=18, n_simulations=128, seed=77)
        two = run_forecast(changed, horizon=18, n_simulations=128, seed=77)
        self.assertEqual(one["model"], two["model"])
        self.assertEqual(one["monthly"], two["monthly"])
        self.assertEqual(one["summary"], two["summary"])
        self.assertEqual(one["actual_ledger"], two["actual_ledger"])

    def test_requested_earlier_cutoff_also_controls_financing_validation(self):
        changed = copy.deepcopy(self.project)
        # This payment is after the explicit cutoff but before the fixture's
        # default cutoff. Replaying it would be an information-boundary error.
        changed["actuals"][17]["principal"] = 1_000_000.0
        one = run_forecast(self.project, as_of="2022-12", horizon=3, n_simulations=20)
        two = run_forecast(changed, as_of="2022-12", horizon=3, n_simulations=20)
        self.assertEqual(one["model"], two["model"])
        self.assertEqual(one["monthly"], two["monthly"])
        self.assertEqual(one["summary"], two["summary"])

    def test_exact_past_ratio_with_prior_shrinkage(self):
        p = observed_project(self.project, "2022-12")
        for row in p["baseline"][:12]:
            row["receipts"] = 10.0
        for row in p["actuals"]:
            row["receipts"] = 20.0
        model = fit_corrections(p)
        self.assertAlmostEqual(model["components"]["receipts"]["multiplier"], 1.8, places=12)
        self.assertEqual(model["components"]["receipts"]["active_observations"], 12)

    def test_quantiles_ordered_and_json_finite(self):
        result = run_forecast(self.project, n_simulations=128, seed=77)
        json.dumps(result, allow_nan=False)
        for row in result["monthly"]:
            self.assertLessEqual(row["p10_cash"], row["p50_cash"])
            self.assertLessEqual(row["p50_cash"], row["p90_cash"])
            self.assertTrue(0 <= row["probability_cash_below_floor"] <= 1)

    def test_direct_forecast_rejects_simulation_and_reduction_overflow(self):
        # The point ledger is finite in both cases. Random receipts overflow
        # in the first; aggregation of individually finite gaps in the second.
        for component, amount in (("receipts", 1.5e308), ("capex", 1e306)):
            with self.subTest(component=component):
                p = small_cash_fixture(months=2, observed=1)
                p["baseline"][1][component] = amount
                with self.assertRaisesRegex(ValueError, "overflow|nonfinite"):
                    run_forecast(p, horizon=1, n_simulations=1000, seed=42)

    def test_backtest_rejects_overflowing_squared_errors(self):
        p = small_cash_fixture()
        for r in p["actuals"][3:]:
            r["receipts"] = 1e200
        with self.assertRaisesRegex(ValueError, "overflow|nonfinite"):
            backtest(p, min_train=3, horizon=1)

    def test_backtest_wape_cannot_become_zero_from_an_infinite_denominator(self):
        p = small_cash_fixture()
        for r in p["baseline"]:
            r.update(receipts=9.9e307, opex=9.9e307)
        for r in p["actuals"]:
            r.update(receipts=1e308, opex=1e308)
        # Net cash flow is zero, so only the component aggregation overflows.
        # Without an intermediate check its true nonzero WAPE becomes 0/Inf.
        with self.assertRaisesRegex(ValueError, "overflow|nonfinite"):
            backtest(p, min_train=3, horizon=1)

    def test_reproducible_same_seed(self):
        a = run_forecast(self.project, horizon=12, n_simulations=50, seed=33)
        b = run_forecast(self.project, horizon=12, n_simulations=50, seed=33)
        self.assertEqual(a, b)

    def test_history_is_not_mutated(self):
        p = copy.deepcopy(self.project)
        run_forecast(p, horizon=12, n_simulations=20)
        self.assertEqual(p, self.project)

    def test_delay_conserves_components_including_deferred_tail(self):
        base = run_forecast(self.project, n_simulations=20)
        delayed = run_forecast(self.project, n_simulations=20, scenario={"delay_months": 6})
        for c in ("receipts", "capex", "opex", "tax", "maintenance_capex"):
            total = sum(r[c] for r in delayed["monthly"]) + delayed["summary"]["deferred_beyond_horizon"][c]
            self.assertAlmostEqual(total, sum(r[c] for r in base["monthly"]), places=8)
        self.assertGreater(delayed["summary"]["deferred_receipts"], 0.0)
        self.assertEqual([r["scheduled_principal"] for r in base["monthly"]], [r["scheduled_principal"] for r in delayed["monthly"]])

    def test_delay_at_first_supported_month_has_zero_suspension_flows(self):
        p = small_cash_fixture(months=4, observed=1, start="1900-01")
        for i, row in enumerate(p["baseline"]):
            row["receipts"] = i * 10.0
        result = run_forecast(p, horizon=5, n_simulations=20, scenario={"delay_months": 3})
        self.assertEqual([r["month"] for r in result["monthly"]],
                         ["1900-02", "1900-03", "1900-04", "1900-05", "1900-06"])
        self.assertEqual([r["receipts"] for r in result["monthly"]], [0.0, 0.0, 0.0, 10.0, 20.0])
        self.assertEqual(result["summary"]["deferred_receipts"], 30.0)

    def test_initial_state_matches_last_actual(self):
        result = run_forecast(self.project, horizon=12, n_simulations=20)
        self.assertEqual(result["monthly"][0]["opening_cash"], result["actual_ledger"][-1]["closing_cash"])
        self.assertEqual(result["monthly"][0]["opening_debt"], result["actual_ledger"][-1]["closing_debt"])

    def test_horizon_cannot_silently_extend_past_available_plan(self):
        with self.assertRaisesRegex(ValueError, "horizon exceeds"):
            run_forecast(self.project, horizon=61, n_simulations=20)
        with self.assertRaisesRegex(ValueError, "horizon exceeds"):
            run_forecast(self.project, horizon=67, n_simulations=20, scenario={"delay_months": 6})
        extended = run_forecast(self.project, horizon=66, n_simulations=20, scenario={"delay_months": 6})
        self.assertAlmostEqual(extended["summary"]["deferred_receipts"], 0.0)

    def test_delay_cannot_create_a_schedule_after_last_known_baseline_month(self):
        p = copy.deepcopy(self.project)
        p["as_of"] = p["baseline"][-1]["month"]
        with self.assertRaisesRegex(ValueError, "No unobserved baseline"):
            run_forecast(p, horizon=3, n_simulations=10, scenario={"delay_months": 3})

    def test_rate_shock_does_not_change_observed_state(self):
        base = run_forecast(self.project, horizon=12, n_simulations=20)
        shocked = run_forecast(self.project, horizon=12, n_simulations=20, scenario={"annual_rate_shift": 0.02})
        self.assertEqual(base["actual_ledger"], shocked["actual_ledger"])
        self.assertGreater(shocked["monthly"][0]["interest"], base["monthly"][0]["interest"])

    def test_backtest_count_and_no_percentage_error_on_net_cash(self):
        report = backtest(self.project, min_train=12, horizon=3)
        self.assertEqual(report["rolling_origins"], 70)
        self.assertEqual(report["prediction_count"], 210)
        self.assertEqual(set(report["methods"]), {"plan", "last_observation", "adjusted"})
        self.assertNotIn("mape", json.dumps(report).lower())
        for metrics in report["methods"].values():
            self.assertGreaterEqual(metrics["net_cashflow_rmse"], metrics["net_cashflow_mae"] - 1e-10)

    def test_duplicate_month_and_nonfinite_and_invalid_rate_rejected(self):
        p = copy.deepcopy(self.project)
        p["baseline"][1]["month"] = p["baseline"][0]["month"]
        with self.assertRaises(ValueError):
            validate_project(p)
        p = copy.deepcopy(self.project)
        p["actuals"][0]["capex"] = float("nan")
        with self.assertRaises(ValueError):
            validate_project(p)
        with self.assertRaises(ValueError):
            run_forecast(self.project, n_simulations=20, scenario={"annual_rate_shift": 1.0})

    def test_actual_history_prefix_and_units_validated(self):
        p = copy.deepcopy(self.project)
        p["actuals"] = p["actuals"][1:]
        with self.assertRaises(ValueError):
            validate_project(p)
        p = copy.deepcopy(self.project)
        p["amount_unit"] = "rubles"
        with self.assertRaises(ValueError):
            validate_project(p)

    def test_zero_service_retains_null(self):
        p = copy.deepcopy(self.project)
        p["financing"]["opening_cash"] = 100000.0
        p["actuals"] = [{k: v for k, v in row.items() if k not in ("debt_draw", "interest")} for row in p["actuals"]]
        result = run_forecast(p, n_simulations=20)
        self.assertTrue(all(row["dscr"] is None for row in result["monthly"]))
        self.assertIsNone(result["summary"]["min_dscr"])


class IndependentNumericalOracleTests(unittest.TestCase):
    """Small exact oracles do not call the production estimator or ledger."""

    def receipt_fixture(self):
        p = make_demo_project()
        template = {"receipts": 0.0, "capex": 0.0, "opex": 0.0, "tax": 0.0,
                    "maintenance_capex": 0.0, "equity": 0.0, "principal": 0.0}
        p["baseline"] = [{**template, "month": f"2022-{i+1:02d}", "receipts": 10.0} for i in range(6)]
        p["actuals"] = [{**template, "month": f"2022-{i+1:02d}", "receipts": float(value),
                         "debt_draw": 0.0, "interest": 0.0} for i, value in enumerate([8, 12, 16, 10, 20, 4])]
        p.update(as_of="2022-03", operations_start="2022-01")
        p["financing"] = {"opening_cash": 1000.0, "opening_debt": 0.0, "opening_cumulative_drawn": 0.0,
                           "facility_limit": 0.0, "annual_interest_rate": 0.0,
                           "minimum_cash": 0.0, "availability_end": "2022-12"}
        return p

    def exact_multiplier(self, actuals):
        n = len(actuals)
        weights = [Fraction(17, 20) ** (n - 1 - i) for i in range(n)]
        weighted_ratio = sum(w * Fraction(value, 10) for w, value in zip(weights, actuals)) / sum(weights)
        return (n * weighted_ratio + 3) / (n + 3)

    def test_ewma_and_pooled_metrics_against_exact_fraction_oracle(self):
        p = self.receipt_fixture()
        actual = [8, 12, 16, 10, 20, 4]
        exact = self.exact_multiplier(actual[:3])
        self.assertEqual(exact, Fraction(3847, 3430))
        got = fit_corrections(p)["components"]["receipts"]["multiplier"]
        self.assertAlmostEqual(got, float(exact), places=13)
        report = backtest(p, min_train=3, horizon=2)
        errors = {"plan": [], "last_observation": [], "adjusted": []}
        for origin_count in (3, 4):
            predictions = {"plan": Fraction(10), "last_observation": Fraction(actual[origin_count-1]),
                           "adjusted": 10 * self.exact_multiplier(actual[:origin_count])}
            for target_index in (origin_count, origin_count + 1):
                for name, prediction in predictions.items():
                    errors[name].append(prediction - actual[target_index])
        self.assertEqual(report["rolling_origins"], 2)
        self.assertEqual(report["prediction_count"], 4)
        for name, values in errors.items():
            absolute_sum = sum(abs(value) for value in values)
            squared_sum = sum(value * value for value in values)
            metrics = report["methods"][name]
            self.assertAlmostEqual(metrics["absolute_error_sum"], float(absolute_sum), places=11)
            self.assertAlmostEqual(metrics["squared_error_sum"], float(squared_sum), places=11)
            self.assertAlmostEqual(metrics["net_cashflow_mae"], float(absolute_sum / 4), places=12)
            self.assertAlmostEqual(metrics["net_cashflow_rmse"], math.sqrt(float(squared_sum / 4)), places=12)
            self.assertAlmostEqual(metrics["net_cashflow_bias"], float(sum(values) / 4), places=12)
        self.assertAlmostEqual(report["methods"]["plan"]["net_cashflow_mae"], 6.5)
        self.assertAlmostEqual(report["methods"]["plan"]["net_cashflow_rmse"], math.sqrt(59))

    def test_vectorized_waterfall_against_decimal_hand_calculation(self):
        components = ["receipts", "capex", "opex", "tax", "maintenance_capex"]
        model = {"components": {c: {"conditional_log_noise_sd": 0.0, "parameter_log_noise_sd": 0.0} for c in components}}
        rows = [
            {"month": "2024-01", "receipts": 0, "capex": 30, "opex": 5, "tax": 0, "maintenance_capex": 1, "equity": 0, "principal": 10},
            {"month": "2024-02", "receipts": 80, "capex": 0, "opex": 10, "tax": 3, "maintenance_capex": 2, "equity": 0, "principal": 90},
            {"month": "2024-03", "receipts": 0, "capex": 20, "opex": 0, "tax": 0, "maintenance_capex": 0, "equity": 0, "principal": 0},
        ]
        financing = {"annual_interest_rate": 0.12, "facility_limit": 100.0, "minimum_cash": 10.0, "availability_end": "2024-02"}
        state = {"cash": 20.0, "debt": 50.0, "cumulative_drawn": 70.0}
        cash, fcf, dscr = _cash_path_simulation(rows, financing, state, model, 3, 42)
        # Month1: 20 - 36 - .5 - 10 + 30 = 3.5; debt70, commitment exhausted.
        # Month2: 3.5 +65 -.7 -70 = -2.2; month3: -2.2 -20 = -22.2.
        expected_cash = [Decimal('3.5'), Decimal('-2.2'), Decimal('-22.2')]
        for path in range(3):
            np.testing.assert_allclose(cash[path], [float(x) for x in expected_cash], rtol=0, atol=1e-12)
            np.testing.assert_allclose(fcf[path], [-36, 65, -20], rtol=0, atol=1e-12)
            self.assertAlmostEqual(dscr[path, 0], float(Decimal(-6) / Decimal('10.5')), places=12)
            self.assertAlmostEqual(dscr[path, 1], float(Decimal(65) / Decimal('70.7')), places=12)
            self.assertTrue(math.isnan(dscr[path, 2]))

    def test_monte_carlo_principal_uses_each_paths_own_debt(self):
        components = ["receipts", "capex", "opex", "tax", "maintenance_capex"]
        model = {"components": {c: {"conditional_log_noise_sd": 1.0 if c == "capex" else 0.0,
                                    "parameter_log_noise_sd": 0.0} for c in components}}
        rows = [
            {"month": "2024-01", "receipts": 0, "capex": 50, "opex": 0, "tax": 0, "maintenance_capex": 0, "equity": 0, "principal": 0},
            {"month": "2024-02", "receipts": 200, "capex": 0, "opex": 0, "tax": 0, "maintenance_capex": 0, "equity": 0, "principal": 90},
        ]
        financing = {"annual_interest_rate": 0.0, "facility_limit": 100.0, "minimum_cash": 0.0, "availability_end": "2024-01"}
        state = {"cash": 0.0, "debt": 50.0, "cumulative_drawn": 50.0}
        individual = np.zeros((2, 2, 5))
        # Choose CAPEX multipliers 1 and 1/2 by setting the normal innovation;
        # the second month has no CAPEX, so its innovation has no cash effect.
        individual[0, 0, 1] = 0.5 / math.sqrt(0.65)
        individual[1, 0, 1] = (math.log(0.5) + 0.5) / math.sqrt(0.65)
        class FixedNormals:
            def __init__(self):
                self.values = iter([np.zeros((2, 2, 1)), individual, np.zeros((2, 1)), np.zeros((2, 5))])
            def normal(self, size):
                value = next(self.values)
                assert value.shape == size
                return value
        with patch("infra_cashflow.forecasting.np.random.default_rng", return_value=FixedNormals()):
            cash, _, _ = _cash_path_simulation(rows, financing, state, model, 2, 42)
        # Debts are100 and75 after month1: month2 pays90 and75, respectively.
        np.testing.assert_allclose(cash[:, 1], [110.0, 125.0], rtol=0, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
