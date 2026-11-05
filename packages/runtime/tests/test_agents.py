# SPDX-License-Identifier: Apache-2.0
import json, os, tempfile, threading, time, unittest

from runtime.agents import Agent, AgentRunner, Job, Pipeline, Skip, default_agents, start_agents
from runtime.bus import EventBus
from runtime.gateway import GatewayError
from runtime.tools import Tools


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeGateway:
    """Records bodies, returns scripted content (or raises), optionally slowly."""

    def __init__(self, contents=(), error=None, delay=0.0, model="muse-spark-1.3-contributor"):
        self.contents, self.error, self.delay, self.model = list(contents), error, delay, model
        self.bodies, self.started = [], threading.Event()

    def complete(self, body):
        self.bodies.append(body)
        self.started.set()
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        content = self.contents.pop(0) if self.contents else "{}"
        return {"choices": [{"message": {"content": content}}]}, self.model, "req_fake"


def events_of(bus, type_):
    return [e for e in bus.since(0)[0] if e["type"] == type_]


def make_tools(bus, clock=None):
    return Tools(bus, clock=clock or Clock())


class PipelineT(unittest.TestCase):
    def test_topo_order_and_ctx(self):
        calls = []

        def job(name):
            def run(ctx):
                calls.append(name)
                return name.upper()
            return run

        p = Pipeline("p", [Job("c", ("b",), job("c")), Job("a", (), job("a")), Job("b", ("a",), job("b"))])
        out = p.run({"seed": 1})
        self.assertEqual(calls, ["a", "b", "c"])
        self.assertEqual(out["seed"], 1)
        self.assertEqual((out["a"], out["b"], out["c"]), ("A", "B", "C"))

    def test_cycle_names_jobs(self):
        with self.assertRaises(ValueError) as cm:
            Pipeline("p", [Job("a", ("b",), lambda ctx: None), Job("b", ("a",), lambda ctx: None)])
        self.assertIn("a", str(cm.exception))
        self.assertIn("b", str(cm.exception))

    def test_unknown_dep_raises(self):
        with self.assertRaises(ValueError):
            Pipeline("p", [Job("a", ("nope",), lambda ctx: None)])

    def test_skip_stops_pipeline(self):
        calls = []

        def skipper(ctx):
            calls.append("skipper")
            raise Skip("not today")

        p = Pipeline("p", [Job("a", (), skipper), Job("b", ("a",), lambda ctx: calls.append("b"))])
        self.assertEqual(p.run({}), {"skipped": "not today"})
        self.assertEqual(calls, ["skipper"])


class OptimizerT(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.clock = Clock()
        self.tools = make_tools(self.bus, self.clock)
        for activity in ("focus", "meeting", "focus"):
            self.tools.t_log_time(activity, 30)
        self.bus._recent = []  # only observe what agents emit from here

    def tearDown(self):
        if getattr(self, "runner", None):
            self.runner.stop()

    def test_optimizer_emits_valid_insight(self):
        gw = FakeGateway(['```json\n{"suggestion": "Batch comms at 11", "reason": "fewer switches"}\n```'])
        self.runner = start_agents(self.bus, gw, self.tools)
        self.bus.emit("ledger.event.added", {"t": self.clock.t, "activity": "focus", "duration_s": 60.0, "text": ""}, "test")
        self.assertTrue(self.runner.drain(5))
        insights = [e["data"] for e in events_of(self.bus, "insight.proposed") if e["data"].get("agent") == "optimizer"]
        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0]["kind"], "optimization")
        self.assertEqual(insights[0]["text"], "Batch comms at 11")
        self.assertEqual(insights[0]["reason"], "fewer switches")
        self.assertIn("switches", insights[0]["evidence"])
        self.assertIn("lost_min", insights[0]["evidence"])
        self.assertEqual(gw.bodies[0]["role"], "agent.background")
        self.assertEqual(gw.bodies[0]["max_tokens"], 1200)
        done = [e["data"] for e in events_of(self.bus, "agent.done") if e["data"]["agent"] == "optimizer"]
        self.assertEqual(done[-1]["status"], "ok")

    def test_optimizer_ignores_malformed_json(self):
        gw = FakeGateway(["not json at all"])
        self.runner = start_agents(self.bus, gw, self.tools)
        self.bus.emit("ledger.event.added", {"t": self.clock.t, "activity": "focus", "duration_s": 60.0, "text": ""}, "test")
        self.assertTrue(self.runner.drain(5))
        self.assertEqual([e for e in events_of(self.bus, "insight.proposed") if e["data"].get("agent") == "optimizer"], [])
        done = [e["data"] for e in events_of(self.bus, "agent.done") if e["data"]["agent"] == "optimizer"]
        self.assertTrue(done[-1]["status"].startswith("skipped"), done)


class PlannerT(unittest.TestCase):
    def test_planner_repairs_order_and_uses_planner_role(self):
        bus = EventBus()
        tools = make_tools(bus)
        ids = [tools.t_create_task(f"task {i}")["task_id"] for i in range(3)]
        bad = json.dumps({"order": [ids[2], "tsk_unknown", ids[0]], "rationale": "due first", "next": "tsk_unknown"})
        gw = FakeGateway([bad], model="muse-wonder-1.0")
        runner = start_agents(bus, gw, tools)
        try:
            bus.emit("task.created", {"task_id": ids[0], "title": "task 0", "status": "todo", "estimate_min": None}, "test")
            self.assertTrue(runner.drain(5))
        finally:
            runner.stop()
        plans = [e["data"] for e in events_of(bus, "plan.proposed")]
        self.assertEqual(len(plans), 1)
        self.assertEqual(sorted(plans[0]["order"]), sorted(ids))
        self.assertEqual(plans[0]["order"][:2], [ids[2], ids[0]])
        self.assertEqual(plans[0]["order"][-1], ids[1])  # missing task appended in original order
        self.assertIn(plans[0]["next"], plans[0]["order"])
        self.assertEqual(plans[0]["model"], "muse-wonder-1.0")
        planner_calls = [b for b in gw.bodies if b["role"] == "agent.planner"]
        self.assertTrue(planner_calls)
        self.assertEqual(planner_calls[0]["max_tokens"], 1200)


class RunnerT(unittest.TestCase):
    def make_runner(self, bus, pipeline, **kw):
        runner = AgentRunner(bus, FakeGateway(), None, **kw)
        runner.register(Agent("echo", ("ping",), pipeline))
        return runner

    def counting_pipeline(self, counter):
        def run(ctx):
            counter.append(ctx["event_id"])
            return {}
        return Pipeline("echo", [Job("only", (), run)])

    def test_idempotency_across_restart(self):
        d = tempfile.mkdtemp()
        log = os.path.join(d, "events.jsonl")
        counter = []
        bus1 = EventBus(log)
        r1 = self.make_runner(bus1, self.counting_pipeline(counter))
        ev = bus1.emit("ping", {}, "test")
        self.assertTrue(r1.drain(5))
        r1.stop()
        self.assertEqual(counter, [ev["id"]])

        bus2 = EventBus(log)
        r2 = AgentRunner(bus2, FakeGateway(), None)
        agent = Agent("echo", ("ping",), self.counting_pipeline(counter))
        r2.register(agent)
        try:
            # Re-deliver the very same event after restart: agent.done in the log marks it done.
            self.assertFalse(r2.handle_event(agent, ev))
            self.assertTrue(r2.drain(5))
        finally:
            r2.stop()
        self.assertEqual(counter, [ev["id"]])

    def test_loop_guard_ignores_runtime_agents_source(self):
        bus = EventBus()
        counter = []
        runner = self.make_runner(bus, self.counting_pipeline(counter))
        try:
            bus.emit("ping", {}, "runtime.agents")
            bus.emit("ping", {}, "runtime.agents.optimizer")
            self.assertTrue(runner.drain(5))
        finally:
            runner.stop()
        self.assertEqual(counter, [])
        self.assertEqual(events_of(bus, "agent.done"), [])

    def test_throttles_after_limit_once_per_window(self):
        bus = EventBus()
        counter = []
        runner = self.make_runner(bus, self.counting_pipeline(counter), max_runs=3)
        try:
            for _ in range(6):
                bus.emit("ping", {}, "test")
            self.assertTrue(runner.drain(5))
        finally:
            runner.stop()
        self.assertEqual(len(counter), 3)
        self.assertEqual(len(events_of(bus, "agent.throttled")), 1)
        self.assertEqual(len(events_of(bus, "agent.done")), 3)

    def test_gateway_402_becomes_skipped(self):
        bus = EventBus()
        tools = make_tools(bus)
        for activity in ("focus", "meeting", "focus"):
            tools.t_log_time(activity, 30)
        gw = FakeGateway(error=GatewayError(402, "spend limit reached"))
        runner = start_agents(bus, gw, tools)
        try:
            bus.emit("ledger.event.added", {"t": tools.clock(), "activity": "focus", "duration_s": 60.0, "text": ""}, "test")
            self.assertTrue(runner.drain(5))
        finally:
            runner.stop()
        done = [e["data"] for e in events_of(bus, "agent.done") if e["data"]["agent"] == "optimizer"]
        self.assertTrue(done)
        self.assertTrue(done[-1]["status"].startswith("skipped"), done)

    def test_emit_returns_before_agent_finishes(self):
        bus = EventBus()
        tools = make_tools(bus)
        tools.t_create_task("one")
        tools.t_create_task("two")
        gw = FakeGateway([json.dumps({"order": [], "rationale": "r", "next": None})], delay=0.6, model="muse-wonder-1.0")
        runner = start_agents(bus, gw, tools)
        try:
            t0 = time.monotonic()
            bus.emit("task.created", {"task_id": "x", "title": "x", "status": "todo", "estimate_min": None}, "test")
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.3)
            self.assertTrue(gw.started.wait(2))  # worker is off doing the slow call
            self.assertEqual(events_of(bus, "plan.proposed"), [])
            self.assertTrue(runner.drain(5))
            self.assertEqual(len(events_of(bus, "plan.proposed")), 1)
        finally:
            runner.stop()

    def test_summarizer_emits_note_on_timer_stopped(self):
        bus = EventBus()
        tools = make_tools(bus)
        gw = FakeGateway(["Focused work for 25 minutes."])
        runner = start_agents(bus, gw, tools)
        try:
            bus.emit("timer.stopped", {"timer_id": "tmr_x", "seconds": 1500.0}, "test")
            self.assertTrue(runner.drain(5))
        finally:
            runner.stop()
        notes = [e["data"] for e in events_of(bus, "insight.proposed") if e["data"].get("kind") == "note"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["text"], "Focused work for 25 minutes.")

    def test_default_agents_shape(self):
        agents = default_agents()
        self.assertEqual([a.name for a in agents], ["optimizer", "summarizer", "planner"])
        by_name = {a.name: a for a in agents}
        self.assertEqual(by_name["planner"].role, "agent.planner")
        self.assertIn("timer.stopped", by_name["optimizer"].triggers)
        for a in agents:
            self.assertEqual(a.pipeline.order, ["gather", "think", "validate", "emit"])


if __name__ == "__main__":
    unittest.main()
