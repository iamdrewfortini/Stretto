# SPDX-License-Identifier: Apache-2.0
import hashlib, os, time, unittest
from wf13d.bridge import analyze, pack
from wf13d.table import Table, build

DATA = os.path.join(os.path.dirname(__file__), "..", "src", "wf13d", "data")
class TableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.blob = open(os.path.join(DATA, "wf13d.tbl"), "rb").read(); cls.T = Table(cls.blob)
    def test_size_and_checksum_match_the_shipped_hash(self):
        self.assertEqual(len(self.blob), 1048576); self.assertEqual(hashlib.sha256(self.blob).hexdigest(), open(os.path.join(DATA, "wf13d.tbl.sha256")).read().strip())
    def test_lookup_equals_analyze_for_every_address(self):
        for a in range(1 << 18):
            if self.T.lookup(a) != analyze(a): self.fail(f"mismatch at address {a}")
    def test_shipped_file_is_reproducible(self): self.assertEqual(hashlib.sha256(build()).hexdigest(), hashlib.sha256(self.blob).hexdigest())
    def test_lookup_speed_is_reported(self):
        t = time.perf_counter(); [self.T.word(a) for a in range(1 << 18)]; w = (time.perf_counter() - t) / (1 << 18)
        t = time.perf_counter(); [self.T.lookup(a) for a in range(0, 1 << 18, 8)]; l = (time.perf_counter() - t) / (1 << 15); print(f"\nraw word read {w*1e9:.0f} ns, full decode {l*1e6:.1f} us")
        self.assertLess(w, 5e-6)
if __name__ == "__main__": unittest.main()
