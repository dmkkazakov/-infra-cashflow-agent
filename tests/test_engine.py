import math
import unittest

from infra_cashflow.data import add_months
from infra_cashflow.engine import cashflow_ledger, closing_state


def cash_row(month, **values):
    return {"month": month, "receipts": 0.0, "capex": 0.0, "opex": 0.0,
            "tax": 0.0, "maintenance_capex": 0.0, "equity": 0.0, "principal": 0.0, **values}


def terms(**values):
    return {"opening_cash": 0.0, "opening_debt": 0.0, "opening_cumulative_drawn": 0.0,
            "facility_limit": 100.0, "annual_interest_rate": 0.12, "minimum_cash": 0.0,
            "availability_end": "2022-12", **values}


class CashWaterfallTests(unittest.TestCase):
    def test_hand_calculated_cfads_and_dscr(self):
        fin = terms(opening_cash=50.0, opening_debt=100.0, opening_cumulative_drawn=100.0)
        row = cash_row("2022-01", receipts=200.0, capex=50.0, opex=60.0, tax=20.0, maintenance_capex=10.0, principal=10.0)
        got = cashflow_ledger([row], fin)[0]
        self.assertEqual(got["cfads"], 110.0)
        self.assertEqual(got["free_cash_flow"], 60.0)
        self.assertEqual(got["interest"], 1.0)
        self.assertEqual(got["dscr"], 10.0)
        self.assertEqual(got["closing_cash"], 99.0)
        self.assertEqual(got["closing_debt"], 90.0)

    def test_nonrevolving_draw_cap_not_restored_by_repayment(self):
        rows = [cash_row("2022-01", capex=100.0), cash_row("2022-02", receipts=120.0, principal=100.0), cash_row("2022-03", capex=50.0)]
        ledger = cashflow_ledger(rows, terms())
        self.assertEqual(ledger[0]["debt_draw"], 100.0)
        self.assertEqual(ledger[0]["interest"], 0.0)
        self.assertEqual(ledger[1]["interest"], 1.0)
        self.assertEqual(ledger[1]["closing_debt"], 0.0)
        self.assertEqual(ledger[2]["debt_draw"], 0.0)
        self.assertEqual(ledger[2]["closing_cash"], -31.0)
        self.assertEqual(ledger[2]["funding_gap"], 31.0)

    def test_no_service_dscr_is_null(self):
        got = cashflow_ledger([cash_row("2022-01", receipts=100)], terms())[0]
        self.assertIsNone(got["dscr"])

    def test_no_funding_after_facility_expiry(self):
        got = cashflow_ledger([cash_row("2022-02", capex=90)], terms(availability_end="2022-01"))[0]
        self.assertEqual(got["debt_draw"], 0.0)
        self.assertEqual(got["closing_cash"], -90.0)

    def test_negative_cash_does_not_cancel_contractual_debt_service(self):
        got = cashflow_ledger([cash_row("2022-01", principal=20)], terms(opening_debt=100, opening_cumulative_drawn=100))[0]
        self.assertEqual(got["principal"], 20.0)
        self.assertEqual(got["debt_service"], 21.0)
        self.assertEqual(got["closing_cash"], -21.0)
        self.assertEqual(got["dscr"], 0.0)

    def test_recorded_financing_is_honored(self):
        rows = [cash_row("2022-01", capex=50, debt_draw=70, interest=2)]
        got = cashflow_ledger(rows, terms())[0]
        self.assertEqual(got["debt_draw"], 70.0)
        self.assertEqual(got["closing_cash"], 18.0)
        self.assertEqual(got["closing_debt"], 70.0)

    def test_invalid_recorded_debt_draw_is_rejected(self):
        with self.assertRaises(ValueError):
            cashflow_ledger([cash_row("2022-01", debt_draw=101, interest=0)], terms())
        with self.assertRaises(ValueError):
            cashflow_ledger([cash_row("2023-01", debt_draw=10, interest=0)], terms())

    def test_observed_principal_is_never_silently_rewritten(self):
        fin = terms(opening_debt=40, opening_cumulative_drawn=40)
        with self.assertRaisesRegex(ValueError, "actual principal"):
            cashflow_ledger([cash_row("2022-01", principal=50, debt_draw=0, interest=0.4)], fin)
        # A future contractual repayment schedule may safely retire only the
        # outstanding balance; this is explicitly different from an actual.
        forecast = cashflow_ledger([cash_row("2022-01", principal=50)], fin)[0]
        self.assertEqual(forecast["principal"], 40.0)
        self.assertEqual(forecast["scheduled_principal"], 50.0)

    def test_zero_debt_cannot_absorb_any_positive_actual_payment(self):
        for historical_draws in (0.0, 1e15):
            with self.subTest(historical_draws=historical_draws):
                fin = terms(opening_cumulative_drawn=historical_draws, facility_limit=1e15)
                with self.assertRaisesRegex(ValueError, "actual principal"):
                    cashflow_ledger([cash_row("2022-01", principal=5e-9)], fin, actuals=True)

    def test_decimal_payoff_preserves_actual_payments_and_zero_debt(self):
        fin = terms(opening_cash=3.3, opening_debt=3.3, opening_cumulative_drawn=3.3,
                    facility_limit=3.3, annual_interest_rate=0.0)
        rows = [cash_row("2022-01", principal=2.2, debt_draw=0.0, interest=0.0),
                cash_row("2022-02", principal=1.1, debt_draw=0.0, interest=0.0)]
        ledger = cashflow_ledger(rows, fin, actuals=True)
        self.assertEqual([r["principal"] for r in ledger], [2.2, 1.1])
        self.assertEqual(ledger[-1]["closing_debt"], 0.0)
        self.assertEqual(ledger[-1]["closing_cash"], 3.3 - 2.2 - 1.1)

    def test_final_decimal_payment_can_resume_from_closing_state(self):
        fin = terms(opening_cash=60.0, opening_debt=60.0, opening_cumulative_drawn=60.0,
                    facility_limit=60.0, annual_interest_rate=0.0)
        rows = [cash_row(add_months("2022-01", i), principal=0.1, debt_draw=0.0, interest=0.0)
                for i in range(600)]
        prefix = cashflow_ledger(rows[:-1], fin, actuals=True)
        resumed = cashflow_ledger(rows[-1:], fin, closing_state(prefix, fin), actuals=True)
        complete = cashflow_ledger(rows, fin, actuals=True)
        self.assertEqual(resumed[-1], complete[-1])
        self.assertEqual(resumed[-1]["principal"], 0.1)
        self.assertEqual(resumed[-1]["closing_debt"], 0.0)

    def test_large_historical_draws_cannot_excuse_material_overpayment(self):
        fin = terms(opening_debt=1e-12, opening_cumulative_drawn=1e15, facility_limit=1e15)
        with self.assertRaisesRegex(ValueError, "actual principal"):
            cashflow_ledger([cash_row("2022-01", principal=2e-12)], fin, actuals=True)

    def test_positive_recorded_draw_requires_headroom_and_availability(self):
        for fin in (terms(facility_limit=0.0),
                    terms(opening_cumulative_drawn=100.0),
                    terms(availability_end="2021-12")):
            with self.subTest(financing=fin):
                with self.assertRaisesRegex(ValueError, "facility"):
                    cashflow_ledger([cash_row("2022-01", debt_draw=5e-9, interest=0.0)], fin)

    def test_decimal_draws_keep_recorded_amounts_and_exhaust_headroom(self):
        fin = terms(facility_limit=0.3, annual_interest_rate=0.0)
        rows = [cash_row("2022-01", debt_draw=0.1, interest=0.0),
                cash_row("2022-02", debt_draw=0.2, interest=0.0)]
        ledger = cashflow_ledger(rows, fin, actuals=True)
        self.assertEqual([r["debt_draw"] for r in ledger], [0.1, 0.2])
        self.assertEqual(ledger[-1]["cumulative_drawn"], 0.1 + 0.2)
        self.assertEqual(ledger[-1]["unused_facility"], 0.0)
        with self.assertRaisesRegex(ValueError, "facility"):
            cashflow_ledger([cash_row("2022-03", debt_draw=5e-9, interest=0.0)],
                            fin, closing_state(ledger, fin), actuals=True)

    def test_zero_initial_draws_and_limit_are_strict(self):
        for fin, state in (
                (terms(), {"cash": 0.0, "debt": 5e-10, "cumulative_drawn": 0.0}),
                (terms(facility_limit=0.0), {"cash": 0.0, "debt": 0.0, "cumulative_drawn": 5e-10})):
            with self.subTest(state=state):
                with self.assertRaisesRegex(ValueError, "opening state"):
                    cashflow_ledger([cash_row("2022-01")], fin, state)

    def test_rowwise_cash_and_debt_conservation(self):
        rows = [cash_row("2022-01", capex=80, equity=10), cash_row("2022-02", receipts=50, opex=10, tax=2, maintenance_capex=1, principal=15)]
        ledger = cashflow_ledger(rows, terms())
        for r in ledger:
            cash = r["opening_cash"] + r["receipts"] + r["equity"] + r["debt_draw"] - r["capex"] - r["opex"] - r["tax"] - r["maintenance_capex"] - r["interest"] - r["principal"]
            debt = r["opening_debt"] + r["debt_draw"] - r["principal"]
            self.assertAlmostEqual(cash, r["closing_cash"], places=10)
            self.assertAlmostEqual(debt, r["closing_debt"], places=10)

    def test_nonfinite_cash_input_rejected(self):
        with self.assertRaises(ValueError):
            cashflow_ledger([cash_row("2022-01", capex=math.inf)], terms())

    def test_actual_principal_is_preserved_without_recorded_financing(self):
        fin = terms(opening_cash=100, opening_debt=40, opening_cumulative_drawn=40)
        with self.assertRaisesRegex(ValueError, "actual principal"):
            cashflow_ledger([cash_row("2022-01", principal=50)], fin, actuals=True)
        got = cashflow_ledger([cash_row("2022-01", principal=25)], fin, actuals=True)[0]
        self.assertEqual(got["principal"], 25.0)
        self.assertAlmostEqual(got["closing_cash"], 74.6)
        self.assertEqual(got["closing_debt"], 15.0)

    def test_missing_amount_is_not_assumed_zero(self):
        row = cash_row("2022-01")
        del row["capex"]
        with self.assertRaisesRegex(ValueError, "Missing cash flow"):
            cashflow_ledger([row], terms())

    def test_boolean_is_not_a_cash_amount_or_financing_term(self):
        with self.assertRaises(ValueError):
            cashflow_ledger([cash_row("2022-01", receipts=True)], terms())
        with self.assertRaises(ValueError):
            cashflow_ledger([cash_row("2022-01")], terms(annual_interest_rate=True))
        with self.assertRaises(ValueError):
            cashflow_ledger([cash_row("2022-01", debt_draw=True, interest=0)], terms())

    def test_empty_explicit_state_cannot_reset_to_original_balances(self):
        with self.assertRaisesRegex(ValueError, "initial_state"):
            cashflow_ledger([cash_row("2022-01")], terms(opening_cash=99), {})

    def test_finite_inputs_that_overflow_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "overflow"):
            cashflow_ledger([cash_row("2022-01", receipts=1e308, equity=1e308)], terms())

    def test_cash_shortfall_carries_forward_without_a_hidden_injection(self):
        rows = [cash_row("2022-01", capex=150), cash_row("2022-02", receipts=20)]
        ledger = cashflow_ledger(rows, terms())
        self.assertEqual(ledger[0]["closing_cash"], -50.0)
        self.assertEqual(ledger[1]["opening_cash"], -50.0)
        self.assertEqual(ledger[1]["closing_cash"], -31.0)
        self.assertEqual(ledger[1]["debt_draw"], 0.0)
        self.assertEqual(ledger[1]["equity"], 0.0)

    def test_resumed_state_preserves_existing_cash_deficit_and_used_limit(self):
        state = {"cash": -50.0, "debt": 100.0, "cumulative_drawn": 100.0}
        got = cashflow_ledger([cash_row("2022-02", receipts=20)], terms(), state)[0]
        self.assertEqual(got["closing_cash"], -31.0)
        self.assertEqual(got["unused_facility"], 0.0)

    def test_month_gap_cannot_omit_an_interest_period(self):
        with self.assertRaisesRegex(ValueError, "consecutive"):
            cashflow_ledger([cash_row("2022-01"), cash_row("2022-03")], terms())


if __name__ == "__main__":
    unittest.main()
