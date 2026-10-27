# SPDX-License-Identifier: Apache-2.0
"""End-to-end on SYNTHETIC people only: consent -> capture -> redaction -> personal ledger -> assistant -> department roll-up -> fine-tuning gate; and a micro cell steered by D."""
import unittest
from perception import ConsentRegistry, EventStore, ingest
from humanflow import PersonalLedger, rollup
from assistant import Assistant
from finetune import build_dataset, job_spec
from wf13d.bridge import State
from coherence.metrics import distance, direction

class Hive(unittest.TestCase):
    def test_people_to_department_view_to_training_gate(self):
        reg, store, leds = ConsentRegistry(), EventStore(), {}
        for i in range(6): reg.grant(f"p{i}", ["screen"], ["assist", "team-analytics", "model-improvement"], 10 ** 6, 0); leds[f"p{i}"] = PersonalLedger(f"p{i}")
        reg.grant("outsider", ["screen"], ["assist"], 10 ** 6, 0)
        script = [(0, "focus", "writing spec"), (600, "wait", "waiting for review from legal"), (1500, "search", "looking for expense policy"), (1800, "focus", "writing spec")]
        for i in range(6):
            for t, act, text in script:
                ev = ingest(reg, store, f"p{i}", b"k%d" % i, "screen", "assist", b"RAW", lambda f, a=act, x=text: {"activity": a, "text": x + f" ping alice{i}@example.com"}, t)
                leds[f"p{i}"].add(dict(ev, failed_search=(act == "search")))
        self.assertEqual(len(store.events), 24); self.assertTrue(all("@" not in e["text"] for e in store.events)); self.assertTrue(store.chain.verify())
        sums = [leds[f"p{i}"].summary(f"p{i}") for i in range(6)]; view = rollup({"eng": sums, "tiny": sums[:2]}, k=5, epsilon=5.0, seed=1)
        self.assertFalse(view["eng"]["suppressed"]); self.assertTrue(view["tiny"]["suppressed"]); self.assertNotIn("p0", repr(view))
        with self.assertRaises(PermissionError): leds["p0"].summary("manager")
        a = Assistant("p0", reg, lambda m, p: "Ask legal for the status; the policy lives in the HR space."); [a.on_event(e, 2000) for e in store.events if e["pseudonym"]]
        fb = [dict(person=f"p{i}", source="screen", context="waiting for review from legal", suggestion="Ping the reviewer.", accepted=True, edited=None) for i in range(6)]
        rows, manifest = build_dataset(fb, reg, 2000); self.assertTrue(manifest["released"]); self.assertFalse(job_spec("muse-glimmer-30b", "fireworks", manifest)["submitted"])
    def test_a_cell_follows_the_gradient_of_D(self):
        st = State(30, 62); st.step({"bits": {"WHAT": 1, "WHY": 1, "HOW": 1}}); gaps = {"speed": None, "energy": None, "balance": 0.12, "scale": None, "intent": 1 - len(st.view()["known"]) / 6}
        d0 = distance(gaps)["D"]; self.assertTrue(distance(gaps)["lower_bound"]); r = direction(gaps, {"ask-human": {"intent": -1 / 6}, "migrate": {"balance": -0.06}}, {"ask-human": 0.5, "migrate": 3.0}); self.assertEqual(r[0][0], "ask-human")
        gaps["intent"] -= 1 / 6; self.assertLess(distance(gaps)["D"], d0)
if __name__ == "__main__": unittest.main()
