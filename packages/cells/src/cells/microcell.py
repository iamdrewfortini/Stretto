# SPDX-License-Identifier: Apache-2.0
"""Meta micro cell core. Every call a cell makes passes, in order: WF-13D readiness and stops (bridge) -> Meta-only and gateway policy -> speed-aware routing -> provenance row
carrying the WF-13D address, the cell's attention focus and its stated intent. Nothing here executes real work: run/check are injected."""
from wf13d.bridge import State
from metarouter.speed import SpeedRouter
from coherence.attention import Attention
from metarouter.policy import check_agent
from harness.rollout import Ledger

ROLE_OF = {"text": "planner", "code": "coder", "vision": "vision", "image": "image", "voice": "voice"}

class MicroCell:
    def __init__(self, name, state, router, attention, budget_usd=1.0, price_per_s=0.01, ledger=None):
        for e in router.eps:
            bad = check_agent(dict(id=e.name, model=e.model))
            if bad: raise ValueError("; ".join(bad))
        self.name, self.state, self.router, self.att, self.budget, self.price, self.spent = name, state, router, attention, budget_usd, price_per_s, 0.0
        self.led = ledger or Ledger()
    def _row(self, event, **kw): self.led.add(event=event, cell=self.name, addr=self.state.view()["key"], mode=self.router.mode, **kw)
    def observe(self, obs):
        r = self.att.step(obs); self._row("FOCUS", focus=r["focus"], shifted=r["shifted"], preempted=r["preempted"], alignment=r["alignment"], drift=r["drift"], entropy=r["entropy"]); return r
    def confirm(self, delta): self.state.step(delta, source="human"); self._row("CONFIRM", delta=delta, line=self.state.line())
    def gate(self, kind, approvals=()):
        v = self.state.view(); P = []
        if kind == "observe": return P
        if kind == "draft" and len(v["known"]) < 4 and "S4" not in v["stops"]: P.append(f"READY {v['ready']} < 2/3 (4 of 6 bits): ask first ({', '.join(v['ask'][:v['max_q']])})")
        if kind == "materialize":
            if v["ready"] < 1.0: P.append(f"READY {v['ready']} < 1.0: cannot materialize")
            if "S2" in v["stops"] and "S2" not in approvals: P.append("S2: irreversible edge needs human approval")
            if "S3" in v["stops"] and "S3" not in approvals: P.append("S3: evidence is partial and the edge irreversible: escalate")
            if "S6" in v["stops"] and not any(a.startswith("S6:fate:") for a in approvals): P.append("S6: declare fate (SHARED|ISOLATED) first")
        if kind not in ("observe", "draft", "materialize"): P.append(f"unknown task kind '{kind}'")
        return P
    def act(self, modality, kind, task, run, check, approvals=()):
        problems = self.gate(kind, approvals)
        if self.spent >= self.budget: problems.append(f"cell budget {self.budget} spent")
        if problems: self._row("BLOCKED", kind=kind, problems=problems); return dict(status="BLOCKED", problems=problems)
        plan = self.router.plan(ROLE_OF[modality], task, self.price)
        if plan is None: self._row("NO_SIGNAL", kind=kind, role=ROLE_OF[modality]); return dict(status="NO_SIGNAL", why=f"no eligible Meta endpoint for '{ROLE_OF[modality]}' in {self.router.mode} mode")
        res = self.router.execute(plan, task, run, check); self.spent += plan["cost"]
        self._row("ACT", kind=kind, modality=modality, task=task, strategy=plan["strategy"], endpoints=[e.name for e in plan["eps"]], exp_cost=round(plan["cost"], 5), exp_time=round(plan["time"], 3), J=round(plan["J"], 5),
                  result=res["status"], lane=res.get("lane"), secs=round(res["secs"], 4), focus=self.att.focus, intent=sorted(self.att.intent))
        return res
