# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
import threading
import unittest
from dataclasses import replace
from cells.development import (DevelopmentTask, DevelopmentSwarm, ExecutionPolicy,
                               LIVE_GATES, MAX_CONCURRENCY, MAX_TASKS, MAX_ARTIFACT_BYTES,
                               MAX_INSTRUCTION_CHARS, MAX_PATH_CHARS, offline_dry_run)

HASH = "a" * 64


def task(name, **kwargs):
    return DevelopmentTask(name, "Produce a reviewable draft", (f"src/{name}.py",), HASH,
                           **kwargs)


def output(t):
    return {"rubric_sha256": HASH, "artifacts": {t.owned_paths[0]: "draft"},
            "evidence": ["unit acceptance source"]}


class DevelopmentTests(unittest.TestCase):
    def swarm(self, tasks, **kwargs):
        return DevelopmentSwarm(tasks, ExecutionPolicy(HASH), **kwargs)

    def test_rejects_missing_dependencies_cycles_and_duplicate_ids(self):
        for tasks in ([task("a", dependencies=("missing",))],
                      [task("a", dependencies=("b",)), task("b", dependencies=("a",))],
                      [task("a"), task("a")]):
            with self.assertRaises(ValueError):
                self.swarm(tasks)

    def test_rejects_invalid_task_shape(self):
        for kwargs in ({"owned_paths": ()}, {"owned_paths": ("../x",)},
                       {"owned_paths": ("/tmp/x",)}, {"owned_paths": ("src//x",)},
                       {"owned_paths": ("src/*",)}, {"max_attempts": 3},
                       {"max_attempts": True}, {"instruction": ""},
                       {"dependencies": "parent"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(task("a"), **kwargs)
        for limit in (0, -1, True):
            with self.assertRaises(ValueError):
                self.swarm([task("a")], max_concurrency=limit)
        with self.assertRaises(ValueError):
            ExecutionPolicy("missing")
        with self.assertRaises(ValueError):
            ExecutionPolicy(HASH, mode="direct")

    def test_concurrent_directory_file_and_exact_ownership_collisions_rejected(self):
        for scopes in (("src", "src/a.py"), ("src/a.py", "src/a.py")):
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                self.swarm([replace(task("a"), owned_paths=(scopes[0],)),
                            replace(task("b"), owned_paths=(scopes[1],))])
        # A textual prefix is not a path ancestor.
        self.swarm([replace(task("a"), owned_paths=("src/a",)),
                    replace(task("b"), owned_paths=("src/abc",))])

    def test_dependency_order_allows_sequential_shared_ownership(self):
        a = task("a")
        b = replace(task("b", dependencies=("a",)), owned_paths=a.owned_paths)
        c = replace(task("c", dependencies=("b",)), owned_paths=a.owned_paths)
        calls = []
        def run(t, deps, attempt):
            self.assertEqual(set(deps), set(t.dependencies))
            self.assertEqual(calls, list("abc")[:len(calls)])
            calls.append(t.id)
            return output(t)
        report = self.swarm([c, b, a]).execute(run, lambda t, o: True)
        self.assertEqual(calls, ["a", "b", "c"])
        self.assertEqual(report["status"], "CHECKED")
        events = report["events"]
        for previous, successor in (("a", "b"), ("b", "c")):
            finish = next(e["sequence"] for e in events if e["task"] == previous
                          and e["event"] == "CHECKED")
            start = next(e["sequence"] for e in events if e["task"] == successor
                         and e["event"] == "TASK_STARTED")
            self.assertLess(finish, start)

    def test_concurrency_is_real_and_bounded_without_polling(self):
        barrier = threading.Barrier(2, timeout=3)
        lock = threading.Lock()
        active = 0
        peak = 0
        def run(t, deps, attempt):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait()
                return output(t)
            finally:
                with lock:
                    active -= 1
        report = self.swarm([task(str(i)) for i in range(4)], max_concurrency=2).execute(
            run, lambda t, o: True)
        self.assertEqual(report["status"], "CHECKED")
        self.assertEqual(peak, 2)

    def test_failure_blocks_descendants_but_not_independent_tasks(self):
        calls = []
        def run(t, deps, attempt):
            calls.append(t.id)
            if t.id == "a":
                raise RuntimeError("secret must never enter event logs")
            return output(t)
        report = self.swarm([task("a"), task("b", dependencies=("a",)),
                             task("c", dependencies=("b",)), task("d")]).execute(
            run, lambda t, o: True)
        self.assertEqual(set(calls), {"a", "d"})
        self.assertEqual(report["tasks"]["a"]["status"], "FAILED")
        self.assertEqual(report["tasks"]["b"]["status"], "BLOCKED")
        self.assertEqual(report["tasks"]["c"]["status"], "BLOCKED")
        self.assertEqual(report["tasks"]["d"]["status"], "CHECKED")
        self.assertNotIn("secret must never", json.dumps(report))

    def test_retry_cap_and_retry_completion_trigger(self):
        calls = []
        def run(t, deps, attempt):
            calls.append(attempt)
            return output(t)
        report = self.swarm([task("a", max_attempts=2)]).execute(run, lambda t, o: False)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(report["tasks"]["a"]["attempts"], 2)
        self.assertEqual(report["tasks"]["a"]["status"], "FAILED")
        swarm = self.swarm([task("a", max_attempts=2)])
        report = swarm.execute(lambda t, d, n: output(t) if n == 2 else {}, lambda t, o: True)
        self.assertEqual(report["tasks"]["a"]["status"], "CHECKED")
        self.assertEqual(sum(e["event"] == "RETRY_READY" for e in report["events"]), 1)

    def test_task_acknowledgement_and_gates_block_before_callback(self):
        for t, policy in ((replace(task("a"), rubric_sha256=""), ExecutionPolicy(HASH)),
                          (task("a", required_gates=("consent",)), ExecutionPolicy(HASH)),
                          (task("a"), ExecutionPolicy(HASH, mode="meta-api"))):
            calls = []
            report = DevelopmentSwarm([t], policy).execute(
                lambda *args: calls.append(args), lambda t, o: True)
            self.assertEqual(calls, [])
            self.assertEqual(report["tasks"]["a"]["status"], "BLOCKED")
            self.assertEqual(report["tasks"]["a"]["attempts"], 0)

    def test_named_gates_are_not_inferred(self):
        t = task("a", required_gates=("consent",))
        policy = ExecutionPolicy(HASH, mode="meta-api",
                                 approved_gates=tuple(LIVE_GATES | {"consent"}))
        report = DevelopmentSwarm([t], policy).execute(lambda t, d, a: output(t),
                                                      lambda t, o: True)
        self.assertEqual(report["status"], "CHECKED")
        self.assertEqual(report["mode"], "meta-api")
        self.assertIn("product verification not established", report["proof_scope"])

    def test_non_draft_actions_never_run_even_with_named_approval(self):
        for action in ("push", "publish", "apply", "unknown"):
            calls = []
            report = self.swarm([replace(task("a"), action=action)]).execute(
                lambda *args: calls.append(args), lambda t, o: True)
            self.assertEqual(calls, [])
            self.assertEqual(report["tasks"]["a"]["status"], "BLOCKED")

    def test_output_schema_acknowledgement_scope_and_check_are_enforced(self):
        bad = [{}, {"rubric_sha256": "b" * 64, "artifacts": {"src/a.py": "x"},
                    "evidence": ["source"]},
               {"rubric_sha256": HASH, "artifacts": {"src/unowned.py": "x"},
                "evidence": ["source"]},
               {"rubric_sha256": HASH, "artifacts": {"../src/a.py": "x"},
                "evidence": ["source"]},
               {"rubric_sha256": HASH, "artifacts": {"src/a.py": 123},
                "evidence": ["source"]},
               {"rubric_sha256": HASH, "artifacts": {"src/a.py": "x"}, "evidence": []}]
        for raw in bad:
            with self.subTest(raw=raw):
                checks = []
                report = self.swarm([task("a")]).execute(lambda t, d, a: raw,
                    lambda *args: checks.append(args) or True)
                self.assertEqual(checks, [])
                self.assertEqual(report["tasks"]["a"]["status"], "FAILED")
        # Truthy strings are not an acceptance proof.
        report = self.swarm([task("a")]).execute(lambda t, d, a: output(t),
                                                 lambda t, o: "passed")
        self.assertEqual(report["tasks"]["a"]["status"], "FAILED")

    def test_no_signal_never_retries_or_unblocks_dependents(self):
        calls = []
        report = self.swarm([task("a", max_attempts=2), task("b", dependencies=("a",))]).execute(
            lambda t, d, a: calls.append(t.id) or {"status": "NO_SIGNAL"}, lambda t, o: True)
        self.assertEqual(calls, ["a"])
        self.assertEqual(report["tasks"]["a"]["status"], "NO_SIGNAL")
        self.assertEqual(report["tasks"]["b"]["status"], "BLOCKED")

    def test_dependency_inputs_and_acceptance_cannot_mutate_prior_evidence(self):
        def run(t, deps, attempt):
            if deps:
                deps["a"]["artifacts"]["src/a.py"] = "tampered"
            return output(t)
        def check(t, o):
            o["artifacts"].clear()
            return True
        report = self.swarm([task("a"), task("b", dependencies=("a",))]).execute(run, check)
        self.assertEqual(report["tasks"]["a"]["output"]["artifacts"], {"src/a.py": "draft"})
        self.assertEqual(report["tasks"]["b"]["status"], "CHECKED")

    def test_preflight_exposes_holds_without_running_or_consuming_execution(self):
        tasks = [replace(task("a"), rubric_sha256="b" * 64),
                 replace(task("b"), action="publish"),
                 task("c", required_gates=("consent",)), task("d")]
        swarm = self.swarm(tasks)
        preflight = swarm.preflight()
        self.assertTrue(preflight["a"])
        self.assertTrue(preflight["b"])
        self.assertTrue(preflight["c"])
        self.assertEqual(preflight["d"], [])
        self.assertEqual(swarm.events, [])
        calls = []
        report = swarm.execute(lambda t, d, n: calls.append(t.id) or output(t),
                               lambda t, o: True)
        self.assertEqual(calls, ["d"])
        self.assertEqual(report["tasks"]["c"]["status"], "BLOCKED")

    def test_status_bearing_transport_errors_are_terminal_without_retry(self):
        class TransportFailure(RuntimeError):
            def __init__(self, status):
                self.status = status
                super().__init__("secret remote details")
        for status, expected in (("NO_SIGNAL", "NO_SIGNAL"), ("BLOCKED", "BLOCKED"),
                                 ("FAILED", "FAILED"), ("UNKNOWN_REMOTE", "FAILED")):
            with self.subTest(status=status):
                calls = []
                def run(t, d, n):
                    calls.append(t.id)
                    raise TransportFailure(status)
                report = self.swarm([task("a", max_attempts=2),
                                      task("b", dependencies=("a",))]).execute(run, lambda t, o: True)
                self.assertEqual(calls, ["a"])
                self.assertEqual(report["tasks"]["a"]["status"], expected)
                self.assertEqual(report["tasks"]["a"]["attempts"], 1)
                self.assertEqual(report["tasks"]["b"]["status"], "BLOCKED")
                self.assertNotIn("secret remote details", json.dumps(report))
                self.assertFalse(any(e["event"] == "RETRY_READY" for e in report["events"]))

    def test_explicit_failure_and_promotion_status_cannot_be_laundered_as_checked(self):
        for status in ("FAILED", "BLOCKED", "NO_SIGNAL", "PARTIAL", "VERIFIED",
                       "HUMAN-VALIDATED", "CHECKED", "OK", "", None, [], {}):
            with self.subTest(status=status):
                calls, checks = [], []
                def run(t, d, n):
                    calls.append(t.id)
                    return dict(output(t), status=status)
                report = self.swarm([task("a", max_attempts=2),
                                      task("b", dependencies=("a",))]).execute(
                    run, lambda *args: checks.append(args) or True)
                self.assertEqual(calls, ["a"])
                self.assertEqual(checks, [])
                self.assertIn(report["tasks"]["a"]["status"], ("FAILED", "BLOCKED", "NO_SIGNAL"))
                self.assertEqual(report["tasks"]["b"]["status"], "BLOCKED")
        for status in ("UNVERIFIED", "UNVERIFIED_PROPOSAL"):
            report = self.swarm([task("a")]).execute(
                lambda t, d, n: dict(output(t), status=status), lambda t, o: True)
            self.assertEqual(report["status"], "CHECKED")

    def test_resource_caps_reject_excess_and_accept_boundary_values(self):
        self.swarm([task("a")], max_concurrency=MAX_CONCURRENCY)
        with self.assertRaises(ValueError):
            self.swarm([task("a")], max_concurrency=MAX_CONCURRENCY + 1)
        self.swarm([task(str(i)) for i in range(MAX_TASKS)])
        with self.assertRaises(ValueError):
            self.swarm(task(str(i)) for i in range(MAX_TASKS + 1))
        replace(task("a"), instruction="x" * MAX_INSTRUCTION_CHARS,
                owned_paths=("x" * MAX_PATH_CHARS,))
        for kwargs in ({"instruction": "x" * (MAX_INSTRUCTION_CHARS + 1)},
                       {"owned_paths": ("x" * (MAX_PATH_CHARS + 1),)}):
            with self.assertRaises(ValueError):
                replace(task("a"), **kwargs)

    def test_artifact_cap_counts_utf8_aggregate_and_allows_empty_files(self):
        t = replace(task("a"), owned_paths=("src",))
        def execute(artifacts):
            return self.swarm([t]).execute(lambda t, d, a: {
                "rubric_sha256": HASH, "artifacts": artifacts, "evidence": ["source"]},
                lambda t, o: True)
        self.assertEqual(execute({"src/a.py": "x" * MAX_ARTIFACT_BYTES,
                                  "src/__init__.py": ""})["status"], "CHECKED")
        for artifacts in ({"src/a.py": "x" * MAX_ARTIFACT_BYTES, "src/b.py": "x"},
                          {"src/a.py": "é" * (MAX_ARTIFACT_BYTES // 2 + 1)}):
            self.assertEqual(execute(artifacts)["tasks"]["a"]["status"], "FAILED")
        report = execute({"src/" + "x" * MAX_PATH_CHARS: "x"})
        self.assertEqual(report["tasks"]["a"]["status"], "FAILED")

    def test_offline_fixture_label_artifact_hash_and_event_hash_chain(self):
        swarm = self.swarm([task("a")])
        report = swarm.execute(offline_dry_run, lambda t, o: "OFFLINE DRY RUN" in
                               next(iter(o["artifacts"].values())))
        self.assertEqual(report["mode"], "offline-dry-run")
        self.assertEqual(report["proof_scope"], "offline orchestration")
        self.assertNotIn("VERIFIED", {e["event"] for e in report["events"]})
        record = report["tasks"]["a"]
        self.assertEqual(record["artifact_sha256"]["src/a.py"], hashlib.sha256(
            record["output"]["artifacts"]["src/a.py"].encode()).hexdigest())
        prev = "0" * 64
        for event in report["events"]:
            self.assertEqual(event["previous_sha256"], prev)
            digest = event["sha256"]
            payload = {k: v for k, v in event.items() if k != "sha256"}
            self.assertEqual(digest, hashlib.sha256(json.dumps(payload, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest())
            self.assertEqual(event["rubric_sha256"], HASH)
            prev = digest
        with self.assertRaises(RuntimeError):
            swarm.execute(offline_dry_run, lambda t, o: True)


if __name__ == "__main__":
    unittest.main()
