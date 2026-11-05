# SPDX-License-Identifier: Apache-2.0
"""Background agent pipelines. Agents react to bus events, think through the gateway, and only ever
PROPOSE (emit events); they never speak to the person and never write the ledger. The voice core
decides what to say. All runs happen on one daemon worker thread so `bus.emit` never blocks."""
import json, queue, threading, time
from collections import deque
from datetime import datetime

SOURCE = "runtime.agents"


class Skip(Exception):
    """Raise from a job to stop its pipeline quietly; the reason is reported as skipped:<reason>."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = str(reason)


class Job:
    def __init__(self, name, deps=(), run=None):
        self.name = name
        self.deps = (deps,) if isinstance(deps, str) else tuple(deps)
        self.run = run


class Pipeline:
    def __init__(self, name, jobs):
        self.name = name
        self.jobs = list(jobs)
        self._by_name = {}
        for job in self.jobs:
            if job.name in self._by_name:
                raise ValueError(f"duplicate job {job.name!r} in pipeline {name!r}")
            self._by_name[job.name] = job
        for job in self.jobs:
            for dep in job.deps:
                if dep not in self._by_name:
                    raise ValueError(f"job {job.name!r} in pipeline {name!r} depends on unknown job {dep!r}")
        self.order = self._topo_sort()

    def _topo_sort(self):
        # Kahn's algorithm; whatever is left when it stalls is in (or downstream of) a cycle.
        indeg = {job.name: len(job.deps) for job in self.jobs}
        dependents = {job.name: [] for job in self.jobs}
        for job in self.jobs:
            for dep in job.deps:
                dependents[dep].append(job.name)
        ready = deque(sorted(n for n, d in indeg.items() if d == 0))
        order = []
        while ready:
            n = ready.popleft()
            order.append(n)
            for m in sorted(dependents[n]):
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if len(order) != len(self.jobs):
            cycle = sorted(n for n, d in indeg.items() if d > 0)
            raise ValueError(f"cycle in pipeline {self.name!r} involving jobs: {', '.join(cycle)}")
        return order

    def run(self, seed=None):
        ctx = dict(seed or {})
        for name in self.order:
            job = self._by_name[name]
            if job.run is None:
                ctx[name] = None
                continue
            try:
                ctx[name] = job.run(ctx)
            except Skip as e:
                return {"skipped": e.reason}
        return ctx


class Agent:
    def __init__(self, name, triggers, pipeline, role=None):
        self.name = name
        self.triggers = (triggers,) if isinstance(triggers, str) else tuple(triggers)
        self.pipeline = pipeline
        self.role = role

    def __repr__(self):
        return f"Agent({self.name!r})"


def _agent_field(agent, field, default=None):
    if isinstance(agent, dict):
        return agent.get(field, default)
    return getattr(agent, field, default)


class AgentRunner:
    def __init__(self, bus, gateway=None, tools=None, max_runs=20, window_s=600.0, clock=None, **kw):
        # Accept a few natural spellings for the loop-guard knobs.
        if "max_per_window" in kw:
            max_runs = kw.pop("max_per_window")
        if "per_window_limit" in kw:
            max_runs = kw.pop("per_window_limit")
        if "max_runs_per_window" in kw:
            max_runs = kw.pop("max_runs_per_window")
        if "runs_per_window" in kw:
            max_runs = kw.pop("runs_per_window")
        if "rate_limit" in kw:
            max_runs = kw.pop("rate_limit")
        if "limit" in kw:
            max_runs = kw.pop("limit")
        if "window" in kw:
            window_s = kw.pop("window")
        if "window_seconds" in kw:
            window_s = kw.pop("window_seconds")
        if "time_fn" in kw and clock is None:
            clock = kw.pop("time_fn")
        if kw:
            raise TypeError(f"unknown AgentRunner arguments: {sorted(kw)}")
        self.bus, self.gateway, self.tools = bus, gateway, tools
        self.max_runs, self.window_s = int(max_runs), float(window_s)
        self.clock = clock or time.monotonic
        self.queue = queue.Queue()
        self._agents = {}
        self._handlers = {}
        self._seen = {}
        self._runs = {}
        self._throttled_at = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.worker = None
        self.thread = None
        self._thread = None
        self._load_done()
        self.start()

    # --- idempotency across restarts ---
    def _load_done(self, agent_name=None):
        replay = getattr(self.bus, "replay", None)
        if replay is None:
            return
        try:
            events = replay() or ()
            for ev in events:
                if not isinstance(ev, dict) or ev.get("type") != "agent.done":
                    continue
                data = ev.get("data") or {}
                name, eid = data.get("agent"), data.get("event_id")
                if name and eid and (agent_name is None or name == agent_name):
                    self._seen.setdefault(name, set()).add(eid)
        except Exception:
            return

    # --- lifecycle ---
    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return self
        self._stop.clear()
        self.worker = threading.Thread(target=self._work, name="runtime-agents", daemon=True)
        self.thread = self.worker
        self._thread = self.worker
        self.worker.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self.queue.put_nowait(None)
        except Exception:
            pass
        if self.worker is not None:
            self.worker.join(timeout=2.0)

    def drain(self, timeout=5.0):
        deadline = time.monotonic() + (timeout if timeout is not None else 0)
        while True:
            if self.queue.unfinished_tasks == 0:
                return True
            if timeout is not None and time.monotonic() >= deadline:
                return self.queue.unfinished_tasks == 0
            time.sleep(0.005)

    # --- registration / intake ---
    def register(self, agent):
        name = _agent_field(agent, "name")
        triggers = _agent_field(agent, "triggers") or ()
        if isinstance(triggers, str):
            triggers = (triggers,)
        if not name:
            raise ValueError("agent must declare a name")
        self._agents[name] = agent
        self._seen.setdefault(name, set())
        self._load_done(name)

        def handler(ev, _agent=agent, _name=name):
            self.handle_event(_agent, ev)

        self._handlers[name] = handler
        self.bus.subscribe(handler, types=set(triggers))
        return agent

    def handle_event(self, agent, ev):
        name = _agent_field(agent, "name")
        if not isinstance(ev, dict):
            return False
        if str(ev.get("source") or "").startswith(SOURCE):
            return False
        eid = ev.get("id")
        now = self.clock()
        throttled = False
        with self._lock:
            seen = self._seen.setdefault(name, set())
            if eid is not None:
                if eid in seen:
                    return False
                seen.add(eid)
            runs = self._runs.setdefault(name, deque())
            while runs and runs[0] <= now - self.window_s:
                runs.popleft()
            if len(runs) >= self.max_runs:
                last = self._throttled_at.get(name)
                if last is None or now - last >= self.window_s:
                    self._throttled_at[name] = now
                    throttled = True
                # excess: suppress the run whether or not we announce it this window
                runs = None
            else:
                runs.append(now)
        if runs is None:
            if throttled:
                self.bus.emit("agent.throttled", {"agent": name, "event_id": eid}, SOURCE)
            return False
        self.queue.put((agent, ev))
        return True

    # Backwards/easy aliases for direct delivery in tests and adapters.
    _on_event = handle_event
    enqueue = handle_event
    submit = handle_event

    # --- worker ---
    def _work(self):
        while not self._stop.is_set():
            try:
                item = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                agent, ev = item
                self._run_one(agent, ev)
            finally:
                self.queue.task_done()

    def _run_one(self, agent, ev):
        name = _agent_field(agent, "name")
        pipeline = _agent_field(agent, "pipeline")
        t0 = time.monotonic()
        try:
            seed = {"event": ev, "event_id": ev.get("id"), "data": ev.get("data") or {},
                    "bus": self.bus, "gateway": self.gateway, "tools": self.tools, "agent": name}
            if pipeline is None:
                result = {}
            elif hasattr(pipeline, "run"):
                result = pipeline.run(seed)
            elif callable(pipeline):
                result = pipeline(seed)
            else:
                result = {}
            if isinstance(result, dict) and "skipped" in result:
                status = f"skipped:{result['skipped']}"
            else:
                status = "ok"
        except Skip as e:
            status = f"skipped:{e.reason}"
        except Exception as e:  # GatewayError (incl. 402) and any other failure: never crash the worker
            status = f"skipped:{e}"
        ms = round((time.monotonic() - t0) * 1000)
        try:
            self.bus.emit("agent.done", {"agent": name, "event_id": ev.get("id"), "status": status, "ms": ms}, SOURCE)
        except Exception:
            pass


# --- shared helpers for the default agents ---

def _resolve(ctx, key, fallback=None):
    value = ctx.get(key)
    return fallback if value is None else value


def _strip_fences(text):
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_json(content):
    try:
        obj = json.loads(_strip_fences(content))
    except Exception:
        raise Skip("malformed JSON from model")
    if not isinstance(obj, dict):
        raise Skip("malformed JSON from model")
    return obj


def _gateway_content(ctx, fallback_gateway, role, prompt):
    gateway = _resolve(ctx, "gateway", fallback_gateway)
    if gateway is None:
        raise Skip("no gateway")
    data, model, _rid = gateway.complete({"role": role, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1200})
    content = data["choices"][0]["message"]["content"]
    return content, model


def _today_count(tools):
    events = getattr(tools, "events", None)
    if not isinstance(events, (list, tuple)):
        return None
    clock = getattr(tools, "clock", None) or time.time
    try:
        now = clock()
    except Exception:
        now = time.time()
    start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return sum(1 for e in events if not isinstance(e, dict) or "t" not in e or (e.get("t") or 0) >= start)


# --- default agents: gather -> think -> validate -> emit ---

def _optimizer_pipeline(bus=None, gateway=None, tools=None):
    def gather(ctx):
        tls = _resolve(ctx, "tools", tools)
        count = _today_count(tls) if tls is not None else None
        if count is not None and count < 3:
            raise Skip("fewer than 3 ledger events today")
        summary = tls.t_get_summary("today")
        return {"summary": summary}

    def think(ctx):
        summary = ctx["gather"]["summary"]
        prompt = ("Given today's time summary, propose ONE concrete change to reduce context switches or waiting. "
                  f"Summary: {json.dumps(summary)}. Answer only as JSON {{\"suggestion\": str, \"reason\": str}}.")
        content, model = _gateway_content(ctx, gateway, "agent.background", prompt)
        return {"content": content, "model": model}

    def validate(ctx):
        obj = _parse_json(ctx["think"]["content"])
        suggestion = str(obj.get("suggestion") or "").strip()
        reason = str(obj.get("reason") or "").strip()
        if not suggestion or len(suggestion) > 240:
            raise Skip("invalid suggestion")
        if not reason:
            raise Skip("invalid suggestion")
        return {"text": suggestion, "suggestion": suggestion, "reason": reason, "model": ctx["think"].get("model")}

    def emit(ctx):
        v = ctx["validate"]
        summary = ctx["gather"]["summary"]
        data = {"agent": "optimizer", "kind": "optimization", "text": v["text"], "reason": v["reason"],
                "evidence": {"switches": summary.get("switches"), "lost_min": summary.get("lost_min")}}
        bs = _resolve(ctx, "bus", bus)
        bs.emit("insight.proposed", data, SOURCE, causation_id=ctx.get("event_id"))
        return data

    return Pipeline("optimizer", [Job("gather", (), gather), Job("think", ("gather",), think),
                                  Job("validate", ("think",), validate), Job("emit", ("validate",), emit)])


def _summarizer_pipeline(bus=None, gateway=None, tools=None):
    def gather(ctx):
        tls = _resolve(ctx, "tools", tools)
        summary = None
        if tls is not None and hasattr(tls, "t_get_summary"):
            try:
                summary = tls.t_get_summary("today")
            except Exception:
                summary = None
        return {"event_data": ctx.get("data") or {}, "summary": summary}

    def think(ctx):
        prompt = ("Write ONE sentence noting what the finished time block was and how long it lasted. "
                  f"Finished block: {json.dumps(ctx['gather']['event_data'])}. Today: {json.dumps(ctx['gather']['summary'])}.")
        content, model = _gateway_content(ctx, gateway, "agent.background", prompt)
        return {"content": content, "model": model}

    def validate(ctx):
        text = _strip_fences(ctx["think"]["content"]).strip().strip('"')
        if not text:
            raise Skip("empty note")
        text = text.splitlines()[0].strip()
        if not text:
            raise Skip("empty note")
        return {"text": text, "model": ctx["think"].get("model")}

    def emit(ctx):
        data = {"agent": "summarizer", "kind": "note", "text": ctx["validate"]["text"]}
        bs = _resolve(ctx, "bus", bus)
        bs.emit("insight.proposed", data, SOURCE, causation_id=ctx.get("event_id"))
        return data

    return Pipeline("summarizer", [Job("gather", (), gather), Job("think", ("gather",), think),
                                   Job("validate", ("think",), validate), Job("emit", ("validate",), emit)])


def _planner_pipeline(bus=None, gateway=None, tools=None):
    def gather(ctx):
        tls = _resolve(ctx, "tools", tools)
        all_tasks = tls.t_list_tasks()
        open_tasks = [t for t in all_tasks if t.get("status") != "done"]
        if len(open_tasks) < 2:
            raise Skip("fewer than 2 open tasks")
        summary = tls.t_get_summary("today") if hasattr(tls, "t_get_summary") else {}
        return {"tasks": open_tasks, "open_tasks": open_tasks, "summary": summary,
                "task_ids": [t["task_id"] for t in open_tasks]}

    def think(ctx):
        prompt = ("Order these open tasks into a plan for today. "
                  f"Open tasks: {json.dumps(ctx['gather']['open_tasks'])}. Today summary: {json.dumps(ctx['gather']['summary'])}. "
                  "Answer only as JSON {\"order\": [task_id...], \"rationale\": str, \"next\": task_id}.")
        content, model = _gateway_content(ctx, gateway, "agent.planner", prompt)
        return {"content": content, "model": model}

    def validate(ctx):
        obj = _parse_json(ctx["think"]["content"])
        open_ids = list(ctx["gather"]["task_ids"])
        raw = obj.get("order") if isinstance(obj.get("order"), list) else []
        order, seen = [], set()
        for tid in raw:
            if tid in open_ids and tid not in seen:
                order.append(tid)
                seen.add(tid)
        for tid in open_ids:
            if tid not in seen:
                order.append(tid)
                seen.add(tid)
        nxt = obj.get("next")
        if nxt not in order:
            nxt = order[0] if order else None
        return {"order": order, "next": nxt, "rationale": str(obj.get("rationale") or ""), "model": ctx["think"].get("model")}

    def emit(ctx):
        v = ctx["validate"]
        data = {"agent": "planner", "order": v["order"], "next": v["next"], "rationale": v["rationale"], "model": v["model"]}
        bs = _resolve(ctx, "bus", bus)
        bs.emit("plan.proposed", data, SOURCE, causation_id=ctx.get("event_id"))
        return data

    return Pipeline("planner", [Job("gather", (), gather), Job("think", ("gather",), think),
                                Job("validate", ("think",), validate), Job("emit", ("validate",), emit)])


def default_agents(bus=None, gateway=None, tools=None):
    return [
        Agent("optimizer", ("ledger.event.added", "timer.stopped"), _optimizer_pipeline(bus, gateway, tools), role="agent.background"),
        Agent("summarizer", ("timer.stopped",), _summarizer_pipeline(bus, gateway, tools), role="agent.background"),
        Agent("planner", ("task.created", "task.updated"), _planner_pipeline(bus, gateway, tools), role="agent.planner"),
    ]


def start_agents(bus, gateway, tools):
    runner = AgentRunner(bus, gateway, tools)
    for agent in default_agents(bus, gateway, tools):
        runner.register(agent)
    runner.start()
    return runner
