# SPDX-License-Identifier: Apache-2.0
"""Ranked micro workflow changes and trajectory forecast.

Owner rule: every suggestion carries BOTH time won back and cost to adopt.
All assumed constants come from ``leaks["assumptions"]``.
"""

TARGETS = ("switching", "waiting", "re_finding", "admin")

CATALOG = [
    {
        "id": "batch-messages",
        "text": "Batch messages into two windows a day.",
        "targets": "switching",
        "recover_fraction": 0.4,
        "adopt_cost_min": 15.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "tab-group-per-client",
        "text": "Keep one tab group per client.",
        "targets": "switching",
        "recover_fraction": 0.25,
        "adopt_cost_min": 10.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "where-i-put-it-note",
        "text": "Keep a running note of where you put things.",
        "targets": "re_finding",
        "recover_fraction": 0.5,
        "adopt_cost_min": 10.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "search-templates",
        "text": "Save searches you repeat every week.",
        "targets": "re_finding",
        "recover_fraction": 0.3,
        "adopt_cost_min": 20.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "async-status-template",
        "text": "Send blockers with an async status template.",
        "targets": "waiting",
        "recover_fraction": 0.35,
        "adopt_cost_min": 15.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "meeting-office-hours",
        "text": "Move quick questions into weekly office hours.",
        "targets": "waiting",
        "recover_fraction": 0.2,
        "adopt_cost_min": 30.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "voice-log-on-switch",
        "text": "Voice-log time as you switch instead of reconstructing.",
        "targets": "admin",
        "recover_fraction": 0.5,
        "adopt_cost_min": 10.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "weekly-invoice-from-ledger",
        "text": "Raise the weekly invoice straight from the ledger.",
        "targets": "admin",
        "recover_fraction": 0.3,
        "adopt_cost_min": 20.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "shutdown-ritual",
        "text": "Close the day with a five minute shutdown ritual.",
        "targets": "switching",
        "recover_fraction": 0.15,
        "adopt_cost_min": 5.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "default-meeting-25",
        "text": "Shorten default meetings to twenty five minutes.",
        "targets": "waiting",
        "recover_fraction": 0.15,
        "adopt_cost_min": 5.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "file-everything-friday",
        "text": "File receipts and notes every Friday.",
        "targets": "admin",
        "recover_fraction": 0.2,
        "adopt_cost_min": 15.0,
        "adopt_cost_usd": 0.0,
    },
    {
        "id": "link-everything-once",
        "text": "Paste the link where you will look for it next time.",
        "targets": "re_finding",
        "recover_fraction": 0.2,
        "adopt_cost_min": 5.0,
        "adopt_cost_usd": 0.0,
    },
]


def _assumptions(leaks, params=None):
    assumptions = dict(leaks.get("assumptions", {}))
    if params:
        assumptions.update(params)
    return assumptions


def rank(leaks, catalog=None, params=None):
    """Rank catalog items by time won back per cost to adopt."""
    items = catalog if catalog is not None else CATALOG
    assumptions = _assumptions(leaks, params)
    rate = assumptions["hourly_rate_usd"]
    wdays_week = assumptions["workdays_per_week"]
    wdays_year = assumptions["workdays_per_year"]
    per_day = leaks.get("per_day_min", {})
    ranked = []
    for entry in items:
        target = entry["targets"]
        base = float(per_day.get(target, 0.0))
        frac = float(entry["recover_fraction"])
        win_week = base * frac * wdays_week
        if win_week == 0:
            continue
        win_hours_year = base * frac * wdays_year / 60.0
        win_usd_year = win_hours_year * rate
        cost_min = float(entry["adopt_cost_min"])
        cost_usd = float(entry["adopt_cost_usd"])
        score = win_hours_year * rate / (cost_min / 60.0 * rate + cost_usd + 1.0)
        ranked.append(
            {
                "id": entry["id"],
                "text": entry["text"],
                "targets": target,
                "winback_min_per_week": win_week,
                "winback_hours_year": win_hours_year,
                "winback_usd_year": win_usd_year,
                "adopt_cost_min": cost_min,
                "adopt_cost_usd": cost_usd,
                "score": score,
                "evidence": {
                    "component": target,
                    "per_day_min": base,
                    "recover_fraction": frac,
                },
            }
        )
    ranked.sort(key=lambda r: (-r["score"], r["adopt_cost_min"] + r["adopt_cost_usd"]))
    return ranked


def trajectory(leaks, adopted_ids, horizon_weeks=52, catalog=None):
    """Forecast cumulative leaked hours with and without adopted changes."""
    items = catalog if catalog is not None else CATALOG
    assumptions = _assumptions(leaks)
    rate = assumptions["hourly_rate_usd"]
    wdays_week = assumptions["workdays_per_week"]
    per_day = leaks.get("per_day_min", {})
    by_id = {entry["id"]: entry for entry in items}
    factor = {t: 1.0 for t in TARGETS}
    for aid in adopted_ids:
        entry = by_id.get(aid)
        if entry is None:
            continue
        target = entry["targets"]
        if target in factor:
            factor[target] *= 1.0 - float(entry["recover_fraction"])
    base_total = sum(float(per_day.get(t, 0.0)) for t in TARGETS)
    adopted_total = sum(float(per_day.get(t, 0.0)) * factor[t] for t in TARGETS)
    base_total = max(0.0, base_total)
    adopted_total = max(0.0, adopted_total)
    weeks = list(range(1, horizon_weeks + 1))
    current_hours = [(i * base_total * wdays_week / 60.0) for i in weeks]
    adopted_hours = [(i * adopted_total * wdays_week / 60.0) for i in weeks]
    won_back_hours = (current_hours[-1] - adopted_hours[-1]) if weeks else 0.0
    return {
        "weeks": weeks,
        "current_hours": current_hours,
        "adopted_hours": adopted_hours,
        "won_back_hours": won_back_hours,
        "won_back_usd": won_back_hours * rate,
    }
