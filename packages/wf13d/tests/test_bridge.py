# SPDX-License-Identifier: Apache-2.0
import time, unittest
from wf13d.bridge import *

# Ground truth: outputs of the live wf13d MCP tool (wf13d_addr), 2026-10-27
TOOL = {
 "15.07.072": dict(c="FRONTIER", t="ID.CL.RV.MU.EP.PB", s="100100D", known=["WHO", "WHEN"], ask=["WHAT", "WHERE", "WHY", "HOW"], max_q=2, where_res="jurisdiction", path="D01 D02 D03 D04 D05 D06 D07 D08 D10 D12 D13", stops=[], out="ProblemStatement>QuestionRegister", ready=0.333),
 "00.00.000": dict(c="REPAIR", t="ID.CL.RV.SO.ER.PF", s="000000D", known=[], ask=["WHAT", "WHY", "WHO", "WHERE", "WHEN", "HOW"], max_q=2, where_res=None, path="D01 D02 D03 D04 D05 D08 D10", stops=[], out="ProblemStatement>FixRecord", ready=0),
 "31.63.127": dict(c="MOVEMENT", t="AR.CP.IR.MU.EP.PB", s="111111U", known=["WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW"], ask=[], max_q=1, where_res=None, path="D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11 D12 D13", stops=["S2", "S3", "S6"], out="ProblemStatement>PrincipleRecord", ready=1),
 "22.36.064": dict(c="MASTERY", t="AR.CL.RV.MU.ER.PF", s="100000D", known=["WHO"], ask=["WHAT", "WHY", "WHERE", "WHEN", "HOW"], max_q=2, where_res=None, path="D01 D02 D03 D04 D05 D06 D07 D08 D10 D11 D12 D13", stops=[], out="ProblemStatement>LearningRecord", ready=0.167),
 "08.45.003": dict(c="INCIDENT", t="AR.CL.IR.MU.ER.PB", s="000001U", known=["HOW"], ask=["WHEN", "WHERE", "WHO", "WHAT", "WHY"], max_q=1, where_res="jurisdiction", path="D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11", stops=["S2", "S4", "S6"], out="ProblemStatement>Postmortem", ready=0.167),
 "05.50.100": dict(c="TINKER", t="AR.CP.RV.SO.EP.PF", s="110010D", known=["WHO", "WHAT", "WHY"], ask=["HOW", "WHERE", "WHEN"], max_q=3, where_res=None, path="D01 D02 D03 D04 D05 D08 D10 D11", stops=[], out="ProblemStatement>ExperimentLog", ready=0.5),
 "29.62.020": dict(c="EXPLORATION", t="AR.CP.IR.MU.EP.PF", s="001010D", known=["WHERE", "WHY"], ask=["WHAT", "WHO", "HOW", "WHEN"], max_q=2, where_res=None, path="D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11", stops=["S2", "S3", "S6"], out="ProblemStatement>ExperimentSpec", ready=0.333),
 "12.09.005": dict(c="PROJECT", t="ID.CL.IR.SO.ER.PB", s="000010U", known=["WHY"], ask=["WHEN", "WHERE", "WHAT", "WHO", "HOW"], max_q=1, where_res="jurisdiction", path="D01 D02 D03 D04 D05 D09 D10", stops=["S2", "S4"], out="ProblemStatement>Decomposition", ready=0.167),
 "01.00.000": dict(c="SYMPTOM", t="ID.CL.RV.SO.ER.PF", s="000000D", known=[], ask=["WHAT", "WHY", "WHO", "WHERE", "WHEN", "HOW"], max_q=2, where_res=None, path="D01 D02 D03 D04 D05 D08 D10", stops=[], out="ProblemStatement", ready=0),
 "07.63.127": dict(c="DREAM", t="AR.CP.IR.MU.EP.PB", s="111111U", known=["WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW"], ask=[], max_q=1, where_res=None, path="D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11 D12 D13", stops=["S2", "S3"], out="ProblemStatement", ready=1),
}

def reference(c, t, s):
    """Independent, deliberately naive implementation straight from the prose spec (strings and lists, no masks)."""
    cb, tb, sb = format(c, "05b"), format(t, "06b"), format(s, "07b")
    dom, scope, mode, hor, dfn = (int(x) for x in cb); st, bn, rk, ac, ev, lo = (int(x) for x in tb)
    set_ = dict(zip(SUBS, (int(x) for x in sb[:6]))); U_ = int(sb[6]); gaps = [k for k in SUBS if not set_[k]]
    q = ["WHAT", "WHY", "WHO", "WHERE", "WHEN", "HOW"]
    for flag, who in ((bn, "HOW"), (ac, "WHO"), (lo, "WHERE"), (U_, "WHEN"), (dfn, "WHAT")):
        if flag: q = [who] + [x for x in q if x != who]
    ask = [x for x in q if not set_[x]]
    mq = 1 if U_ else (2 if len(gaps) > 3 else 3)
    wr = None
    if lo and not set_["WHERE"]: wr = {(0, 0): "site", (0, 1): "jurisdiction", (1, 0): "locale", (1, 1): "jurisdiction"}[(dom, scope)]
    p = [1, 2, 3, 10]
    if dfn or not set_["WHAT"]: p += [4, 5]
    if hor or ac: p += [6, 7]
    if ev or not set_["WHY"]: p += [8]
    if rk: p += [9]
    if st or bn: p += [11]
    if hor: p += [12, 13]
    stops = [x for x, on in (("S2", rk), ("S3", ev and rk), ("S4", U_ and len(gaps) >= 4), ("S6", scope and ac and rk)) if on]
    return dict(ask=ask, max_q=mq, where_res=wr, path=[f"D{n:02d}" for n in sorted(p)], stops=stops, ready=round((6 - len(gaps)) / 6, 3), known=[k for k in SUBS if set_[k]])

class Bridge(unittest.TestCase):
    def test_matches_live_tool_on_all_fixtures(self):
        for key, want in TOOL.items():
            c, t, s = (int(x) for x in key.split(".")); got = analyze(pack(c, t, s)); want = dict(want, path=want["path"].split())
            for k, v in want.items(): self.assertEqual(got[k], v, (key, k))
            self.assertEqual(got["key"], key)
    def test_equals_independent_reference_on_all_262144_addresses(self):
        for a in range(1 << 18):
            c, t, s = unpack(a); g, r = analyze(a), reference(c, t, s)
            if not (g["ask"] == r["ask"] and g["max_q"] == r["max_q"] and g["where_res"] == r["where_res"] and g["path"] == r["path"] and g["stops"] == r["stops"] and g["ready"] == r["ready"] and g["known"] == r["known"]):
                self.fail(f"mismatch at {c}.{t}.{s}")
    def test_pack_unpack_roundtrip_exhaustive(self):
        self.assertTrue(all(pack(*unpack(a)) == a for a in range(1 << 18)))
    def test_invariants(self):
        for a in range(0, 1 << 18, 7):
            v = analyze(a)
            self.assertEqual(len(v["ask"]) + len(v["known"]), 6); self.assertTrue(set(v["ask"]).isdisjoint(v["known"])); self.assertIn(v["max_q"], (1, 2, 3))
            self.assertTrue({"D01", "D02", "D03", "D10"} <= set(v["path"])); self.assertEqual(v["path"], sorted(v["path"]))
    def test_speed(self):
        analyze.cache_clear(); t0 = time.perf_counter(); [analyze(a) for a in range(1 << 18)]; cold = (time.perf_counter() - t0) / (1 << 18)
        t0 = time.perf_counter(); [analyze(a) for a in range(1 << 18)]; warm = (time.perf_counter() - t0) / (1 << 18)
        print(f"\nanalyze: cold {cold*1e6:.2f} us/addr, cached {warm*1e6:.3f} us/addr"); self.assertLess(warm, cold)
        t0 = time.perf_counter(); [pack(*unpack(a)) for a in range(1 << 18)]; print(f"pack+unpack: {(time.perf_counter()-t0)/(1<<18)*1e9:.0f} ns")
class Steps(unittest.TestCase):
    def test_bits_only_from_human_and_retraction(self):
        st = State(30, 60); st.step({"bits": {"WHAT": 1}}); self.assertEqual(st.view()["known"], ["WHAT"])
        with self.assertRaises(PermissionError): st.step({"bits": {"WHO": 1}}, source="agent")
        st.step({"bits": {"WHAT": 0}}); self.assertEqual(st.view()["known"], []); self.assertIn(("RETRACT", "WHAT"), st.log)
    def test_idk_counts_as_assumption_and_set(self):
        st = State(30, 60); st.step({"bits": {"WHY": "idk"}}); self.assertEqual(st.A, 1); self.assertNotIn("WHY", st.view()["ask"])
    def test_ready_reaches_one_and_line(self):
        st = State(31, 63, 0); st.step({"bits": {n: 1 for n in SUBS}, "tempo": 1}); self.assertEqual(st.view()["ready"], 1); self.assertIn("stops=S2,S3,S6", st.line())
    def test_unknown_bit_rejected(self):
        with self.assertRaises(ValueError): State().step({"bits": {"WHEN2": 1}})
if __name__ == "__main__": unittest.main(verbosity=1)
