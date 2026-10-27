# SPDX-License-Identifier: Apache-2.0
"""Realtime personal assistant core. It sees only consented, redacted events; it talks only to Meta models (checked at construction); it respects attention (no interruptions during focus
unless urgent, bounded suggestions per hour); and it asks the person's own WF-13D questions before it assumes anything. The model call is injected, so the same code runs against the
Meta Model API, the cluster gateway or an on-device Meta model."""
import math, re
from collections import Counter
from metarouter.policy import check_agent
from wf13d.bridge import State
from perception.redact import scan

def bm25(query, docs, k=3, k1=1.5, b=0.75):
    """Local lexical retrieval over the person's OWN documents (stdlib). Swappable for a Meta-model embedding store once one is evaluated."""
    tok = lambda s: re.findall(r"[a-z0-9]+", s.lower()); D = [tok(d) for d in docs]; N = len(D); avg = sum(map(len, D)) / max(N, 1); df = Counter(w for d in D for w in set(d)); q = tok(query); scores = []
    for i, d in enumerate(D):
        tf = Counter(d); s = 0.0
        for w in q:
            if w in tf: idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5)); s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scores.append((s, i))
    return [i for s, i in sorted(scores, reverse=True)[:k] if s > 0]

class Assistant:
    def __init__(self, person, registry, call_model, model="muse-wonder-1.0", state=None, max_per_hour=6, quiet=("focus",), window=12):
        bad = check_agent(dict(id="assistant", model=model))
        if bad: raise ValueError("; ".join(bad))
        self.person, self.reg, self.call, self.model, self.state = person, registry, call_model, model, state or State(); self.max_h, self.quiet, self.window = max_per_hour, set(quiet), window
        self.events, self.sent = [], []
    def on_event(self, ev, now):
        if self.reg.allows(self.person, ev["source"], "assist", now): self.events.append(ev); return True
        return False
    def questions(self): v = self.state.view(); return v["ask"][:v["max_q"]]
    def suggest(self, now, urgent=False):
        recent = [e for e in self.events if self.reg.allows(self.person, e["source"], "assist", now)][-self.window:]
        if not recent: return dict(status="NO_CONSENTED_EVENTS")
        if recent[-1]["activity"] in self.quiet and not urgent: return dict(status="HELD", why="person is in focus; not interrupting")
        if len([t for t in self.sent if now - t < 3600]) >= self.max_h: return dict(status="HELD", why="hourly suggestion budget used")
        prompt = ("You help one person with their own work. Recent activity (already redacted):\n" + "\n".join(f"- [{e['activity']}] {e['text']}" for e in recent) +
                  "\nOpen questions about their goal: " + (", ".join(self.questions()) or "none") + "\nGive at most two short, concrete suggestions. If the goal is unclear, ask one question instead.")
        assert not scan(prompt), "unredacted data reached the prompt"
        text = self.call(self.model, prompt); self.sent.append(now)
        return dict(status="OK", text=text, model=self.model, event_ids=[e["id"] for e in recent], questions=self.questions())
    def transcribe(self, audio, call_voice, now, model="muse-voice-transcribe-1.0"):
        bad = check_agent(dict(id="voice", model=model))
        if bad: raise ValueError("; ".join(bad))
        if not self.reg.allows(self.person, "audio", "assist", now): return dict(status="NO_CONSENT")
        from perception.redact import redact
        text, counts = redact(call_voice(model, audio)); return dict(status="OK", text=text, redactions=counts, model=model)
