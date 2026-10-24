#!/usr/bin/env python3
"""Render manuscript figures from the released, executed JSON results.

Requires matplotlib; never synthesizes forecast values for illustration.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs" / "publications" / "figures"
DEST.mkdir(parents=True, exist_ok=True)
latest = json.loads((ROOT / "results/demo/latest.json").read_text())
report = json.loads((ROOT / "results/demo" / latest["run_id"] / "report.json").read_text())
benchmark = json.loads((ROOT / "results/benchmark.json").read_text())
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": "#233044", "text.color": "#233044",
                     "xtick.color": "#405067", "ytick.color": "#405067",
                     "axes.edgecolor": "#a7b2c2", "savefig.facecolor": "white"})
colors = {"baseline": "#177d82", "downside": "#b76b26", "stress": "#9e3153"}
TRANSLATIONS = {'Baseline conditional P10-P90': 'Расчётный диапазон P10-P90', 'Baseline central ledger': 'Базовый прогноз', 'Downside central ledger': 'Неблагоприятный', 'Stress central ledger': 'Стресс', 'Required cash floor: 75': 'Денежный резерв 75 млн руб.', 'Projected closing cash, RUB million': 'Остаток денег на конец месяца, млн руб.', 'Positive terminal cash can coexist with an earlier funding gap': 'Когда проекту не хватает денег', 'Unchanged\nplan': 'Исходный\nплан', 'Last\nobservation': 'Последний\nфакт', 'Corrected\nplan': 'План с\nпоправкой', 'Pooled MAE, RUB million': 'Средняя абсолютная ошибка, млн руб.', '2,520 origin-target pairs': '2 520 прогнозов', 'Synthetic seed': 'Синтетическая реализация', 'Plan MAE - corrected MAE': 'MAE плана минус MAE поправки', 'Correction improves 8 of 12 cases': 'Поправка помогла в 8 случаях из 12', 'Remaining schedule +3 months': 'Сдвиг оставшегося графика на 3 месяца', 'Construction + maintenance CAPEX +10%': 'Строительный и поддерживающий CAPEX +10%', 'Cash receipts -10%': 'Денежные поступления -10%', 'Annual interest rate +2 percentage points': 'Годовая ставка +2 процентных пункта', 'Change in central terminal cash, RUB million': 'Изменение конечного остатка, млн руб.', 'One-factor sensitivities within the fixed forecast horizon': 'Влияние каждого фактора на конечный остаток'}

for language in ("en", "ru"):
    suffix = "_ru" if language == "ru" else ""
    tr = lambda text: TRANSLATIONS.get(text, text) if language == "ru" else text
    months = [r["month"] for r in report["forecasts"]["baseline"]["monthly"]]
    x = np.arange(len(months))
    fig, ax = plt.subplots(figsize=(9.2, 4.8), layout="constrained")
    base = report["forecasts"]["baseline"]["monthly"]
    ax.fill_between(x, [r["p10_cash"] for r in base], [r["p90_cash"] for r in base],
                    color="#177d82", alpha=.13, label=tr("Baseline conditional P10-P90"))
    for name, label in [("baseline", tr("Baseline central ledger")), ("downside", tr("Downside central ledger")), ("stress", tr("Stress central ledger"))]:
        rows = report["forecasts"][name]["monthly"]
        ax.plot(x, [r["closing_cash"] for r in rows], color=colors[name], linewidth=2, label=label)
    ax.axhline(0, color="#233044", linewidth=.8)
    ax.axhline(75, color="#69778a", linestyle="--", linewidth=.8, label=tr("Required cash floor: 75"))
    ticks = list(range(0, len(x), 12)) + [len(x)-1]
    ax.set_xticks(ticks, [months[t] for t in ticks])
    ax.set_ylabel(tr("Projected closing cash, RUB million"))
    ax.set_title(tr("Positive terminal cash can coexist with an earlier funding gap"), loc="left", fontsize=13, pad=16)
    ax.grid(axis="y", alpha=.16)
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncols=2)
    fig.savefig(DEST / ("forecast" + suffix + ".png"), dpi=220)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.0), layout="constrained", gridspec_kw={"width_ratios": [1, 1.45]})
    methods = [("plan", tr("Unchanged\nplan"), "#7b8ca4"), ("last_observation", tr("Last\nobservation"), "#b7c1ce"), ("adjusted", tr("Corrected\nplan"), "#177d82")]
    values = [benchmark["aggregate"][m]["net_cashflow_mae"] for m, _, _ in methods]
    bars = axes[0].bar(range(3), values, color=[c for _, _, c in methods], width=.58)
    axes[0].bar_label(bars, fmt="%.2f", padding=5, fontsize=10)
    axes[0].set_xticks(range(3), [label for _, label, _ in methods], fontsize=9)
    axes[0].set_ylim(0, 29)
    axes[0].set_ylabel(tr("Pooled MAE, RUB million"))
    axes[0].set_title(tr("2,520 origin-target pairs"), loc="left", fontsize=11)
    cases = benchmark["per_project"]
    delta = [r["methods"]["plan"]["net_cashflow_mae"] - r["methods"]["adjusted"]["net_cashflow_mae"] for r in cases]
    axes[1].bar(range(1, 13), delta, color=["#177d82" if d >= 0 else "#9e3153" for d in delta])
    axes[1].axhline(0, color="#233044", linewidth=.8)
    axes[1].set_xticks(range(1, 13))
    axes[1].set_xlabel(tr("Synthetic seed"))
    axes[1].set_ylabel(tr("Plan MAE - corrected MAE"))
    axes[1].set_title(tr("Correction improves 8 of 12 cases"), loc="left", fontsize=11)
    for ax in axes:
        ax.grid(axis="y", alpha=.14)
        ax.set_axisbelow(True)
    fig.savefig(DEST / ("benchmark" + suffix + ".png"), dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.2, 3.4), layout="constrained")
    base_summary = report["forecasts"]["baseline"]["summary"]
    driver_names = [("delay", tr("Remaining schedule +3 months")), ("capex", tr("Construction + maintenance CAPEX +10%")),
                    ("receipts", tr("Cash receipts -10%")), ("rate", tr("Annual interest rate +2 percentage points"))]
    changes = [report["forecasts"]["sensitivity_" + name]["summary"]["terminal_cash"] - base_summary["terminal_cash"] for name, _ in driver_names]
    bars = ax.barh(range(4), changes, color="#526f98", height=.56)
    ax.set_yticks(range(4), [label for _, label in driver_names])
    ax.invert_yaxis()
    ax.set_xlim(min(changes)*1.2, 0)
    ax.bar_label(bars, fmt="%.1f", padding=4, fontsize=10)
    ax.set_xlabel(tr("Change in central terminal cash, RUB million"))
    ax.set_title(tr("One-factor sensitivities within the fixed forecast horizon"), loc="left", fontsize=13, pad=14)
    ax.grid(axis="x", alpha=.15)
    ax.set_axisbelow(True)
    fig.savefig(DEST / ("risk_drivers" + suffix + ".png"), dpi=220)
    plt.close(fig)
print(json.dumps({"figures": [str(p.relative_to(ROOT)) for p in sorted(DEST.glob("*.png"))], "run_id": report["run_id"]}))
