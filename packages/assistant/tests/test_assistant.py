# SPDX-License-Identifier: Apache-2.0
import unittest
from assistant import Assistant, bm25
from perception import ConsentRegistry
from wf13d.bridge import State

def ev(i, t, act, text="reading the quarterly report", src="screen"): return dict(id=f"e{i}", t=t, activity=act, text=text, source=src, pseudonym="x")
def mk(**kw):
    r = ConsentRegistry(); r.grant("alice", ["screen", "audio"], ["assist"], 10 ** 6, 0); calls = []
    a = Assistant("alice", r, lambda m, p: calls.append((m, p)) or "Try the template in the shared drive.", **kw); return a, r, calls
class AssistantTests(unittest.TestCase):
    def test_only_meta_models_allowed(self):
        r = ConsentRegistry()
        for m in ("gpt-5", "claude-opus", "grok-4", "chat-12g"):
            with self.assertRaises(ValueError): Assistant("a", r, lambda m, p: "", model=m)
        Assistant("a", r, lambda m, p: "", model="muse-spark-1.3")
    def test_no_consent_no_events_no_model_call(self):
        a, r, calls = mk(); r.revoke("alice", 1); self.assertFalse(a.on_event(ev(1, 2, "comms"), 2)); self.assertEqual(a.suggest(3)["status"], "NO_CONSENTED_EVENTS"); self.assertEqual(calls, [])
    def test_does_not_interrupt_focus_but_will_when_urgent(self):
        a, r, calls = mk(); a.on_event(ev(1, 10, "focus"), 10); self.assertEqual(a.suggest(11)["status"], "HELD"); self.assertEqual(calls, []); self.assertEqual(a.suggest(12, urgent=True)["status"], "OK")
    def test_hourly_budget(self):
        a, r, calls = mk(max_per_hour=2); a.on_event(ev(1, 10, "comms"), 10); res = [a.suggest(20 + i)["status"] for i in range(4)]; self.assertEqual(res, ["OK", "OK", "HELD", "HELD"]); self.assertEqual(a.suggest(4000)["status"], "OK")
    def test_prompt_carries_redacted_text_and_wf13d_questions_and_provenance(self):
        a, r, calls = mk(); a.on_event(ev(1, 10, "comms", "reply to [EMAIL] about invoice"), 10); out = a.suggest(11)
        self.assertEqual(out["status"], "OK"); self.assertEqual(out["event_ids"], ["e1"]); self.assertIn("WHAT", calls[0][1]); self.assertEqual(out["questions"], a.questions()); self.assertEqual(calls[0][0], "muse-wonder-1.0")
    def test_unredacted_text_cannot_reach_the_model(self):
        a, r, calls = mk(); a.on_event(ev(1, 10, "comms", "send to jane@example.com"), 10)
        with self.assertRaises(AssertionError): a.suggest(11)
        self.assertEqual(calls, [])
    def test_questions_shrink_as_the_person_confirms_bits(self):
        st = State(30, 62); a, r, _ = mk(state=st); before = a.questions(); st.step({"bits": {"WHO": 1}}); after = a.questions(); self.assertNotIn("WHO", after); self.assertEqual(before[0], "WHO"); self.assertNotEqual(before, after)
    def test_voice_needs_audio_consent_and_is_redacted(self):
        a, r, _ = mk(); out = a.transcribe(b"pcm", lambda m, x: "call me at (312) 555-0199", 5); self.assertEqual(out["status"], "OK"); self.assertIn("[PHONE]", out["text"])
        r.revoke("alice", 6); self.assertEqual(a.transcribe(b"pcm", lambda m, x: "x", 7)["status"], "NO_CONSENT")
        with self.assertRaises(ValueError): a.transcribe(b"pcm", lambda m, x: "x", 7, model="whisper-large")
    def test_bm25_finds_the_right_document(self):
        docs = ["expense reimbursement policy and forms", "onboarding checklist for new engineers", "vpn setup guide for remote work"]; self.assertEqual(bm25("how do I submit an expense", docs, k=1), [0]); self.assertEqual(bm25("zzzz", docs), [])
if __name__ == "__main__": unittest.main()
