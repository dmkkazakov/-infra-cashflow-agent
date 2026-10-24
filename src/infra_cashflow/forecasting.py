"""Past-only statistical cash forecasts and conditional Monte Carlo scenarios.

This is an explicit statistical model, not a claim that a language model can
predict finance. Intervals describe the supplied model and assumptions; they
are not calibrated probabilities of a real project's outcomes.
"""
from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from .data import AMOUNT_FIELDS, FLOW_COMPONENTS, add_months, month_number, observed_project, validate_project
from .engine import cashflow_ledger, closing_state

LOOKBACK_ACTIVE = 12
WEIGHT_DECAY = 0.85
PRIOR_STRENGTH = 3.0
AR_COEFFICIENT = 0.65
COMMON_VARIANCE_SHARE = 0.35
NOISE_FLOORS = {"receipts": 0.05, "capex": 0.06, "opex": 0.04, "tax": 0.05, "maintenance_capex": 0.05}
UNOBSERVED_NOISE = {"receipts": 0.12, "capex": 0.10, "opex": 0.08, "tax": 0.10, "maintenance_capex": 0.10}


def fit_corrections(project: dict) -> dict:
    """Fit recency-weighted actual/plan multipliers from the supplied prefix.

    Calendar periods with zero baseline in a component provide no multiplicative
    information and are excluded. Ratios above five are winsorized explicitly
    to prevent one tiny denominator from dominating; counts are disclosed.
    """
    cutoff = month_number(project["as_of"])
    plan = {r["month"]: r for r in project["baseline"]}
    observed = [r for r in project["actuals"] if month_number(r["month"]) <= cutoff]
    components = {}
    for c in FLOW_COMPONENTS:
        pairs = [(r["month"], float(r[c]) / float(plan[r["month"]][c]))
                 for r in observed if float(plan[r["month"]][c]) > 1e-9]
        pairs = pairs[-LOOKBACK_ACTIVE:]
        n = len(pairs)
        if n:
            raw = np.array([x[1] for x in pairs], dtype=float)
            ratios = np.clip(raw, 0.0, 5.0)
            weights = WEIGHT_DECAY ** np.arange(n - 1, -1, -1, dtype=float)
            weights = weights / weights.sum() * n
            weighted_mean = float(np.dot(weights, ratios) / weights.sum())
            multiplier = float((np.dot(weights, ratios) + PRIOR_STRENGTH) / (n + PRIOR_STRENGTH))
            residual_sd = math.sqrt(float(np.dot(weights, (ratios - weighted_mean) ** 2) / weights.sum()))
            relative_sd = min(0.60, max(NOISE_FLOORS[c], residual_sd / max(multiplier, 0.1)))
            parameter_sd = relative_sd / math.sqrt(n + PRIOR_STRENGTH)
            clipped = int(np.count_nonzero(raw > 5.0))
        else:
            multiplier = 1.0
            relative_sd = UNOBSERVED_NOISE[c]
            parameter_sd = relative_sd
            clipped = 0
        components[c] = {
            "multiplier": multiplier,
            "active_observations": n,
            "last_active_month": pairs[-1][0] if pairs else None,
            "conditional_log_noise_sd": relative_sd,
            "parameter_log_noise_sd": parameter_sd,
            "winsorized_observations": clipped,
            "basis": "past_actual_to_plan_ratios" if n else "unobserved_component_prior",
        }
    return {
        "name": "ewma_plan_ratio_v1",
        "trained_through": project["as_of"],
        "lookback_active_months": LOOKBACK_ACTIVE,
        "weight_decay": WEIGHT_DECAY,
        "prior_strength": PRIOR_STRENGTH,
        "components": components,
    }


def _scenario(scenario: dict | None) -> dict:
    defaults = {
        "name": "base",
        "delay_months": 0,
        "receipts_multiplier": 1.0,
        "capex_multiplier": 1.0,
        "opex_multiplier": 1.0,
        "annual_rate_shift": 0.0,
    }
    if scenario is not None:
        if not isinstance(scenario, dict):
            raise ValueError("scenario must be an object")
        unknown = set(scenario) - set(defaults)
        if unknown:
            raise ValueError(f"Unsupported scenario fields: {sorted(unknown)}")
        defaults.update(scenario)
    if not isinstance(defaults["name"], str):
        raise ValueError("scenario.name must be a string")
    delay = defaults["delay_months"]
    if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 60:
        raise ValueError("delay_months must be an integer in [0,60]")
    for key in ("receipts_multiplier", "capex_multiplier", "opex_multiplier"):
        val = defaults[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not 0 <= val <= 5:
            raise ValueError(f"{key} must be finite in [0,5]")
    val = defaults["annual_rate_shift"]
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not -1 <= val <= 1:
        raise ValueError("annual_rate_shift must be finite in [-1,1]")
    return defaults


def _future_rows(project: dict, model: dict, horizon: int, scenario: dict) -> tuple[list[dict], dict]:
    """Shift remaining unobserved cash schedules, keeping contracts fixed.

    ``delay_months`` is a suspension of remaining physical/operating schedules.
    It shifts receipts and operating cash as well as construction spending.
    It is a commissioning delay only when the project is still constructing.
    Equity commitments and principal dates never move automatically.
    """
    plan = {r["month"]: r for r in project["baseline"]}
    cutoff = project["as_of"]
    cutoff_n = month_number(cutoff)
    delay = scenario["delay_months"]
    multipliers = {
        "receipts": scenario["receipts_multiplier"],
        "capex": scenario["capex_multiplier"],
        "opex": scenario["opex_multiplier"],
        # Cash taxes are a separately provided schedule; they are shifted but
        # not inferred from a jurisdiction-specific tax rate.
        "tax": 1.0,
        "maintenance_capex": scenario["capex_multiplier"],
    }
    zero = {k: 0.0 for k in AMOUNT_FIELDS}
    future = []
    for i in range(1, horizon + 1):
        month = add_months(cutoff, i)
        source_month = add_months(month, -delay)
        source = plan.get(source_month, zero) if month_number(source_month) > cutoff_n else zero
        contract = plan.get(month, zero)
        row = {"month": month}
        for c in FLOW_COMPONENTS:
            row[c] = float(source[c]) * model["components"][c]["multiplier"] * multipliers[c]
        row["equity"] = float(contract["equity"])
        row["principal"] = float(contract["principal"])
        future.append(row)
    end = month_number(future[-1]["month"])
    deferred = {c: 0.0 for c in FLOW_COMPONENTS}
    for month, r in plan.items():
        n = month_number(month)
        if n > cutoff_n and n + delay > end:
            for c in FLOW_COMPONENTS:
                deferred[c] += float(r[c]) * model["components"][c]["multiplier"] * multipliers[c]
    return future, deferred


def _cash_path_simulation(point_rows: list[dict], financing: dict, state: dict, model: dict,
                          n_simulations: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized cash waterfall using common random numbers across scenarios."""
    rng = np.random.default_rng(seed)
    t_count, c_count = len(point_rows), len(FLOW_COMPONENTS)
    common = rng.normal(size=(n_simulations, t_count, 1))
    individual = rng.normal(size=(n_simulations, t_count, c_count))
    innovations = math.sqrt(COMMON_VARIANCE_SHARE) * common + math.sqrt(1.0 - COMMON_VARIANCE_SHARE) * individual
    shocks = np.empty_like(innovations)
    shocks[:, 0, :] = innovations[:, 0, :]
    for t in range(1, t_count):
        shocks[:, t, :] = AR_COEFFICIENT * shocks[:, t - 1, :] + math.sqrt(1.0 - AR_COEFFICIENT ** 2) * innovations[:, t, :]
    persistent_common = rng.normal(size=(n_simulations, 1))
    persistent_individual = rng.normal(size=(n_simulations, c_count))
    persistent = math.sqrt(COMMON_VARIANCE_SHARE) * persistent_common + math.sqrt(1.0 - COMMON_VARIANCE_SHARE) * persistent_individual
    sigma = np.array([model["components"][c]["conditional_log_noise_sd"] for c in FLOW_COMPONENTS])
    param_sigma = np.array([model["components"][c]["parameter_log_noise_sd"] for c in FLOW_COMPONENTS])
    factors = np.exp(shocks * sigma + persistent[:, None, :] * param_sigma - 0.5 * (sigma ** 2 + param_sigma ** 2))
    point = np.array([[r[c] for c in FLOW_COMPONENTS] for r in point_rows])
    flows = factors * point[None, :, :]
    cash = np.full(n_simulations, state["cash"], dtype=float)
    debt = np.full(n_simulations, state["debt"], dtype=float)
    drawn = np.full(n_simulations, state["cumulative_drawn"], dtype=float)
    cash_paths = np.empty((n_simulations, t_count), dtype=float)
    fcf_paths = np.empty_like(cash_paths)
    dscr_paths = np.full_like(cash_paths, np.nan)
    rate = financing["annual_interest_rate"] / 12.0
    limit = financing["facility_limit"]
    floor = financing["minimum_cash"]
    avail = month_number(financing["availability_end"])
    for t, row in enumerate(point_rows):
        receipts, capex, opex, tax, maintenance = [flows[:, t, i] for i in range(c_count)]
        cfads = receipts - opex - tax - maintenance
        fcf = cfads - capex
        interest = debt * rate
        principal = np.minimum(row["principal"], debt)
        service = interest + principal
        cash = cash + fcf + row["equity"] - service
        if month_number(row["month"]) <= avail:
            draw = np.minimum(np.maximum(floor - cash, 0.0), np.maximum(limit - drawn, 0.0))
        else:
            draw = np.zeros(n_simulations)
        cash = cash + draw
        debt = debt + draw - principal
        drawn += draw
        cash_paths[:, t] = cash
        fcf_paths[:, t] = fcf
        np.divide(cfads, service, out=dscr_paths[:, t], where=service > 1e-12)
    return cash_paths, fcf_paths, dscr_paths


def run_forecast(project: dict, as_of: str | None = None, horizon: int | None = None,
                 n_simulations: int = 1000, seed: int = 42, scenario: dict | None = None) -> dict:
    """Run a forecast, never training on actual outcomes after ``as_of``.

    P10/P50/P90 are lower/median/upper percentiles, not exceedance probabilities.
    Quantiles of different months are not one economically coherent cash path.
    """
    # The requested cutoff controls validation of historical financing too;
    # otherwise an original later default cutoff could replay future data.
    validation_at_cutoff = {**project, "as_of": as_of or project.get("as_of")}
    validation = validate_project(validation_at_cutoff)
    p = observed_project(project, as_of)
    s = _scenario(scenario)
    if horizon is None:
        horizon = month_number(p["baseline"][-1]["month"]) - month_number(p["as_of"])
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 240:
        raise ValueError("Forecast horizon must be an integer in [1,240]")
    remaining_plan_months = month_number(p["baseline"][-1]["month"]) - month_number(p["as_of"])
    if remaining_plan_months <= 0:
        raise ValueError("No unobserved baseline months remain after the forecast cutoff; a delay cannot create a new schedule")
    if horizon > remaining_plan_months + s["delay_months"]:
        raise ValueError("Forecast horizon exceeds the supplied baseline plus its explicit delayed cash-flow tail")
    if isinstance(n_simulations, bool) or not isinstance(n_simulations, int) or not 1 <= n_simulations <= 20000:
        raise ValueError("n_simulations must be an integer in [1,20000]")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    model = fit_corrections(p)
    actual_ledger = cashflow_ledger(p["actuals"], p["financing"], actuals=True)
    state = closing_state(actual_ledger, p["financing"])
    fin = copy.deepcopy(p["financing"])
    fin["annual_interest_rate"] += float(s["annual_rate_shift"])
    if not 0 <= fin["annual_interest_rate"] <= 1.0:
        raise ValueError("Scenario annual interest rate must remain in [0,1]")
    point_rows, deferred = _future_rows(p, model, horizon, s)
    point_ledger = cashflow_ledger(point_rows, fin, state)
    cash_paths, fcf_paths, dscr_paths = _cash_path_simulation(point_rows, fin, state, model, n_simulations, seed)
    cash_q = np.quantile(cash_paths, (0.1, 0.5, 0.9), axis=0)
    fcf_q = np.quantile(fcf_paths, (0.1, 0.5, 0.9), axis=0)
    floor = fin["minimum_cash"]
    probability_below = (cash_paths < floor - 1e-7).mean(axis=0)
    monthly = []
    for i, row in enumerate(point_ledger):
        monthly.append({**row,
                        "p10_cash": float(cash_q[0, i]), "p50_cash": float(cash_q[1, i]), "p90_cash": float(cash_q[2, i]),
                        "p10_free_cash_flow": float(fcf_q[0, i]), "p50_free_cash_flow": float(fcf_q[1, i]), "p90_free_cash_flow": float(fcf_q[2, i]),
                        "probability_cash_below_floor": float(probability_below[i])})
    minimum_paths = cash_paths.min(axis=1)
    min_quantiles = np.quantile(minimum_paths, (0.1, 0.5, 0.9))
    terminal_q = np.quantile(cash_paths[:, -1], (0.1, 0.5, 0.9))
    point_min = min(row["closing_cash"] for row in monthly)
    operations_start = p.get("operations_start") or next((r["month"] for r in p["baseline"] if r["receipts"] > 0), point_rows[0]["month"])
    # For a project already operating, a suspension itself is an operating risk
    # and must not be excluded from DSCR. For construction, commissioning moves.
    effective_operations_start = add_months(operations_start, s["delay_months"]) if operations_start > p["as_of"] else operations_start
    operating_dscr = [r["dscr"] for r in monthly if r["month"] >= effective_operations_start and r["dscr"] is not None]
    all_dscr = [r["dscr"] for r in monthly if r["dscr"] is not None]
    # Warning metadata must describe the actual requested cutoff, not only
    # the default cutoff in the original fixture.
    warnings = list(validation["warnings"])
    if any(v > 1e-8 for v in deferred.values()):
        warnings.append("Cash flows remain beyond the selected horizon; deferred component totals are reported and have not been discarded from the input.")
    unobserved = [c for c in FLOW_COMPONENTS if model["components"][c]["active_observations"] == 0]
    if unobserved:
        warnings.append("No active observed history for: " + ", ".join(unobserved) + "; baseline/prior used.")
    summary = {
        "currency": p["currency"], "amount_unit": p["amount_unit"],
        "as_of": p["as_of"], "forecast_start": monthly[0]["month"], "forecast_end": monthly[-1]["month"],
        "opening_cash_at_cutoff": state["cash"], "opening_debt_at_cutoff": state["debt"],
        "min_cash": point_min, "terminal_cash": monthly[-1]["closing_cash"],
        "peak_funding_gap": max(floor - point_min, 0.0),
        "peak_negative_cash": max(-point_min, 0.0),
        "terminal_debt": monthly[-1]["closing_debt"],
        "minimum_cash_floor": floor,
        "min_dscr": min(operating_dscr) if operating_dscr else None,
        "min_dscr_all_periods": min(all_dscr) if all_dscr else None,
        "effective_operations_start": effective_operations_start,
        "probability_min_cash_below_floor": float((minimum_paths < floor - 1e-7).mean()),
        "probability_negative_cash": float((minimum_paths < -1e-7).mean()),
        "p10_min_cash": float(min_quantiles[0]), "p50_min_cash": float(min_quantiles[1]), "p90_min_cash": float(min_quantiles[2]),
        "p10_terminal_cash": float(terminal_q[0]), "p50_terminal_cash": float(terminal_q[1]), "p90_terminal_cash": float(terminal_q[2]),
        "mean_peak_funding_gap": float(np.maximum(floor - minimum_paths, 0.0).mean()),
        "deferred_receipts": deferred["receipts"], "deferred_capex": deferred["capex"],
        "deferred_beyond_horizon": deferred,
        "n_simulations": n_simulations, "seed": seed,
    }
    return {
        "schema_version": "1.0", "project_id": p["project_id"], "synthetic_data": p["synthetic_data"],
        "as_of": p["as_of"], "scenario": s, "model": model,
        "monthly": monthly, "summary": summary, "actual_ledger": actual_ledger,
        "assumptions": {
            "cash_basis": "Cash receipts/payments; no additional working-capital adjustment.",
            "facility": "Nonrevolving cumulative-draw limit; repayments do not restore headroom; availability_end enforced.",
            "interest": "Opening debt times nominal annual interest rate divided by 12; draws occur at month end.",
            "cash_shortfall": "Negative cash is unmet funding; no automatic equity injection, refinancing or debt-service forgiveness.",
            "cfads": "Receipts minus opex, supplied cash taxes and maintenance capex; construction capex excluded.",
            "dscr": "Monthly diagnostic CFADS/(interest+contractual principal capped by opening debt), null if service is zero; not a legal covenant determination.",
            "scenario_delay": "Shift remaining unobserved physical/operating cash schedules; equity and principal dates stay fixed. A construction delay only before operations begin.",
            "tax": "Cash tax schedule supplied as input; scenario multipliers do not recalculate statutory taxes.",
            "point_forecast": "Expected component amounts through a nonlinear financing waterfall; not necessarily expected closing cash.",
            "uncertainty": "Conditional lognormal shocks, AR(1)=0.65, common innovation variance share=0.35, plus persistent parameter shocks. Model-conditioned, not real-world calibrated probabilities.",
            "percentiles": "P10 lower, P50 median, P90 upper. Monthly quantiles are not a single coherent joint path.",
            "not_modelled": "Fees, reserves, intra-month liquidity, tax law, FX, refinancing, distributions and off-balance contingent obligations.",
        },
        "warnings": warnings,
    }


def _fcf(row: dict) -> float:
    return float(row["receipts"] - row["opex"] - row["tax"] - row["maintenance_capex"] - row["capex"])


def backtest(project: dict, min_train: int = 12, horizon: int = 3) -> dict:
    """Rolling-origin, fixed-horizon evaluation of *prefinancing* cash flows.

    Uses all supplied outcomes only as a historical evaluation fixture. Every
    origin independently removes its future before fitting. Overlapping test
    windows are reported, not treated as independent statistical experiments.
    No random train/test split and no tuning on test outcomes are performed.
    """
    validate_project(project)
    if isinstance(min_train, bool) or not isinstance(min_train, int) or min_train < 3:
        raise ValueError("min_train must be an integer >=3")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    rows = project["actuals"]
    if len(rows) < min_train + horizon:
        raise ValueError("Not enough actual outcomes for requested backtest")
    plan = {r["month"]: r for r in project["baseline"]}
    methods = ("plan", "last_observation", "adjusted")
    errors = {name: [] for name in methods}
    component_errors = {name: {c: [] for c in FLOW_COMPONENTS} for name in methods}
    component_actuals = {c: [] for c in FLOW_COMPONENTS}
    origin_rows = []
    for stop in range(min_train, len(rows) - horizon + 1):
        cutoff = rows[stop - 1]["month"]
        prefix = observed_project(project, cutoff)
        model = fit_corrections(prefix)
        last = prefix["actuals"][-1]
        targets = rows[stop:stop + horizon]
        origin = {"as_of": cutoff, "target_end": targets[-1]["month"], "horizon": horizon, "methods": {}}
        by_origin = {name: [] for name in methods}
        for actual in targets:
            baseline = plan[actual["month"]]
            predictions = {
                "plan": {c: baseline[c] for c in FLOW_COMPONENTS},
                "last_observation": {c: last[c] for c in FLOW_COMPONENTS},
                "adjusted": {c: baseline[c] * model["components"][c]["multiplier"] for c in FLOW_COMPONENTS},
            }
            for c in FLOW_COMPONENTS:
                component_actuals[c].append(float(actual[c]))
            for method, predicted in predictions.items():
                e = _fcf(predicted) - _fcf(actual)
                errors[method].append(e)
                by_origin[method].append(e)
                for c in FLOW_COMPONENTS:
                    component_errors[method][c].append(float(predicted[c] - actual[c]))
        for method in methods:
            arr = np.array(by_origin[method])
            origin["methods"][method] = {"mae": float(np.abs(arr).mean()), "rmse": float(np.sqrt((arr ** 2).mean()))}
        origin_rows.append(origin)
    metrics = {}
    for method in methods:
        arr = np.array(errors[method])
        wape = {}
        for c in FLOW_COMPONENTS:
            denominator = sum(abs(x) for x in component_actuals[c])
            wape[c] = sum(abs(x) for x in component_errors[method][c]) / denominator if denominator > 1e-12 else None
        metrics[method] = {
            "net_cashflow_mae": float(np.abs(arr).mean()),
            "net_cashflow_rmse": float(np.sqrt((arr ** 2).mean())),
            "net_cashflow_bias": float(arr.mean()),
            "absolute_error_sum": float(np.abs(arr).sum()),
            "squared_error_sum": float((arr ** 2).sum()),
            "predictions": len(arr),
            "component_wape": wape,
        }
    return {
        "project_id": project["project_id"], "synthetic_data": project["synthetic_data"],
        "currency": project["currency"], "amount_unit": project["amount_unit"],
        "target": "prefinancing_free_cash_flow",
        "min_train_months": min_train, "horizon_months": horizon,
        "rolling_origins": len(origin_rows), "prediction_count": len(errors["plan"]),
        "first_origin": origin_rows[0]["as_of"], "last_origin": origin_rows[-1]["as_of"],
        "methods": metrics, "origin_results": origin_rows,
        "limitations": [
            "Synthetic outcomes do not establish real-project predictive accuracy.",
            "Overlapping rolling-origin windows are dependent; no statistical significance is claimed.",
            "The frozen plan is assumed available at every origin; real deployment needs archived plan vintages.",
            "The last-observation comparator ignores known phases and seasonality; it is deliberately a simple baseline.",
            "Uncertainty bands are not empirically calibrated or evaluated in this point-forecast experiment.",
        ],
    }
