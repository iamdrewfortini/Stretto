# SPDX-License-Identifier: Apache-2.0
import unittest
from handoff import *
from handoff.examples import ALL

class Graphs(unittest.TestCase):
    def test_examples_are_clean_and_acyclic(self):
        for name, f in ALL.items():
            p = f(); issues, final = replay(p); self.assertEqual(issues, [], name); self.assertEqual(gaps(p), []); d = dag(p); self.assertFalse(d["cycle"], name); self.assertEqual(len(d["order"]), len(p.steps))
    def test_the_issue_example_from_the_brief(self):
        p = ALL["garage-door gearbox"](); q = p.copy(); q.steps.pop(q.index("g4"))                       # the belt removal is missing
        g = gaps(q); self.assertTrue(any(x["fact"] == "belt_off" and x["kind"] == "missing_step" and x["needed_by"] == "g6" for x in g)); self.assertTrue(any("belt_off" in x["question"] for x in g))
    def test_out_of_order_is_distinguished_from_missing(self):
        p = ALL["server rack install"](); q = p.copy(); s = q.steps.pop(q.index("r2")); q.steps.append(s)       # rails mounted after the server
        self.assertTrue(any(x["kind"] == "out_of_order" and x["fact"] == "rails_on" for x in gaps(q)))
    def test_phantom_removal(self):
        p = Procedure([step("a", "remove belt", removes=["belt_on"])]); self.assertEqual(gaps(p)[0]["kind"], "phantom_removal"); self.assertEqual(close(p, lambda g: dict(initial=g["fact"]))["closed"], True)
    def test_circular_dependency_surfaces_as_a_precondition_gap(self):
        p = Procedure([step("a", "a", requires=["y"], adds=["x"]), step("b", "b", requires=["x"], adds=["y"])]); self.assertTrue(replay(p)[0])      # b makes y only after a needs it
    def test_removal_of_a_needed_step_in_the_middle_changes_the_dag_order(self):
        p = ALL["garage-door gearbox"](); d = dag(p); self.assertLess(d["order"].index("g4"), d["order"].index("g6")); self.assertLess(d["order"].index("g6"), d["order"].index("g8"))

class Determinism(unittest.TestCase):
    def test_dag_order_does_not_depend_on_the_interpreter_hash_seed(self):
        import os, subprocess, sys
        code = "from handoff.examples import ALL; from handoff import dag; print([dag(f())['order'] for f in ALL.values()])"; outs = set()
        for seed in ("0", "1", "2", "3"):
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=os.pathsep.join(sys.path))); self.assertEqual(r.returncode, 0, r.stderr[-300:]); outs.add(r.stdout)
        self.assertEqual(len(outs), 1)

class Audit(unittest.TestCase):
    def test_every_detectable_removal_is_flagged_for_all_three_procedures(self):
        for name, f in ALL.items():
            a = removal_audit(f()); self.assertEqual(a["flagged"], a["detectable"], name); self.assertEqual(a["undetectable"], [{"garage-door gearbox": "g0", "server rack install": "r0", "vehicle detailing": "d0"}[name]], name)
            print(f"\n{name}: {a['flagged']}/{a['detectable']} detectable removals flagged; undetectable (nothing depends on them): {a['undetectable']} -> {a['detectable_fraction']:.0%} of steps are checkable")
    def test_undetectable_steps_are_reported_not_hidden(self): self.assertLess(removal_audit(ALL["vehicle detailing"]())["detectable_fraction"], 1.0)

class Closing(unittest.TestCase):
    def oracle(self, original, removed_id):
        full = {s["id"]: s for s in original.steps}; order = [s["id"] for s in original.steps]
        def ask(gap):
            nxt = order[order.index(removed_id) + 1] if order.index(removed_id) + 1 < len(order) else None
            return dict(insert=full[removed_id], before=nxt)
        return ask
    def test_expert_closes_the_graph_with_one_question_per_gap(self):
        for name, f in ALL.items():
            orig = f()
            for s in orig.steps:
                q = orig.copy(); i = q.index(s["id"]); q.steps.pop(i)
                if not gaps(q): continue
                r = close(q, self.oracle(orig, s["id"])); self.assertTrue(r["closed"], (name, s["id"])); self.assertLessEqual(len(r["asked"]), 2); self.assertEqual([x["id"] for x in r["procedure"].steps], [x["id"] for x in orig.steps])
    def test_unanswerable_gap_leaves_the_graph_open_and_says_why(self):
        q = ALL["vehicle detailing"](); q.steps.pop(q.index("d4")); r = close(q, lambda g: None); self.assertFalse(r["closed"]); self.assertIn("could not answer", r["why"])
    def test_question_budget(self):
        q = ALL["vehicle detailing"](); q.steps.pop(q.index("d4")); r = close(q, lambda g: dict(initial="unrelated_fact"), max_questions=3); self.assertFalse(r["closed"]); self.assertEqual(len(r["asked"]), 3)

class Guidance(unittest.TestCase):
    def test_in_order_run_has_no_alerts_and_full_progress(self):
        p = ALL["server rack install"](); g = Guide(p); alerts = [a for s in p.steps for a in g.observe(s["id"])]; self.assertEqual(alerts, []); self.assertEqual(g.progress(), 1.0)
    def test_skipped_and_unmet_precondition_are_spoken(self):
        p = ALL["garage-door gearbox"](); g = Guide(p); g.observe("g1"); a = g.observe("g6"); kinds = {x["alert"] for x in a}; self.assertEqual(kinds, {"skipped", "precondition_unmet"})
        self.assertIn("g4", [s for x in a if x["alert"] == "skipped" for s in x["steps"]])
    def test_repeat_and_low_confidence(self):
        p = ALL["vehicle detailing"](); g = Guide(p); g.observe("d1"); self.assertEqual(g.observe("d1")[0]["alert"], "repeated"); self.assertEqual(g.observe("d3", confidence=0.2)[0]["alert"], "low_confidence")

class Scoring(unittest.TestCase):
    def test_recall_against_a_hand_written_key(self):
        key = [s["text"] for s in ALL["garage-door gearbox"]().steps]; extracted = [t.replace("Remove the drive belt", "Take off the belt") for t in key[:-3]] + ["Wipe the workbench"]
        m = match_steps(extracted, key); self.assertAlmostEqual(m["recall"], 9 / 13)          # 10 steps kept, 1 paraphrased too far for a lexical match (a semantic matcher would be needed)
        self.assertLess(m["precision"], 1.0)
        self.assertEqual(match_steps(key, key)["recall"], 1.0); self.assertEqual(match_steps([], key)["recall"], 0.0)
if __name__ == "__main__": unittest.main()
