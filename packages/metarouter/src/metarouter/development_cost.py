# SPDX-License-Identifier: Apache-2.0
"""Exact bounded attempt-policy optimization over declared synthetic inputs.

Attempts stop after the first success. Successes are assumed independent and
per-attempt costs fixed; neither assumption is a measured gateway/billing claim.
The optimizer uses rational arithmetic, including for the reliability floor.
"""
from fractions import Fraction
from itertools import permutations
import math
import random
import re

from .policy import CATALOG

MAX_ENDPOINTS = 8
MAX_TRIALS = 1_000_000
ASSUMPTIONS = [
    "Supplied costs and success probabilities are synthetic declarations, not live measurements.",
    "Attempt successes are independent; each attempt incurs its fixed declared cost.",
    "Fallback is attempted only after failure; stop on first success.",
    "Distinct endpoint IDs do not prove independent failures in real deployments.",
    "Optimality covers only the supplied finite candidate set and attempt limit.",
]


def _number(value, name, probability=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    number = Fraction(str(value))
    if number <= 0 or (probability and number > 1):
        raise ValueError(f"{name} is outside its allowed range")
    # Keep JSON output finite and bounded without imposing a billing unit.
    if not probability and number > 1_000_000_000_000:
        raise ValueError(f"{name} exceeds the declared-cost bound")
    return number


def _candidates(candidates, limit=MAX_ENDPOINTS):
    if not isinstance(candidates, (list, tuple)) or not 1 <= len(candidates) <= limit:
        raise ValueError(f"candidates must contain between one and {limit} endpoints")
    result, ids = [], set()
    for raw in candidates:
        if not isinstance(raw, dict) or not {"id", "model", "cost", "success_probability"} <= raw.keys():
            raise ValueError("candidate requires id, model, cost and success_probability")
        if raw.keys() - {"id", "model", "role", "cost", "success_probability"}:
            raise ValueError("unknown candidate fields")
        ident, model, role = raw["id"], raw["model"], raw.get("role", "coder")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", ident):
            raise ValueError("candidate id must be a bounded identifier")
        if ident in ids:
            raise ValueError("candidate IDs must be distinct")
        ids.add(ident)
        if not isinstance(model, str) or model not in CATALOG:
            raise ValueError("candidate must use a catalogued Meta model")
        if not isinstance(role, str) or role not in {"planner", "coder", "general"}:
            raise ValueError("unsupported development role")
        if role not in CATALOG[model]["roles"]:
            raise ValueError("candidate model does not support its role")
        cost = _number(raw["cost"], "cost")
        probability = _number(raw["success_probability"], "success_probability", True)
        result.append((dict(id=ident, model=model, role=role, cost=raw["cost"],
                            success_probability=raw["success_probability"]), cost, probability))
    if len({row[0]["role"] for row in result}) != 1:
        raise ValueError("attempt candidates must address the same development role")
    return sorted(result, key=lambda row: row[0]["id"])


def _evaluate(attempts):
    failure, expected = Fraction(1), Fraction(0)
    for _, cost, probability in attempts:
        expected += failure * cost
        failure *= 1 - probability
    return expected, 1 - failure


def _policy(attempts):
    cost, success = _evaluate(attempts)
    return dict(attempts=[dict(row[0]) for row in attempts], expected_cost=float(cost),
                success_probability=float(success),
                exact={"expected_cost": str(cost), "success_probability": str(success)})


def optimize_policy(candidates, min_success, max_attempts=2):
    """Return the exact cheapest admissible policy, or explicit NO_SIGNAL.

    Candidate fields: id, model, cost, success_probability, optional role (coder).
    Costs share caller-declared units. Probabilities are in (0, 1]. Up to eight
    candidates and two distinct attempts yield at most 64 ordered policies.
    Ties prefer fewer attempts, then lexicographic endpoint IDs. Never lowers
    the supplied reliability floor to produce an answer.
    """
    rows = _candidates(candidates)
    target = _number(min_success, "min_success", True)
    if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
        raise ValueError("max_attempts must be one or two")
    all_policies, feasible = [], []
    for count in range(1, min(max_attempts, len(rows)) + 1):
        for attempts in permutations(rows, count):
            expected, success = _evaluate(attempts)
            policy = _policy(attempts)
            policy["meets_floor"] = success >= target
            all_policies.append(policy)
            if success >= target:
                feasible.append((expected, count, tuple(a[0]["id"] for a in attempts), policy))
    common = dict(min_success=float(target), exact_min_success=str(target),
                  candidates=[dict(row[0]) for row in rows],
                  max_attempts=max_attempts, policies_evaluated=all_policies,
                  assumptions=list(ASSUMPTIONS), evidence_scope="synthetic_cost_model")
    if not feasible:
        return dict(common, status="NO_SIGNAL", policy=None,
                    reason="No admissible supplied policy meets the required success floor.")
    best = min(feasible, key=lambda row: row[:3])
    return dict(common, status="OK", policy=best[3],
                optimality={"method": "exhaustive rational enumeration",
                            "evaluated_policy_count": len(all_policies),
                            "feasible_policy_count": len(feasible),
                            "exact_cost_gap_to_oracle": "0"})


def simulate_policy(policy, trials=10000, seed=0):
    """Seeded synthetic simulation compared with the exact policy expectation.

    The two Hoeffding bounds have joint failure probability at most 0.001 by
    union bound. A failed comparison is reported as a miss, never smoothed.
    Accept either a selected policy or the optimizer's complete OK result.
    """
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    optimization = policy if "policy" in policy else None
    if optimization is not None:
        if optimization.get("status") != "OK" or optimization.get("policy") is None:
            raise ValueError("cannot simulate an infeasible policy")
        # Recompute, rather than forwarding an untrusted claimed oracle result.
        oracle = optimize_policy(optimization.get("candidates"),
                                 optimization.get("min_success"),
                                 optimization.get("max_attempts"))
        if oracle["status"] != "OK" or optimization["policy"] != oracle["policy"]:
            raise ValueError("supplied optimizer result does not match its exact oracle")
        policy = optimization["policy"]
    rows = _candidates(policy.get("attempts"), limit=2)
    # Validation sorts candidates for determinism; execution must retain order.
    by_id = {row[0]["id"]: row for row in rows}
    rows = [by_id[raw["id"]] for raw in policy["attempts"]]
    if type(trials) is not int or not 1 <= trials <= MAX_TRIALS:
        raise ValueError(f"trials must be within [1, {MAX_TRIALS}]")
    if type(seed) is not int or not -(2 ** 63) <= seed < 2 ** 63:
        raise ValueError("seed must be a signed 64-bit integer")
    expected, success = _evaluate(rows)
    rng, wins, total, attempts_used = random.Random(seed), 0, 0.0, 0
    for _ in range(trials):
        for _, cost, probability in rows:
            total += float(cost)
            attempts_used += 1
            if rng.random() < float(probability):
                wins += 1
                break
    success_tolerance = math.sqrt(math.log(4000) / (2 * trials))
    cost_tolerance = float(sum(row[1] for row in rows)) * success_tolerance
    measured_success, measured_cost = wins / trials, total / trials
    matches = (abs(measured_success - float(success)) <= success_tolerance
               and abs(measured_cost - float(expected)) <= cost_tolerance)
    return dict(status="PASS" if matches else "MISS", evidence_scope="seeded_synthetic_simulation",
                trials=trials, seed=seed, successes=wins, attempts_used=attempts_used,
                observed_success_probability=measured_success, observed_mean_cost=measured_cost,
                exact_policy=_policy(rows),
                absolute_error={"success_probability": abs(measured_success - float(success)),
                                "mean_cost": abs(measured_cost - float(expected))},
                hoeffding_bounds={"success_absolute_tolerance": success_tolerance,
                                  "cost_absolute_tolerance": cost_tolerance,
                                  "joint_failure_probability_at_most": 0.001},
                assumptions=list(ASSUMPTIONS),
                oracle_comparison=(oracle["optimality"] if optimization else None))
