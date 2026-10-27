# SPDX-License-Identifier: Apache-2.0
import unittest
from perception import *

KEY = b"device-local-key"
class Consent(unittest.TestCase):
    def test_default_deny_and_exact_scope(self):
        r = ConsentRegistry(); self.assertFalse(r.allows("p1", "screen", "assist", 0))
        r.grant("p1", ["screen"], ["assist"], 100, now=0); self.assertTrue(r.allows("p1", "screen", "assist", 50))
        self.assertFalse(r.allows("p1", "camera", "assist", 50)); self.assertFalse(r.allows("p1", "screen", "team-analytics", 50)); self.assertFalse(r.allows("p2", "screen", "assist", 50))
    def test_expiry_and_revocation(self):
        r = ConsentRegistry(); r.grant("p1", ["screen"], ["assist"], 100, now=0); self.assertFalse(r.allows("p1", "screen", "assist", 100))
        r.grant("p1", ["screen"], ["assist"], 100, now=200); self.assertTrue(r.allows("p1", "screen", "assist", 250)); r.revoke("p1", 260); self.assertFalse(r.allows("p1", "screen", "assist", 261))
    def test_rejects_unknown_scope_and_unlimited_consent(self):
        r = ConsentRegistry()
        with self.assertRaises(ValueError): r.grant("p", ["retina"], ["assist"], 10, 0)
        with self.assertRaises(ValueError): r.grant("p", ["screen"], ["assist"], 0, 0)
    def test_history_is_tamper_evident(self):
        r = ConsentRegistry(); r.grant("p1", ["screen"], ["assist"], 100, 0); r.revoke("p1", 5); self.assertTrue(r.chain.verify()); r.chain.rows[0]["purposes"] = ["model-improvement"]; self.assertFalse(r.chain.verify())

class Redaction(unittest.TestCase):
    def test_patterns(self):
        t, c = redact("mail me at jane.doe@example.com or call (312) 555-0199, key sk-abcdefghijklmnop1234, ssn 123-45-6789 from 192.0.2.7")
        for tag in ("[EMAIL]", "[PHONE]", "[API_KEY]", "[SSN]", "[IPV4]"): self.assertIn(tag, t)
        self.assertEqual(scan(t), {}); self.assertEqual(set(c), {"EMAIL", "PHONE", "API_KEY", "SSN", "IPV4"})
    def test_card_needs_luhn(self):
        self.assertIn("[CARD]", redact("card 4111 1111 1111 1111 ok")[0]); self.assertNotIn("[CARD]", redact("order 1234 5678 9012 3456")[0]); self.assertTrue(luhn("4111111111111111")); self.assertFalse(luhn("4111111111111112"))

class Sampling(unittest.TestCase):
    def test_rate_bounds(self):
        s = AdaptiveSampler(1.0, 30.0, 0.2); got = [t for t in [i * 0.1 for i in range(1200)] if s.should_capture(t, 0.9)]
        self.assertTrue(all(b - a >= 1.0 - 1e-9 for a, b in zip(got, got[1:])))                       # never faster than min interval even if the scene never stops changing
        s2 = AdaptiveSampler(1.0, 30.0, 0.2); quiet = [t for t in [i * 0.5 for i in range(600)] if s2.should_capture(t, 0.0)]; self.assertTrue(all(b - a <= 30.5 for a, b in zip(quiet, quiet[1:])))   # never idle longer than max
        self.assertGreaterEqual(len(quiet), 9)

class Pipeline(unittest.TestCase):
    def setUp(self): self.r = ConsentRegistry(); self.r.grant("p1", ["screen"], ["assist"], 1000, 0); self.store = EventStore()
    def test_no_consent_no_event_and_model_never_sees_the_frame(self):
        seen = []; ev = ingest(self.r, self.store, "p2", KEY, "screen", "assist", b"PIXELS", lambda f: seen.append(f) or {"text": "x"}, 5)
        self.assertIsNone(ev); self.assertEqual(seen, []); self.assertEqual(self.store.events, [])
    def test_event_is_redacted_pseudonymous_and_has_no_media(self):
        raw = b"\x89PNG-raw-pixels"; ev = ingest(self.r, self.store, "p1", KEY, "screen", "assist", raw, lambda f: {"activity": "focus", "text": "editing report for jane@example.com"}, 10, app="editor", duration_s=4)
        self.assertNotIn("p1", ev["pseudonym"]); self.assertIn("[EMAIL]", ev["text"]); self.assertEqual(set(ev), set(Event.FIELDS))
        self.assertFalse(any(raw in (v if isinstance(v, bytes) else repr(v).encode()) for v in ev.values())); self.assertTrue(self.store.chain.verify())
    def test_pseudonym_depends_on_the_device_key(self): self.assertNotEqual(pseudonym("p1", b"k1"), pseudonym("p1", b"k2")); self.assertEqual(pseudonym("p1", b"k1"), pseudonym("p1", b"k1"))
    def test_revocation_stops_a_running_stream_on_the_next_frame(self):
        frames = iter([b"a", b"b", b"c", b"d", None]); clock = [0.0]; src = Source("screen", lambda: next(frames)); got = []
        for item in src.items(self.r, "p1", "assist", lambda: clock[0]):
            got.append(item); clock[0] += 1
            if len(got) == 2: self.r.revoke("p1", clock[0])
        self.assertEqual(got, [b"a", b"b"])
if __name__ == "__main__": unittest.main()
