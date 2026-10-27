# SPDX-License-Identifier: Apache-2.0
import json, unittest
from finetune import build_dataset, job_spec
from perception import ConsentRegistry

def fb(i, **kw): return dict(dict(person=f"p{i}", source="screen", context="drafting the weekly status update", suggestion="Use the template in the shared drive.", accepted=True, edited=None), **kw)
def reg(n, purposes=("assist", "model-improvement")):
    r = ConsentRegistry(); [r.grant(f"p{i}", ["screen"], list(purposes), 10 ** 6, 0) for i in range(n)]; return r
class Data(unittest.TestCase):
    def test_only_consented_accepted_and_clean_examples_survive(self):
        r = reg(6, ("assist",)); r.grant("p0", ["screen"], ["assist", "model-improvement"], 10 ** 6, 0)
        rows, m = build_dataset([fb(0)], r, 5); self.assertEqual(rows, []); self.assertFalse(m["released"])                                 # one contributor is below the minimum
        r2 = reg(6); fbs = [fb(i) for i in range(5)] + [fb(5, accepted=False), fb(0, context="mail jane@example.com")]
        rows, m = build_dataset(fbs, r2, 5); self.assertTrue(m["released"]); self.assertEqual(m["examples"], 6); self.assertEqual(m["dropped"]["rejected_by_person"], 1)
        self.assertTrue(all("@" not in json.loads(x)["prompt"] for x in rows))                                                              # redacted, not dropped: the email became [EMAIL]
    def test_no_consent_means_excluded(self):
        r = reg(6, ("assist",)); rows, m = build_dataset([fb(i) for i in range(6)], r, 5); self.assertEqual(rows, []); self.assertEqual(m["dropped"]["no_consent"], 6)
    def test_manifest_hash_is_stable(self):
        r = reg(6); a = build_dataset([fb(i) for i in range(6)], r, 5)[1]["sha256"]; b = build_dataset([fb(i) for i in range(6)], r, 5)[1]["sha256"]; self.assertEqual(a, b); self.assertEqual(len(a), 64)
class Jobs(unittest.TestCase):
    def good(self): return build_dataset([fb(i) for i in range(6)], reg(6), 5)[1]
    def test_valid_job_is_a_spec_not_a_submission(self): j = job_spec("muse-glimmer-30b", "fireworks", self.good()); self.assertFalse(j["submitted"]); self.assertEqual(j["method"], "lora")
    def test_base_model_must_be_open_weight_meta(self):
        for bad in ("muse-spark-1.3", "gpt-5", "llama-x"):
            with self.assertRaises(ValueError): job_spec(bad, "fireworks", self.good())
    def test_provider_and_dataset_gates(self):
        with self.assertRaises(ValueError): job_spec("muse-glimmer-30b", "someplace", self.good())
        with self.assertRaises(ValueError): job_spec("muse-glimmer-30b", "modal", build_dataset([fb(0)], reg(6), 5)[1])
if __name__ == "__main__": unittest.main()
