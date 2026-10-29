# SPDX-License-Identifier: Apache-2.0
"""Synthetic loopback Bifrost + development DAG integration, never a live-model proof.

The gate attestations below are test fixtures only. They do not close the recorded
capture circuit, consent, production logging suppression or live availability gates.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cells.development import DevelopmentSwarm, DevelopmentTask, ExecutionPolicy, LIVE_GATES
from metarouter.gateway import GatewayClient, GatewayConfig, LiveGate

RUBRIC_TEXT = "SYNTHETIC TEST RUBRIC: review artifacts; never execute model tools.\n"
RUBRIC_HASH = hashlib.sha256(RUBRIC_TEXT.encode()).hexdigest()
MODEL = "muse-wonder-1.0"
TOKEN_ENV = "METACOH_LOOPBACK_INTEGRATION_VK"
DUMMY_KEY = "synthetic-loopback-key-no-real-credential"


@contextmanager
def synthetic_bifrost(mutate=None, parallel_ids=()):
    """Serve JSON completions over real TCP, scoped to literal loopback only."""
    lock = threading.Lock()
    barrier = threading.Barrier(len(parallel_ids), timeout=3) if parallel_ids else None
    state = {"requests": [], "events": [], "active": 0, "peak": 0, "errors": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                task = json.loads(body["messages"][-1]["content"])
                ident = task["id"]
                with lock:
                    state["requests"].append({"path": self.path, "headers": self.headers,
                                               "body": body, "task": task})
                    state["events"].append(("received", ident))
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                if ident in parallel_ids:
                    barrier.wait()
                output = {"rubric_sha256": RUBRIC_HASH,
                          "artifacts": {task["owned_paths"][0]: "SYNTHETIC PROPOSAL\n" + ident},
                          "evidence": ["Synthetic loopback fixture, no upstream model or product proof"]}
                message = {"role": "assistant", "content": json.dumps(output)}
                if mutate:
                    mutate(task, output, message)
                    message["content"] = json.dumps(output)
                payload = {"model": "meta/" + MODEL,
                           "choices": [{"message": message, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 7, "completion_tokens": 3,
                                     "total_tokens": 10}}
                raw = json.dumps(payload).encode()
                with lock:
                    state["events"].append(("responded", ident))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except Exception as exc:
                with lock:
                    state["errors"].append(type(exc).__name__)
                self.send_error(500)
            finally:
                with lock:
                    state["active"] -= 1

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01},
                              daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(httpd.server_port), state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


class BifrostDevelopmentIntegration(unittest.TestCase):
    def make_task(self, ident, dependencies=(), role="coder"):
        return DevelopmentTask(ident, "SYNTHETIC: propose text only", ("proposals/" + ident + ".py",),
                               RUBRIC_HASH, dependencies=dependencies, role=role)

    def client(self, url):
        return GatewayClient(GatewayConfig(url, token_env=TOKEN_ENV, timeout_s=5,
                                            allow_loopback_http=True),
                             LiveGate(True, True, "SYNTHETIC TEST ONLY dry-run attestation",
                                      "SYNTHETIC TEST ONLY owner attestation"))

    def execute(self, url, tasks):
        client = self.client(url)
        policy = ExecutionPolicy(RUBRIC_HASH, mode="meta-api", approved_gates=tuple(LIVE_GATES))
        swarm = DevelopmentSwarm(tasks, policy, max_concurrency=2)

        def run(task, dependencies, attempt):
            request = {"id": task.id, "instruction": task.instruction,
                       "rubric_sha256": task.rubric_sha256,
                       "owned_paths": task.owned_paths, "dependencies": dict(dependencies),
                       "attempt": attempt}
            response = client.complete(MODEL, [
                {"role": "system", "content": RUBRIC_TEXT},
                {"role": "user", "content": json.dumps(request)}],
                role=task.role, max_tokens=128)
            self.assertEqual(response["status"], "UNVERIFIED")
            self.assertEqual(response["evidence_scope"], "generated_proposal")
            return json.loads(response["content"])

        with patch.dict(os.environ, {TOKEN_ENV: DUMMY_KEY}), \
                patch("subprocess.run", side_effect=AssertionError("generated command executed")), \
                patch("subprocess.Popen", side_effect=AssertionError("generated command executed")), \
                patch("os.system", side_effect=AssertionError("generated command executed")):
            return swarm.execute(run, lambda task, out: all(
                value.startswith("SYNTHETIC PROPOSAL") for value in out["artifacts"].values()))

    def assert_request_contract(self, state):
        self.assertEqual(state["errors"], [])
        for row in state["requests"]:
            self.assertEqual(row["path"], "/v1/chat/completions")
            self.assertEqual(row["headers"]["x-bf-vk"], DUMMY_KEY)
            self.assertEqual(row["headers"]["x-bf-disable-content-logging"], "true")
            self.assertIsNone(row["headers"].get("Authorization"))
            self.assertEqual(row["body"]["model"], "meta/" + MODEL)
            self.assertEqual(row["body"]["max_tokens"], 128)
            self.assertEqual(row["task"]["rubric_sha256"], RUBRIC_HASH)
            self.assertEqual(row["body"]["messages"][0]["content"], RUBRIC_TEXT)
            self.assertNotIn("tools", row["body"])

    def test_plan_parallel_feature_tasks_then_review_over_real_http(self):
        tasks = [self.make_task("plan", role="planner"),
                 self.make_task("api", ("plan",)), self.make_task("ui", ("plan",)),
                 self.make_task("review", ("api", "ui"), role="general")]
        with synthetic_bifrost(parallel_ids=("api", "ui")) as (url, state):
            report = self.execute(url, tasks)
        self.assert_request_contract(state)
        self.assertEqual(report["status"], "CHECKED")
        self.assertEqual(report["mode"], "meta-api")
        self.assertEqual(set(report["tasks"]), {"plan", "api", "ui", "review"})
        self.assertEqual(len(state["requests"]), 4)
        self.assertEqual(state["peak"], 2)
        events = state["events"]
        self.assertLess(events.index(("responded", "plan")), events.index(("received", "api")))
        self.assertLess(events.index(("responded", "plan")), events.index(("received", "ui")))
        for ident in ("api", "ui"):
            self.assertLess(events.index(("responded", ident)), events.index(("received", "review")))
        requests = {r["task"]["id"]: r["task"] for r in state["requests"]}
        self.assertEqual(set(requests["review"]["dependencies"]), {"api", "ui"})
        self.assertEqual(set(requests["api"]["dependencies"]), {"plan"})
        self.assertNotIn(DUMMY_KEY, json.dumps(report))
        self.assertIn("product verification not established", report["proof_scope"])

    def test_bad_result_acknowledgement_or_ownership_blocks_review(self):
        def wrong_ack(task, output, message):
            if task["id"] == "implement":
                output["rubric_sha256"] = "b" * 64
        def wrong_ownership(task, output, message):
            if task["id"] == "implement":
                output["artifacts"] = {"outside/owned-scope.py": "SYNTHETIC PROPOSAL"}
        for mutation in (wrong_ack, wrong_ownership):
            with self.subTest(mutation=mutation.__name__):
                tasks = [self.make_task("plan", role="planner"),
                         self.make_task("implement", ("plan",)),
                         self.make_task("review", ("implement",), role="general")]
                with synthetic_bifrost(mutate=mutation) as (url, state):
                    report = self.execute(url, tasks)
                self.assert_request_contract(state)
                self.assertEqual(report["status"], "PARTIAL")
                self.assertEqual(report["tasks"]["plan"]["status"], "CHECKED")
                self.assertEqual(report["tasks"]["implement"]["status"], "FAILED")
                self.assertEqual(report["tasks"]["review"]["status"], "BLOCKED")
                self.assertEqual([r["task"]["id"] for r in state["requests"]], ["plan", "implement"])

    def test_tool_response_is_rejected_and_generated_python_remains_text(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "model-must-not-write-this"
            code = "__import__('pathlib').Path(" + repr(str(marker)) + ").write_text('executed')"
            def malicious_tool(task, output, message):
                message["tool_calls"] = [{"id": "fixture", "type": "function",
                                          "function": {"name": "python", "arguments": code}}]
            with synthetic_bifrost(mutate=malicious_tool) as (url, state):
                report = self.execute(url, [self.make_task("implement"),
                                           self.make_task("review", ("implement",))])
            self.assertEqual(report["tasks"]["implement"]["status"], "FAILED")
            self.assertEqual(report["tasks"]["review"]["status"], "BLOCKED")
            self.assertEqual(len(state["requests"]), 1)
            self.assertFalse(marker.exists())
            def code_as_text(task, output, message):
                output["artifacts"][task["owned_paths"][0]] = "SYNTHETIC PROPOSAL\n" + code
            with synthetic_bifrost(mutate=code_as_text) as (url, state):
                report = self.execute(url, [self.make_task("implement")])
            self.assertEqual(report["status"], "CHECKED")
            self.assertIn(code, report["tasks"]["implement"]["output"]["artifacts"]["proposals/implement.py"])
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
