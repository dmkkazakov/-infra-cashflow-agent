"""Strict data contract for monthly, cash-basis infrastructure forecasts.

Amounts are expressed in millions of the declared currency. A baseline is a
frozen cash schedule, not an income statement. Tax amounts are supplied cash
payments; this package does not infer jurisdiction-specific taxes.
"""
from __future__ import annotations

import copy
import csv
import json
import math
import re
import random
from pathlib import Path
from typing import Any

FLOW_COMPONENTS = ("receipts", "capex", "opex", "tax", "maintenance_capex")
CONTRACT_COMPONENTS = ("equity", "principal")
AMOUNT_FIELDS = FLOW_COMPONENTS + CONTRACT_COMPONENTS
MONTH_RE = re.compile(r"^([0-9]{4})-(0[1-9]|1[0-2])$")


def month_number(month: str) -> int:
    """Convert YYYY-MM to a sortable month number, with strict validation."""
    if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
        raise ValueError(f"Expected a month in YYYY-MM format, got {month!r}")
    year, mon = map(int, month.split("-"))
    if not 1900 <= year <= 2200:
        raise ValueError(f"Month outside supported 1900-2200 range: {month}")
    return year * 12 + mon - 1


def add_months(month: str, offset: int) -> str:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("Month offset must be an integer")
    n = month_number(month) + offset
    result = f"{n // 12:04d}-{n % 12 + 1:02d}"
    month_number(result)
    return result


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        n = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(n) or n < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return n


def _exceeds_balance(amount: float, balance: float, scale: float) -> bool:
    """Compare positive balances without treating zero as available funding."""
    if amount <= balance:
        return False
    if balance == 0.0:
        return True
    # Up to 600 monthly rows can accumulate rounding in debt/draw balances.
    # Four ULP per row, measured at the historical financing scale, cover
    # that arithmetic and can be reconstructed from a resumed closing_state.
    # The relative cap prevents large historic draws from excusing a material
    # overpayment of a small remaining balance. No fixed currency allowance.
    tolerance = min(4 * 600 * math.ulp(scale), 1e-9 * max(amount, balance))
    return amount - balance > tolerance


def _validate_rows(rows: Any, name: str, *, baseline: bool) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{name} must be a nonempty list of monthly rows")
    if len(rows) > 600:
        raise ValueError(f"{name} exceeds 600-month input limit")
    previous = None
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{name}[{i}] must be an object")
        unknown = set(row) - {"month", *AMOUNT_FIELDS, "debt_draw", "interest"}
        if unknown:
            raise ValueError(f"{name}[{i}] has unsupported fields {sorted(unknown)}; cash information cannot be silently ignored")
        n = month_number(row.get("month"))
        if previous is not None and n != previous + 1:
            raise ValueError(f"{name} months must be unique, sorted and consecutive")
        previous = n
        for field in AMOUNT_FIELDS:
            if field not in row:
                raise ValueError(f"{name}[{i}] missing cash field {field}")
            _number(row[field], f"{name}[{i}].{field}")
        for field in ("debt_draw", "interest"):
            if field in row:
                if baseline:
                    raise ValueError(f"{name} cannot freeze endogenous {field}; use financing rules")
                _number(row[field], f"{name}[{i}].{field}")
        if not baseline and (("debt_draw" in row) != ("interest" in row)):
            raise ValueError(f"{name}[{i}] must provide both recorded debt_draw and interest, or neither")


def validate_project(project: dict) -> dict:
    """Validate the data contract and observed financing consistency.

    Future actual rows can be present in a *synthetic evaluation fixture*. The
    forecasting code selects its as-of prefix before any fitting or replay.
    """
    if not isinstance(project, dict):
        raise ValueError("Project must be a JSON object")
    if project.get("schema_version") != "1.0":
        raise ValueError("schema_version must be '1.0'")
    if not isinstance(project.get("project_id"), str) or not project["project_id"].strip():
        raise ValueError("A nonempty project_id is required")
    if not isinstance(project.get("synthetic_data"), bool):
        raise ValueError("synthetic_data must explicitly be true or false")
    if project.get("amount_unit") != "million":
        raise ValueError("amount_unit must be 'million'; convert inputs explicitly")
    if not isinstance(project.get("currency"), str) or not re.fullmatch(r"[A-Z]{3}", project["currency"]):
        raise ValueError("currency must be a three-letter uppercase code")
    as_of = month_number(project.get("as_of"))
    vintage = month_number(project.get("baseline_vintage"))
    _validate_rows(project.get("baseline"), "baseline", baseline=True)
    _validate_rows(project.get("actuals"), "actuals", baseline=False)
    baseline = project["baseline"]
    actuals = project["actuals"]
    if actuals[0]["month"] != baseline[0]["month"]:
        raise ValueError("Actual history must start at the baseline's first month")
    if month_number(actuals[-1]["month"]) > month_number(baseline[-1]["month"]):
        raise ValueError("Actual history extends beyond the baseline horizon")
    if vintage > month_number(baseline[0]["month"]):
        raise ValueError("baseline_vintage must be no later than the baseline's first month")
    if "operations_start" in project:
        operations_start = month_number(project["operations_start"])
        if not month_number(baseline[0]["month"]) <= operations_start <= month_number(baseline[-1]["month"]):
            raise ValueError("operations_start must be within the supplied baseline horizon")
    if not (month_number(actuals[0]["month"]) <= as_of <= month_number(actuals[-1]["month"])):
        raise ValueError("as_of must be a completed month present in actuals")
    fin = project.get("financing")
    if not isinstance(fin, dict):
        raise ValueError("financing must be an object")
    for field in ("opening_cash", "opening_debt", "opening_cumulative_drawn", "facility_limit", "minimum_cash"):
        _number(fin.get(field), f"financing.{field}")
    rate = _number(fin.get("annual_interest_rate"), "financing.annual_interest_rate")
    if rate > 1.0:
        raise ValueError("annual_interest_rate must be a fraction in [0,1], not a percentage")
    month_number(fin.get("availability_end"))
    debt = float(fin["opening_debt"])
    drawn = float(fin["opening_cumulative_drawn"])
    limit = float(fin["facility_limit"])
    if _exceeds_balance(debt, drawn, drawn):
        raise ValueError("Opening debt cannot exceed cumulative historical draws")
    if _exceeds_balance(drawn, limit, limit):
        raise ValueError("Opening cumulative draws exceed the nonrevolving facility limit")
    observed = [r for r in actuals if month_number(r["month"]) <= as_of]
    # Validate only the observed financing prefix; withheld future outcomes
    # must not determine whether a current financial state is accepted. This
    # preserves actual principal even when debt draw/interest are reconstructed.
    from .engine import cashflow_ledger
    cashflow_ledger(observed, fin, actuals=True)
    recorded = all("debt_draw" in r for r in observed)
    warnings = []
    if not recorded:
        warnings.append("Historical financing is reconstructed under the supplied facility rules where recorded debt_draw/interest are absent.")
    if len(observed) < 12:
        warnings.append("Fewer than 12 observed months; correction estimates have limited evidence.")
    if len(actuals) > len(observed):
        warnings.append("Fixture contains withheld future actuals; forecasts must use only the as-of prefix.")
    return {
        "valid": True,
        "project_id": project["project_id"],
        "currency": project["currency"],
        "amount_unit": "million",
        "synthetic_data": project["synthetic_data"],
        "baseline_months": len(baseline),
        "observed_months": len(observed),
        "withheld_actual_months": len(actuals) - len(observed),
        "warnings": warnings,
    }


def load_project(path: str | Path, *, as_of: str | None = None) -> dict:
    """Read strict JSON and validate against the effective requested cutoff.

    A caller may override the fixture's default date without letting later
    financing observations decide whether that earlier forecast is accepted.
    """
    def invalid_constant(value: str) -> None:
        raise ValueError(f"Nonfinite JSON constant {value} is not allowed")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key {key!r}; values cannot be silently overwritten")
            result[key] = value
        return result

    with Path(path).open("r", encoding="utf-8") as f:
        project = json.load(f, parse_constant=invalid_constant, object_pairs_hook=unique_object)
    if as_of is not None:
        if not isinstance(project, dict):
            raise ValueError("Project must be a JSON object")
        month_number(as_of)
        project["as_of"] = as_of
    validate_project(project)
    return project


def observed_project(project: dict, as_of: str | None = None) -> dict:
    """Return a defensive copy with all outcomes after the cutoff removed."""
    cutoff = project["as_of"] if as_of is None else as_of
    n = month_number(cutoff)
    p = copy.deepcopy(project)
    p["as_of"] = cutoff
    p["actuals"] = [r for r in p["actuals"] if month_number(r["month"]) <= n]
    validate_project(p)
    return p


def rows_from_csv(path: str | Path) -> list[dict]:
    """Load explicitly named monthly cash fields; no date/locale guessing."""
    rows = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)):
            raise ValueError("CSV must have unique named columns; duplicate columns cannot overwrite amounts")
        required = {"month", *AMOUNT_FIELDS}
        allowed = required | {"debt_draw", "interest"}
        if required - set(headers):
            raise ValueError(f"CSV is missing required columns: {sorted(required - set(headers))}")
        if set(headers) - allowed:
            raise ValueError(f"CSV has unsupported columns: {sorted(set(headers) - allowed)}")
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV row {row_number} does not match its declared columns")
            out = {"month": row["month"]}
            for k in AMOUNT_FIELDS + ("debt_draw", "interest"):
                if k in row and row[k] not in (None, ""):
                    try:
                        out[k] = float(row[k])
                    except ValueError as exc:
                        raise ValueError(f"CSV row {row_number}, column {k} must contain a number") from exc
            rows.append(out)
    _validate_rows(rows, "CSV", baseline=not bool({"debt_draw", "interest"} & set(headers)))
    return rows


def make_demo_project(seed: int = 7, as_of: str = "2023-12") -> dict:
    """Generate a fully disclosed synthetic project and withheld test outcomes.

    Three predeclared regimes are selected by seed modulo three: unbiased,
    persistent bias and an operating-regime reversal. They are demonstration
    designs, not fitted representations of any real infrastructure asset.
    The package defaults to seed seven (persistent bias). Baseline capex is
    exactly 6,000 million RUB over 30 months; no real client data are present.
    """
    from .engine import cashflow_ledger

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Synthetic data seed must be a nonnegative integer")
    rng = random.Random(seed)
    start = "2022-01"
    construction_months, total_months = 30, 84
    weights = [0.30 + math.sin(math.pi * (i + 0.5) / construction_months) ** 2 for i in range(construction_months)]
    total_weight = sum(weights)
    baseline = []
    for i in range(total_months):
        operating_age = i - construction_months
        capex = 6000.0 * weights[i] / total_weight if i < construction_months else 0.0
        if operating_age >= 0:
            escalation = 1.02 ** (operating_age / 12.0)
            seasonal = 1.0 + 0.06 * math.sin(2.0 * math.pi * operating_age / 12.0)
            ramp = min(1.0, 0.75 + operating_age * 0.05)
            receipts = 260.0 * escalation * seasonal * ramp
            opex = (60.0 + 0.06 * receipts) * escalation
            maintenance = 5.0 * escalation
            tax = max(receipts - opex - maintenance, 0.0) * 0.12
        else:
            receipts, opex, maintenance, tax = 0.0, 3.0, 0.0, 0.0
        baseline.append({
            "month": add_months(start, i), "receipts": receipts, "capex": capex,
            "opex": opex, "tax": tax, "maintenance_capex": maintenance,
            "equity": 2000.0 if i == 0 else 0.0,
            "principal": 110.0 if i >= 36 else 0.0,
        })
    regime = seed % 3
    regime_names = {0: "unbiased_noisy_plan", 1: "persistent_component_bias", 2: "operating_regime_reversal"}
    if regime == 0:
        biases = {c: 1.0 for c in FLOW_COMPONENTS}
    else:
        biases = {
            "receipts": rng.uniform(0.89, 0.95), "capex": rng.uniform(1.08, 1.15),
            "opex": rng.uniform(1.04, 1.09), "tax": rng.uniform(0.96, 1.02),
            "maintenance_capex": rng.uniform(1.02, 1.08),
        }
    volatility = {"receipts": 0.045, "capex": 0.045, "opex": 0.025, "tax": 0.035, "maintenance_capex": 0.035}
    previous_shocks = {c: 0.0 for c in FLOW_COMPONENTS}
    actual_flows = []
    for i, plan in enumerate(baseline):
        row = {"month": plan["month"], "equity": plan["equity"], "principal": plan["principal"]}
        common = rng.gauss(0.0, 1.0)
        for c in FLOW_COMPONENTS:
            innovation = math.sqrt(0.25) * common + math.sqrt(0.75) * rng.gauss(0.0, 1.0)
            z = 0.45 * previous_shocks[c] + math.sqrt(1.0 - 0.45 ** 2) * innovation
            previous_shocks[c] = z
            bias = biases[c]
            if regime == 2 and i >= 60 and c in ("receipts", "opex", "tax", "maintenance_capex"):
                bias = 1.07 if c == "receipts" else 1.0
            sigma = volatility[c]
            row[c] = plan[c] * bias * math.exp(sigma * z - 0.5 * sigma ** 2)
        actual_flows.append(row)
    financing = {
        "opening_cash": 100.0, "opening_debt": 0.0, "opening_cumulative_drawn": 0.0,
        "facility_limit": 4700.0, "annual_interest_rate": 0.12,
        "minimum_cash": 75.0, "availability_end": "2024-12",
    }
    actual_ledger = cashflow_ledger(actual_flows, financing)
    for row, ledger in zip(actual_flows, actual_ledger):
        row["debt_draw"] = ledger["debt_draw"]
        row["interest"] = ledger["interest"]
        row["principal"] = ledger["principal"]
    project = {
        "schema_version": "1.0", "project_id": f"synthetic-infrastructure-{seed:03d}",
        "description": "Synthetic cash-basis infrastructure SPV: 30 construction months and 54 operating months. No real project or client data.",
        "synthetic_data": True, "currency": "RUB", "amount_unit": "million",
        "baseline_vintage": "2021-12", "operations_start": "2024-07", "as_of": as_of,
        "financing": financing, "baseline": baseline, "actuals": actual_flows,
        "synthetic_design": {
            "seed": seed, "regime": regime_names[regime], "months": total_months,
            "construction_months": construction_months, "construction_capex": 6000.0,
            "outcomes_after_as_of": "Withheld synthetic outcomes for rolling-origin evaluation only; never available to a forecast.",
            "data_generation": "Component lognormal noise, AR(1)=0.45, common innovation variance share=0.25; fixed seed and predeclared component bias regime.",
            "regime_reversal_month": "2027-01" if regime == 2 else None,
            "source": "Programmatically generated demonstration, not calibrated from real infrastructure projects.",
        },
    }
    validate_project(project)
    return project
