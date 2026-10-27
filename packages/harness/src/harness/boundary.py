# SPDX-License-Identifier: Apache-2.0
"""Outer boundary. Independent of the optimizer: it imports nothing from it and holds its own copy of the rules.
The envelope is HMAC-signed; any change that is not re-signed makes the check fail closed. Stdlib only."""
import hashlib, hmac, json, os

def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)
def sha(o): return hashlib.sha256(canon(o).encode()).hexdigest()

def sign(env, key): return hmac.new(key, canon(env).encode(), hashlib.sha256).hexdigest()
def file_hashes(paths): return {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in paths}

class Boundary:
    """env: allowed_knobs{name:{min,max}}, forbidden_classes, max_changes_per_day, max_concurrent, require_quiet,
    floors{min_free_ram_gib,max_cpu_overcommit}, budget{max_p99_regression_pct,max_energy_increase_pct}, breaker{max_consecutive_rollbacks},
    protected{path:sha256} (the optimizer's own gate code and this file: self-modification is outside the boundary)."""
    def __init__(self, env, signature, key=None, verify_fn=None): self.env, self.sig, self.key, self.verify_fn = env, signature, key, verify_fn
    @property
    def hash(self): return sha(self.env)
    def intact(self):
        if self.verify_fn:
            ok, why = self.verify_fn(self.env, self.sig)
            if not ok: return f"envelope signature invalid: {why}"
        elif not hmac.compare_digest(self.sig, sign(self.env, self.key)): return "envelope signature invalid"
        for p, h in self.env.get("protected", {}).items():
            try:
                if hashlib.sha256(open(p, "rb").read()).hexdigest() != h: return f"protected file changed: {os.path.basename(p)}"
            except OSError: return f"protected file missing: {p}"
        return None
    def check(self, action, state):
        """action: knob, cls, value, approved(bool). state: changes_today, in_flight, in_quiet_window, free_ram_gib, cpu_overcommit,
        consecutive_rollbacks, frozen, recent_signatures. Returns ('ALLOW'|'DENY', [violations])."""
        v, e = [], self.env
        bad = self.intact()
        if bad: return "DENY", [bad]
        if state.get("frozen"): v.append("frozen: circuit breaker or recurrence stop is latched; human unfreeze required")
        k = e["allowed_knobs"].get(action["knob"])
        if k is None: v.append(f"knob {action['knob']} not in envelope")
        else:
            if action.get("value") is not None and isinstance(action["value"], (int, float)) and not (k["min"] <= action["value"] <= k["max"]): v.append(f"value {action['value']} outside [{k['min']},{k['max']}]")
        if action["cls"] in e["forbidden_classes"]: v.append(f"class {action['cls']} forbidden")
        if action["cls"] == "B" and not action.get("approved"): v.append("class B without a recorded human approval")
        if state["changes_today"] >= e["max_changes_per_day"]: v.append("daily change budget exhausted")
        if state["in_flight"] >= e["max_concurrent"]: v.append("another change is in flight")
        if e["require_quiet"] and not state["in_quiet_window"]: v.append("not inside a measured quiet window")
        f = e["floors"]
        if state["free_ram_gib"] < f["min_free_ram_gib"]: v.append(f"free RAM {state['free_ram_gib']} GiB under floor {f['min_free_ram_gib']}")
        if state["cpu_overcommit"] > f["max_cpu_overcommit"]: v.append(f"CPU overcommit {state['cpu_overcommit']} over {f['max_cpu_overcommit']}")
        if state["consecutive_rollbacks"] >= e["breaker"]["max_consecutive_rollbacks"]: v.append("circuit breaker: too many consecutive rollbacks")
        if recurring(state.get("recent_signatures", [])): v.append("recurrence: the same attempt keeps repeating (never retry a third time)")
        return ("DENY" if v else "ALLOW"), v

def recurring(sigs, maxp=3):
    """Trajectory check (WF-13D rule 1): the tail is periodic with period p<=3 repeated three times -> a loop, not progress."""
    for p in range(1, maxp + 1):
        if len(sigs) >= 3 * p and all(sigs[-1 - i] == sigs[-1 - i - p] == sigs[-1 - i - 2 * p] for i in range(p)): return True
    return False
