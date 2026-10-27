# SPDX-License-Identifier: Apache-2.0
import math, unittest
from telemetry.store import Store, ingest_pve, maturity, dim

def INV(cpu, mem, nin):
    return {"data": {"resources": [
        {"type": "node", "id": "node/n1", "maxcpu": 24, "cpu": cpu, "mem": mem, "maxmem": 32 * 2 ** 30, "disk": 5, "maxdisk": 10},
        {"type": "node", "id": "node/n2", "maxcpu": 64, "cpu": cpu, "mem": mem, "maxmem": 128 * 2 ** 30, "disk": 5, "maxdisk": 10},
        {"type": "qemu", "id": "qemu/1", "status": "running", "maxcpu": 4, "cpu": cpu, "mem": mem // 8, "maxmem": 8 * 2 ** 30, "netin": nin, "netout": 0, "diskread": 0, "diskwrite": 0},
        {"type": "qemu", "id": "qemu/9", "status": "stopped", "template": 1, "maxcpu": 2, "cpu": 0, "mem": 0, "maxmem": 1, "netin": 0, "netout": 0}]}}
class Telemetry(unittest.TestCase):
    def test_dimension_coordinate_fixed_step(self): self.assertAlmostEqual(dim(100), math.log(100) / math.log(1.4)); self.assertEqual(dim(1), 0.0)
    def test_ingest_levels_units_and_skips_stopped(self):
        s = Store(); n = ingest_pve(s, INV(0.1, 2 ** 30, 1000), ts=0.0); units = {u for u, *_ in s.units()}
        self.assertIn("cluster", units); self.assertNotIn("qemu/9", units); self.assertGreater(n, 10)
        lv = {u: l for u, l, *_ in s.units()}; self.assertGreater(lv["cluster"], lv["node/n1"]); self.assertGreater(lv["node/n1"], lv["qemu/1"])
    def test_counter_rates(self):
        s = Store(); ingest_pve(s, INV(0.1, 2 ** 30, 1000), ts=0.0); ingest_pve(s, INV(0.1, 2 ** 30, 4000), ts=60.0); self.assertEqual(s.rate("qemu/1", "netin_total"), [(60.0, 50.0)])
    def test_maturity_phase_and_hours_needed(self):
        s = Store(); ingest_pve(s, INV(0.1, 2 ** 30, 0), ts=0.0); m = maturity(s, 3600)
        self.assertEqual(m["phase"], "OBSERVE"); self.assertEqual(m["hours_until_testable"]["daily"], 72.0); self.assertEqual(m["hours_until_testable"]["weekly"], 504.0)
        for h in range(1, 4 * 24): ingest_pve(s, INV(0.1, 2 ** 30, 0), ts=h * 3600.0)
        m2 = maturity(s, 3600); self.assertEqual(m2["phase"], "LEARN"); self.assertEqual(m2["hours_until_testable"]["daily"], 0.0); self.assertGreater(m2["hours_until_testable"]["weekly"], 0)
if __name__ == "__main__": unittest.main(verbosity=1)
