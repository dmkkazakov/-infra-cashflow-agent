"""Cash-basis ledger with an explicit, nonrevolving debt facility.

No cash shortfall is repaired by imaginary equity. Negative projected cash is
an unmet funding requirement, not permission for an actual account overdraft.
Interest uses opening debt and a nominal annual rate divided by twelve.
"""
from __future__ import annotations

import math
from typing import Iterable

from .data import AMOUNT_FIELDS, _number, month_number


def initial_state(financing: dict) -> dict:
    return {
        "cash": float(financing["opening_cash"]),
        "debt": float(financing["opening_debt"]),
        "cumulative_drawn": float(financing["opening_cumulative_drawn"]),
    }


def closing_state(ledger: list[dict], financing: dict) -> dict:
    if not ledger:
        return initial_state(financing)
    last = ledger[-1]
    return {"cash": last["closing_cash"], "debt": last["closing_debt"], "cumulative_drawn": last["cumulative_drawn"]}


def cashflow_ledger(rows: Iterable[dict], financing: dict, initial_state: dict | None = None, *, actuals: bool = False) -> list[dict]:
    """Replay actual rows or forecast rows under one transparent cash waterfall.

    Optional recorded ``debt_draw`` and ``interest`` values are honored for
    actual rows. Pass ``actuals=True`` when replaying actual cash payments,
    including when historical financing must be reconstructed. Future rows
    omit both recorded financing fields and use ``actuals=False``. Forecast
    principal is the contractual amount capped by opening debt; an actual
    principal payment above opening debt is rejected rather than silently
    changed. Lack of cash does not reduce scheduled service.
    The facility is nonrevolving: principal repayments do not replenish it.
    Debt can be drawn only through availability_end. Draws at month end start
    accruing interest next month. The model has no fees, reserve accounts,
    capitalized interest, refinancing, shareholder distributions or tax rules.
    """
    if not isinstance(actuals, bool):
        raise ValueError("actuals must be an explicit boolean")
    if not isinstance(financing, dict):
        raise ValueError("financing must be an object")
    fin_fields = ("opening_cash", "opening_debt", "opening_cumulative_drawn", "facility_limit", "minimum_cash", "annual_interest_rate", "availability_end")
    missing_fin = set(fin_fields) - set(financing)
    if missing_fin:
        raise ValueError(f"Missing financing fields: {sorted(missing_fin)}")
    state = initial_state if initial_state is not None else {
        "cash": financing["opening_cash"],
        "debt": financing["opening_debt"],
        "cumulative_drawn": financing["opening_cumulative_drawn"],
    }
    if not isinstance(state, dict) or set(("cash", "debt", "cumulative_drawn")) - set(state):
        raise ValueError("initial_state must contain cash, debt and cumulative_drawn; an empty state is not an opening balance")
    cash = _number(state["cash"], "state.cash", minimum=-math.inf)
    debt = _number(state["debt"], "state.debt")
    drawn = _number(state["cumulative_drawn"], "state.cumulative_drawn")
    limit = _number(financing["facility_limit"], "financing.facility_limit")
    floor = _number(financing["minimum_cash"], "financing.minimum_cash")
    rate = _number(financing["annual_interest_rate"], "financing.annual_interest_rate")
    available_through = month_number(financing["availability_end"])
    if not all(math.isfinite(x) for x in (cash, debt, drawn, limit, floor, rate)):
        raise ValueError("Ledger state/financing must be finite")
    if debt < 0 or drawn < debt - 1e-8 or drawn > limit + 1e-8 or floor < 0 or not 0 <= rate <= 1:
        raise ValueError("Invalid ledger opening state or financing terms")
    result = []
    prior_month = None
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Every ledger row must be an object")
        current_month = month_number(raw.get("month"))
        if prior_month is not None and current_month != prior_month + 1:
            raise ValueError("Ledger rows must be consecutive and ordered")
        prior_month = current_month
        missing_flow = set(AMOUNT_FIELDS) - set(raw)
        if missing_flow:
            raise ValueError(f"Missing cash flow fields: {sorted(missing_flow)}; missing amounts cannot be assumed zero")
        flow = {k: _number(raw[k], f"{raw['month']}.{k}") for k in AMOUNT_FIELDS}
        cash_open, debt_open = cash, debt
        recorded = "debt_draw" in raw or "interest" in raw
        if recorded and (("debt_draw" in raw) != ("interest" in raw)):
            raise ValueError("Recorded financing must provide both debt_draw and interest")
        actual_payment = actuals or recorded
        if actual_payment and flow["principal"] > debt_open + 1e-8:
            raise ValueError("Recorded actual principal payment exceeds opening debt; actual cash payments cannot be silently capped")
        interest = _number(raw["interest"], f"{raw['month']}.interest") if recorded else debt_open * rate / 12.0
        principal = flow["principal"] if actual_payment else min(flow["principal"], debt_open)
        if not math.isfinite(interest) or interest < 0:
            raise ValueError("Interest must be finite and nonnegative")
        cfads = flow["receipts"] - flow["opex"] - flow["tax"] - flow["maintenance_capex"]
        fcf = cfads - flow["capex"]
        cash_before_draw = cash_open + fcf + flow["equity"] - interest - principal
        if not all(math.isfinite(x) for x in (cfads, fcf, cash_before_draw)):
            raise ValueError("Cash flow arithmetic overflow; rescale amounts or correct the inputs")
        headroom = max(limit - drawn, 0.0)
        if "debt_draw" in raw:
            debt_draw = _number(raw["debt_draw"], f"{raw['month']}.debt_draw")
            if not math.isfinite(debt_draw) or debt_draw < 0 or debt_draw > headroom + 1e-8:
                raise ValueError("Recorded debt draw exceeds available nonrevolving facility")
            if current_month > available_through and debt_draw > 1e-8:
                raise ValueError("Recorded debt draw occurs after facility availability ends")
        else:
            debt_draw = min(max(floor - cash_before_draw, 0.0), headroom) if current_month <= available_through else 0.0
        cash = cash_before_draw + debt_draw
        debt = debt_open + debt_draw - principal
        drawn += debt_draw
        service = interest + principal
        ledger_row = {
            "month": raw["month"],
            "opening_cash": cash_open,
            "opening_debt": debt_open,
            **{k: flow[k] for k in AMOUNT_FIELDS if k != "principal"},
            "scheduled_principal": flow["principal"],
            "principal": principal,
            "cfads": cfads,
            "free_cash_flow": fcf,
            "interest": interest,
            "debt_draw": debt_draw,
            "debt_service": service,
            "closing_debt": debt,
            "cumulative_drawn": drawn,
            "unused_facility": max(limit - drawn, 0.0),
            "closing_cash": cash,
            "funding_gap": max(floor - cash, 0.0),
            "dscr": cfads / service if service > 1e-12 else None,
        }
        if not all(math.isfinite(value) for value in ledger_row.values() if isinstance(value, (int, float))):
            raise ValueError("Ledger arithmetic produced a nonfinite value; rescale amounts or correct the inputs")
        result.append(ledger_row)
    return result
