# SPDX-License-Identifier: Apache-2.0
"""Leak loop: on every ledger change, recompute the person's leaks, the ranked changes, their level and the forecast,
and publish them as four events for the /leaks page and the voice core. Pure arithmetic, no model call, so it runs inline."""
from runtime import leaks, suggest

TRIGGERS = {"ledger.event.added", "timer.stopped"}


def snapshot(tools, params=None, now=None):
    """Everything the page and the voice core need, from the current ledger."""
    now = now if now is not None else tools.clock()
    events = list(tools.events)
    lk = leaks.compute(tools.t_get_summary("all"), events, now, params)
    ranked = suggest.rank(lk)
    prog = leaks.progress(leaks.daily_history(events))
    top = [r["id"] for r in ranked[:3]]
    return {"leaks": lk, "ranked": ranked[:5], "progress": prog, "trajectory": suggest.trajectory(lk, top) if top else None}


def publish(bus, tools, params=None):
    s = snapshot(tools, params)
    bus.emit("leaks.computed", s["leaks"], "runtime.leaks")
    bus.emit("suggestions.ranked", {"items": s["ranked"]}, "runtime.leaks")
    bus.emit("progress.updated", s["progress"], "runtime.leaks")
    if s["trajectory"]:
        bus.emit("trajectory.forecast", s["trajectory"], "runtime.leaks")
    return s


def start_leak_loop(bus, tools, params=None):
    """Publish once now, then after every ledger change (the emitted types are not triggers, so it cannot loop)."""
    bus.subscribe(lambda ev: publish(bus, tools, params), types=TRIGGERS)
    return publish(bus, tools, params)
