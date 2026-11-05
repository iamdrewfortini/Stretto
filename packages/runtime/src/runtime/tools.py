# SPDX-License-Identifier: Apache-2.0
"""The voice core's tools over the owner's time ledger and tasks. State is a projection of bus events, so replaying
the event log rebuilds it exactly. Every write is one bus event; every tool returns JSON-serialisable data or raises ToolError."""
import json, threading, time, uuid
from datetime import datetime

from humanflow.personal import CATEGORIES, PersonalLedger

STATUSES = ("todo", "doing", "blocked", "done")
PAGES = ("today", "focus", "tasks", "calendar", "paths", "reports", "goals", "habits", "insights", "leaks", "privacy", "devices", "settings", "talk")
MUTATING = {"log_time", "start_timer", "stop_timer", "create_task", "update_task"}


class ToolError(Exception):
    pass


def _fn(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "additionalProperties": False, "required": list(required), "properties": props}}}


ACT = {"type": "string", "enum": list(CATEGORIES), "description": "focus=deep work, meeting, comms=chat/email, search=looking for info, wait=blocked on someone, admin, other"}
SCHEMAS = [
    _fn("log_time", "Record a finished block of time the owner spent on an activity.",
        {"activity": ACT, "minutes": {"type": "integer", "minimum": 1, "maximum": 600}, "note": {"type": "string", "maxLength": 280},
         "task_id": {"type": "string"}}, ["activity", "minutes"]),
    _fn("start_timer", "Start timing an activity now. Stops any running timer first.",
        {"activity": ACT, "task_id": {"type": "string"}, "note": {"type": "string", "maxLength": 280}}, ["activity"]),
    _fn("stop_timer", "Stop the running timer and log its time.", {}),
    _fn("get_summary", "Totals per activity, context switches and time lost to waiting or failed searches.",
        {"range": {"type": "string", "enum": ["today", "all"]}}, ["range"]),
    _fn("create_task", "Create a task for the owner.",
        {"title": {"type": "string", "maxLength": 200}, "estimate_min": {"type": "integer", "minimum": 1, "maximum": 6000}}, ["title"]),
    _fn("update_task", "Change a task's status.",
        {"task_id": {"type": "string"}, "status": {"type": "string", "enum": list(STATUSES)}, "note": {"type": "string", "maxLength": 280}},
        ["task_id", "status"]),
    _fn("list_tasks", "List the owner's tasks, optionally by status.", {"status": {"type": "string", "enum": list(STATUSES)}}),
    _fn("open_page", "Show the person a page of the Stretto app.",
        {"page": {"type": "string", "enum": list(PAGES)}}, ["page"]),
    _fn("get_leaks", "The owner's time leaks: leak score (lower is better), minutes leaked per day, what that compounds to over a "
        "week, month, year and decade in hours and dollars, and the top changes ranked by time won back per cost to adopt.", {}),
]


class Tools:
    def __init__(self, bus, owner="owner", clock=time.time, stretto=None):
        self.bus, self.owner, self.clock, self.lock, self.stretto = bus, owner, clock, threading.Lock(), stretto
        self.events, self.tasks, self.timer = [], {}, None
        for ev in bus.replay():
            self.apply(ev)
        # replay first, then subscribe: each event is applied exactly once
        bus.subscribe(self.apply, types={"ledger.event.added", "timer.started", "timer.stopped", "task.created", "task.updated"})
        self._cid = None

    # --- projection ---
    def apply(self, ev):
        d, t = ev["data"], ev["type"]
        with self.lock:
            if t == "ledger.event.added":
                self.events.append(d)
            elif t == "timer.started":
                self.timer = d
            elif t == "timer.stopped":
                self.timer = None
            elif t == "task.created":
                self.tasks[d["task_id"]] = dict(d)
            elif t == "task.updated" and d["task_id"] in self.tasks:
                self.tasks[d["task_id"]].update(status=d["status"])

    # --- dispatch ---
    def call(self, name, args, correlation_id=None):
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            raise ToolError(f"unknown tool {name}")
        self._cid = correlation_id
        return fn(**args)

    def _mirror(self, method, path, body=None):
        """Apply the same change to the Stretto app, so what the agent says it did is what the person sees."""
        if not self.stretto:
            return None
        try:
            self.stretto.call(method, path, body)
            return "ok"
        except Exception as e:  # the ledger change stands; report why Stretto did not follow
            return f"stretto: {str(e)[:120]}"

    def _emit(self, type_, data):
        return self.bus.emit(type_, data, "runtime.tools", subject=self.owner, correlation_id=self._cid)

    @staticmethod
    def _act(a):
        if a not in CATEGORIES:
            raise ToolError(f"activity must be one of {CATEGORIES}")
        return a

    # --- tools ---
    def t_log_time(self, activity, minutes, note="", task_id=None):
        if not isinstance(minutes, int) or not 1 <= minutes <= 600:
            raise ToolError("minutes must be an integer 1..600")
        now = self.clock()
        e = dict(t=now - minutes * 60, activity=self._act(activity), duration_s=float(minutes * 60), text=note[:280], task_id=task_id)
        ev = self._emit("ledger.event.added", e)
        return {"event_id": ev["id"], "activity": activity, "minutes": minutes}

    def t_start_timer(self, activity, task_id=None, note=""):
        stopped = self.t_stop_timer() if self.timer else None
        d = dict(timer_id="tmr_" + uuid.uuid4().hex[:10], activity=self._act(activity), t=self.clock(), task_id=task_id, note=note[:280])
        self._emit("timer.started", d)
        out = {"timer_id": d["timer_id"], "activity": activity, "stopped_previous": stopped}
        s = self._mirror("POST", "/api/timer/start", {"kind": "focus", "label": (note or activity)[:120]})
        if s:
            out["stretto"] = s
        return out

    def t_stop_timer(self):
        tm = self.timer
        if not tm:
            if self.stretto and self._mirror("POST", "/api/timer/stop") == "ok":
                return {"activity": "focus", "minutes": 0.0, "stretto": "ok", "note": "stopped the timer running in Stretto"}
            raise ToolError("no timer is running")
        secs = max(1.0, self.clock() - tm["t"])
        self._emit("timer.stopped", dict(timer_id=tm["timer_id"], seconds=secs))
        self._emit("ledger.event.added", dict(t=tm["t"], activity=tm["activity"], duration_s=secs, text=tm.get("note", ""), task_id=tm.get("task_id")))
        out = {"timer_id": tm["timer_id"], "activity": tm["activity"], "minutes": round(secs / 60, 1)}
        s = self._mirror("POST", "/api/timer/stop")
        if s:
            out["stretto"] = s
        return out

    def t_get_summary(self, range="today"):
        start = datetime.fromtimestamp(self.clock()).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() if range == "today" else 0
        L = PersonalLedger(self.owner)
        for e in self.events:
            end = e["t"] + e.get("duration_s", 0.0)
            if e["t"] >= start:
                L.add(e)
            elif end > start:  # a block that crosses midnight counts only its part inside the range
                L.add(dict(e, t=start, duration_s=end - start))
        s = L.summary(self.owner)
        mins = lambda x: None if x is None else round(x / 60, 1)
        out = {"range": range, "total_min": mins(s["total_s"]), "by_activity_min": {k: mins(v) for k, v in s["by_category"].items() if v},
               "switches": s["switches"], "lost_min": {k: mins(v) for k, v in s["loss"].items() if v}}
        if self.timer:
            out["running_timer"] = {"activity": self.timer["activity"], "minutes": round((self.clock() - self.timer["t"]) / 60, 1)}
        return out

    def t_create_task(self, title, estimate_min=None):
        d = dict(task_id="tsk_" + uuid.uuid4().hex[:8], title=title[:200], status="todo", estimate_min=estimate_min, t=self.clock())
        self._emit("task.created", d)
        out = {"task_id": d["task_id"], "title": d["title"], "status": "todo"}
        s = self._mirror("POST", "/api/tasks", {"title": d["title"], "est_min": estimate_min})
        if s:
            out["stretto"] = s
        return out

    def t_update_task(self, task_id, status, note=""):
        if task_id not in self.tasks:
            raise ToolError(f"no task {task_id}; call list_tasks to find the id")
        if status not in STATUSES:
            raise ToolError(f"status must be one of {STATUSES}")
        self._emit("task.updated", dict(task_id=task_id, status=status, note=note[:280]))
        return {"task_id": task_id, "status": status}

    def t_open_page(self, page):
        if page not in PAGES:
            raise ToolError(f"page must be one of {PAGES}")
        return {"navigate": page}

    def t_get_leaks(self):
        from runtime import leaks, suggest  # arithmetic only; imported here so the ledger works without them
        lk = leaks.compute(self.t_get_summary("all"), list(self.events), self.clock())
        top = suggest.rank(lk)[:3]
        return {"leak_score": lk["leak_score"], "per_day_min": lk["per_day_min"], "compounded": lk["compounded"],
                "top_changes": [{k: r[k] for k in ("text", "winback_hours_year", "winback_usd_year", "adopt_cost_min", "adopt_cost_usd")} for r in top],
                "assumptions": lk["assumptions"]}

    def t_list_tasks(self, status=None):
        return [{k: t[k] for k in ("task_id", "title", "status", "estimate_min")} for t in self.tasks.values() if status in (None, t["status"])]


def run_tool(tools, call, correlation_id=None):
    """Execute one model tool_call. Errors become a tool result too, so the conversation stays valid for Meta's API."""
    fn = call.get("function", {})
    try:
        args = json.loads(fn.get("arguments") or "{}")
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        result, ok = tools.call(fn.get("name", ""), args, correlation_id), True
    except (ToolError, TypeError, ValueError) as e:
        result, ok = {"error": str(e)}, False
    return {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}, ok, result
