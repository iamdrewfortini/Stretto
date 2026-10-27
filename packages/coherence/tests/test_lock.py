# SPDX-License-Identifier: Apache-2.0
import unittest
from coherence.swarm import langton_until_locked, seed_from_address

class AntLock(unittest.TestCase):
    def test_empty_grid_runs_as_long_as_needed_then_stops_locked_and_guaranteed(self):
        r = langton_until_locked(); self.assertEqual(r["status"], "LOCKED"); self.assertTrue(r["guaranteed"]); self.assertEqual(r["period"], 104); self.assertEqual(sorted(map(abs, r["vector"])), [2, 2])
        self.assertTrue(9977 < r["lock_step"] < r["steps_run"] <= 10_700, r)            # literature: highway begins at step 9977; lock needs 5 further full periods
    def test_lock_is_independently_verified_by_running_three_more_periods(self):
        r = langton_until_locked(); r2 = langton_until_locked(locks=8); self.assertEqual(r2["status"], "LOCKED"); self.assertEqual(r["vector"], r2["vector"]); self.assertGreater(r2["steps_run"], r["steps_run"])
    def test_seeded_cells_all_lock_or_say_not_locked(self):
        res = [langton_until_locked(seed_from_address(f"{i}.62.080"), cap=400_000) for i in range(40)]
        self.assertTrue(all(r["status"] in ("LOCKED", "NOT_LOCKED") for r in res)); locked = [r for r in res if r["status"] == "LOCKED"]; self.assertGreaterEqual(len(locked), 38)
        self.assertTrue(all(r["guaranteed"] for r in locked)); print("\nlocked:", len(locked), "of 40; steps_run min/median/max", sorted(r["steps_run"] for r in locked)[0], sorted(r["steps_run"] for r in locked)[len(locked) // 2], max(r["steps_run"] for r in locked))
    def test_cap_gives_an_explicit_not_locked(self):
        r = langton_until_locked(cap=3000); self.assertEqual(r["status"], "NOT_LOCKED"); self.assertFalse(r["guaranteed"]); self.assertIsNone(r["direction"]); self.assertEqual(r["steps_run"], 3000)
if __name__ == "__main__": unittest.main()
