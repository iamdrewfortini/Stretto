# SPDX-License-Identifier: Apache-2.0
"""Event-driven development DAGs producing checked, reviewable artifacts only.

Callbacks are trusted host code, not a sandbox: they must enforce their own transport
and filesystem restrictions, including callback deadlines: Python worker threads cannot
be safely terminated by this scheduler. The scheduler never runs generated commands or writes
artifacts. CHECKED means the supplied acceptance callback passed, never five-sided
product verification. Offline dry runs are labelled on every event and result.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from types import MappingProxyType
import json
import re
import time

MAX_CONCURRENCY = 16
MAX_TASKS = 128
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_INSTRUCTION_CHARS = 65536
MAX_PATH_CHARS = 4096

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
LIVE_GATES = frozenset({"circuit-dry-run-proven", "owner-approved-meta-calls",
                        "meta-gateway-contract-verified"})


def _path(value):
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS or "\\" in value:
        raise ValueError("ownership/artifact paths must be nonempty POSIX paths")
    parts = value.split("/")
    if value.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError("ownership/artifact paths must be normalized relative paths")
    if any(c in value for c in "*?[]"):
        raise ValueError("ownership paths must be explicit, without glob patterns")
    return PurePosixPath(value)


def _within(path, scope):
    return path == scope or scope in path.parents


@dataclass(frozen=True)
class DevelopmentTask:
    id: str
    instruction: str
    owned_paths: tuple
    rubric_sha256: str
    dependencies: tuple = ()
    required_gates: tuple = ()
    max_attempts: int = 1
    role: str = "coder"
    action: str = "draft"

    def __post_init__(self):
        for name in ("owned_paths", "dependencies", "required_gates"):
            value = getattr(self, name)
            if isinstance(value, str):
                raise ValueError(f"{name} must be a sequence, not a string")
            object.__setattr__(self, name, tuple(value))
        if not isinstance(self.id, str) or not _ID.fullmatch(self.id):
            raise ValueError("task id must be a nonempty identifier")
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise ValueError("task instruction is required")
        if len(self.instruction) > MAX_INSTRUCTION_CHARS:
            raise ValueError("task instruction exceeds character limit")
        if not self.owned_paths:
            raise ValueError("explicit task file ownership is required")
        for p in self.owned_paths:
            _path(p)
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("duplicate dependencies")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 2:
            raise ValueError("max_attempts must be one or two; recurring failure stops")
        if not all(isinstance(x, str) and x for x in self.required_gates):
            raise ValueError("required gates must be named")


@dataclass(frozen=True)
class ExecutionPolicy:
    rubric_sha256: str
    mode: str = "offline-dry-run"
    approved_gates: tuple = ()

    def __post_init__(self):
        if not isinstance(self.rubric_sha256, str) or not _SHA.fullmatch(self.rubric_sha256):
            raise ValueError("policy requires an exact rubric SHA256")
        if self.mode not in ("offline-dry-run", "meta-api"):
            raise ValueError("mode must be offline-dry-run or meta-api")
        if isinstance(self.approved_gates, str):
            raise ValueError("approved_gates must be a sequence")
        object.__setattr__(self, "approved_gates", frozenset(self.approved_gates))


class DevelopmentSwarm:
    """A bounded, single-execution DAG. Completion events unlock successors.

    run(task, dependency_outputs, attempt) returns JSON-compatible data with:
      rubric_sha256, artifacts={relative_path: text}, evidence=[source/check strings].
    check(task, output) returns literal True only after checking task acceptance.
    Required approvals are declarations supplied by the trusted caller, not signatures.
    """
    def __init__(self, tasks, policy, max_concurrency=4):
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= MAX_CONCURRENCY:
            raise ValueError(f"max_concurrency must be between one and {MAX_CONCURRENCY}")
        self.policy, self.max_concurrency = policy, max_concurrency
        self.tasks = {}
        for task in tasks:
            if len(self.tasks) >= MAX_TASKS:
                raise ValueError(f"task count exceeds {MAX_TASKS}")
            if not isinstance(task, DevelopmentTask):
                raise TypeError("tasks must be DevelopmentTask instances")
            if task.id in self.tasks:
                raise ValueError(f"duplicate task id: {task.id}")
            self.tasks[task.id] = task
        if not self.tasks:
            raise ValueError("at least one task is required")
        # Precedence resolution: validate references, topologically sort, then
        # reject overlapping scopes only for tasks that can run concurrently.
        pending = {key: set(task.dependencies) for key, task in self.tasks.items()}
        for key, deps in pending.items():
            unknown = deps - self.tasks.keys()
            if unknown:
                raise ValueError(f"{key}: unknown dependencies {sorted(unknown)}")
        self.order, ancestors = [], {}
        while pending:
            ready = sorted(k for k, deps in pending.items() if not deps)
            if not ready:
                raise ValueError("dependency cycle: " + ", ".join(sorted(pending)))
            for key in ready:
                self.order.append(key)
                deps = self.tasks[key].dependencies
                ancestors[key] = set(deps).union(*(ancestors[d] for d in deps))
                del pending[key]
            for deps in pending.values():
                deps.difference_update(ready)
        for i, a in enumerate(self.order):
            for b in self.order[i + 1:]:
                if a in ancestors[b] or b in ancestors[a]:
                    continue
                for x in self.tasks[a].owned_paths:
                    for y in self.tasks[b].owned_paths:
                        if _within(_path(x), _path(y)) or _within(_path(y), _path(x)):
                            raise ValueError(f"concurrent ownership collision: {a}, {b}: {x}, {y}")
        self.events, self._used = [], False

    def _event(self, event, task=None, **data):
        row = dict(sequence=len(self.events), event=event, task=task,
                   mode=self.policy.mode, rubric_sha256=self.policy.rubric_sha256,
                   **data)
        row["previous_sha256"] = self.events[-1]["sha256"] if self.events else "0" * 64
        row["sha256"] = sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                          allow_nan=False).encode()).hexdigest()
        self.events.append(row)

    def _gate(self, task):
        problems = []
        if task.rubric_sha256 != self.policy.rubric_sha256:
            problems.append("task rubric acknowledgement missing or mismatched")
        if task.action != "draft":
            problems.append(f"action {task.action!r} is outside reviewable-artifact execution")
        required = set(task.required_gates)
        if self.policy.mode == "meta-api":
            required.update(LIVE_GATES)
        missing = required - self.policy.approved_gates
        if missing:
            problems.append("held gates: " + ", ".join(sorted(missing)))
        return problems

    def _validate_output(self, task, raw):
        if not isinstance(raw, dict):
            raise ValueError("runner output must be an object")
        # Copy into JSON to detach callback data and reject executable/custom objects.
        output = json.loads(json.dumps(raw, allow_nan=False))
        if output.get("rubric_sha256") != self.policy.rubric_sha256:
            raise ValueError("result rubric acknowledgement missing or mismatched")
        artifacts, evidence = output.get("artifacts"), output.get("evidence")
        if not isinstance(artifacts, dict) or not artifacts:
            raise ValueError("result must contain reviewable artifacts")
        if not isinstance(evidence, list) or not evidence or not all(
                isinstance(e, str) and e.strip() for e in evidence):
            raise ValueError("result evidence pointers/check descriptions are required")
        scopes = [_path(p) for p in task.owned_paths]
        artifact_bytes = 0
        for name, content in artifacts.items():
            path = _path(name)
            if not any(_within(path, scope) for scope in scopes):
                raise ValueError(f"artifact outside task ownership: {name}")
            if not isinstance(content, str):
                raise ValueError("artifact content must be text")
            artifact_bytes += len(content.encode("utf-8"))
            if artifact_bytes > MAX_ARTIFACT_BYTES:
                raise ValueError("aggregate artifact content exceeds byte limit")
        return output

    def execute(self, run, check):
        if self._used:
            raise RuntimeError("swarm already executed; construct a new run with explicit intent")
        self._used = True
        states = {key: "PENDING" for key in self.tasks}
        attempts = {key: 0 for key in self.tasks}
        results, outputs = {}, {}
        self._event("RUN_STARTED", max_concurrency=self.max_concurrency)

        def finish(key, status, reasons, output=None):
            states[key] = status
            record = dict(status=status, attempts=attempts[key], reasons=reasons,
                          mode=self.policy.mode, rubric_sha256=self.policy.rubric_sha256)
            if output is not None:
                record["output"] = output
                record["artifact_sha256"] = {p: sha256(c.encode()).hexdigest()
                                              for p, c in output["artifacts"].items()}
                outputs[key] = output
            results[key] = record
            self._event(status, key, attempts=attempts[key], reasons=reasons,
                        artifact_sha256=record.get("artifact_sha256", {}))

        # Policy failures are terminal before any callback for that task.
        for key in self.order:
            problems = self._gate(self.tasks[key])
            if problems:
                finish(key, "BLOCKED", problems)
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            running = {}
            while any(s in ("PENDING", "RUNNING") for s in states.values()):
                for key in self.order:
                    if states[key] != "PENDING":
                        continue
                    task = self.tasks[key]
                    bad = [d for d in task.dependencies
                           if states[d] in ("FAILED", "BLOCKED", "NO_SIGNAL")]
                    if bad:
                        finish(key, "BLOCKED", ["dependency did not pass: " + ", ".join(bad)])
                    elif len(running) < self.max_concurrency and all(
                            states[d] == "CHECKED" for d in task.dependencies):
                        attempts[key] += 1
                        states[key] = "RUNNING"
                        # Detached dependency data: a runner cannot mutate earlier evidence.
                        deps = json.loads(json.dumps({d: outputs[d] for d in task.dependencies}))
                        self._event("TASK_STARTED", key, attempt=attempts[key],
                                    dependencies=list(task.dependencies))
                        future = executor.submit(run, task, MappingProxyType(deps), attempts[key])
                        running[future] = (key, time.monotonic())
                if not running:
                    continue
                completed, _ = wait(running, return_when=FIRST_COMPLETED)
                # Stable processing for events already completed together; dispatch
                # remains driven by completion rather than timers or polling.
                for future in sorted(completed, key=lambda f: running[f][0]):
                    key, started = running.pop(future)
                    task = self.tasks[key]
                    reason, output, status = None, None, "FAILED"
                    try:
                        raw = future.result()
                        if isinstance(raw, dict) and raw.get("status") == "NO_SIGNAL":
                            status, reason = "NO_SIGNAL", "runner reported NO_SIGNAL"
                        else:
                            output = self._validate_output(task, raw)
                            accepted = check(task, json.loads(json.dumps(output)))
                            if accepted is not True:
                                raise ValueError("acceptance check did not return True")
                    except Exception as exc:
                        # Never echo exception text: transports may include secrets.
                        reason = "runner or acceptance failed: " + type(exc).__name__
                    self._event("ATTEMPT_FINISHED", key, attempt=attempts[key],
                                elapsed_s=time.monotonic() - started,
                                accepted=reason is None)
                    if reason is None:
                        finish(key, "CHECKED", [], output)
                    elif status != "NO_SIGNAL" and attempts[key] < task.max_attempts:
                        states[key] = "PENDING"
                        self._event("RETRY_READY", key, attempt=attempts[key], reason=reason)
                    else:
                        finish(key, status, [reason])
        overall = "CHECKED" if all(v == "CHECKED" for v in states.values()) else "PARTIAL"
        self._event("RUN_FINISHED", status=overall)
        return dict(status=overall, mode=self.policy.mode,
                    proof_scope="offline orchestration" if self.policy.mode == "offline-dry-run"
                    else "reviewable development artifacts; product verification not established",
                    rubric_sha256=self.policy.rubric_sha256,
                    tasks=results, events=list(self.events))


def offline_dry_run(task, dependency_outputs, attempt):
    """Deterministic fixture producer; no model, filesystem or shell execution."""
    path = str(_path(task.owned_paths[0]))
    # Explicit file ownership recommended; directory scopes receive a draft file.
    if not PurePosixPath(path).suffix:
        path += "/draft.txt"
    return dict(rubric_sha256=task.rubric_sha256,
                artifacts={path: f"OFFLINE DRY RUN\nTask: {task.id}\n{task.instruction}\n"},
                evidence=["Deterministic offline fixture; no model call; not product verification"],
                dependencies=sorted(dependency_outputs), attempt=attempt)
