# SPDX-License-Identifier: Apache-2.0
"""Human question stream: small yes / no / other{text} questions, ranked by value of information, answers fed back as evidence.
Class A work never waits on a question (advisory). Class B questions double as the approval record. Stdlib only."""
import math
from harness.rollout import Ledger

def beta_sd(s, f): a, b = 1 + s, 1 + f; return math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))

class QuestionStream:
    def __init__(self, per_day=5, weight=2.0, approval_ttl=7 * 86400):
        self.q, self.per_day, self.w, self.ttl, self.led, self.asked = {}, per_day, weight, approval_ttl, Ledger(), []
        self.approvals, self.notes = {}, []
    def propose(self, qid, knob, cls, counts, stakes, text):
        """voi = stakes x posterior sd of the knob's success rate: ask where a human answer would change the most belief at the highest stakes."""
        s, f = counts.get(knob, [0, 0]); self.q[qid] = dict(qid=qid, knob=knob, cls=cls, text=text, stakes=stakes, voi=round(stakes * beta_sd(s, f), 6), state="open", advisory=(cls == "A"))
    def next(self, now, k=3):
        today = [t for t in self.asked if now - t < 86400]; room = max(0, self.per_day - len(today))
        open_ = sorted((x for x in self.q.values() if x["state"] == "open"), key=lambda x: (-x["voi"], x["qid"]))[:min(k, room)]
        self.asked += [now] * len(open_); return open_
    def answer(self, qid, choice, who, now, text=None):
        x = self.q[qid]
        if choice not in ("yes", "no", "other"): raise ValueError("choice must be yes, no or other")
        if choice == "other" and not (text or "").strip(): raise ValueError("other needs text")
        x["state"] = "answered"; self.led.add(event="ANSWER", qid=qid, knob=x["knob"], choice=choice, who=who, text=text, ts=now)
        if choice == "yes" and x["cls"] == "B": self.approvals[x["knob"]] = now + self.ttl
        if choice == "other": self.notes.append(dict(qid=qid, knob=x["knob"], text=text, who=who))      # free text: kept for rule review, never auto-parsed into action
    def apply_to_counts(self, counts):
        """yes/no become weighted pseudo-observations for the knob's success posterior; they inform, they do not gate class A."""
        out = {k: list(v) for k, v in counts.items()}
        for r in self.led.rows:
            if r["event"] == "ANSWER" and r["choice"] in ("yes", "no"):
                s, f = out.get(r["knob"], [0, 0]); out[r["knob"]] = [s + self.w * (r["choice"] == "yes"), f + self.w * (r["choice"] == "no")]
        return out
    def approved(self, knob, now): return self.approvals.get(knob, 0) > now
