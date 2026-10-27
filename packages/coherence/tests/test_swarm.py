# SPDX-License-Identifier: Apache-2.0
import math, random, time, unittest
from coherence.swarm import *
from coherence.metrics import distance, direction, AXES

class Ant(unittest.TestCase):
    def test_empty_grid_highway_after_about_10000_steps(self):
        r = langton(12000); self.assertEqual(r["period"], 104); self.assertTrue(9900 <= r["onset"] <= 10100, r["onset"])       # literature: highway begins ~step 9977
        self.assertEqual(sorted(map(abs, r["vector"])), [2, 2]); print("\nlangton(12000): onset", r["onset"], "vector", r["vector"], "direction", escape_direction(r["vector"]))
    def test_at_exactly_10000_steps_the_highway_is_not_yet_confirmable_but_is_with_a_short_window(self):
        r = langton(10000); self.assertEqual(r["onset"], None)                       # only 23 steps into the highway at step 10,000 (onset 9977)
        r2 = langton(10000, extra=400); self.assertIsNotNone(r2["vector"]); self.assertEqual(sorted(map(abs, r2["vector"])), [2, 2]); self.assertEqual(r2["onset"], 9977)
    def test_deterministic_and_seed_dependent(self):
        a = langton(2000, seed_from_address("30.62.080")); b = langton(2000, seed_from_address("30.62.080")); c = langton(2000, seed_from_address("30.62.081")); self.assertEqual(a, b); self.assertNotEqual(a["end"], c["end"])
    def test_no_highway_is_reported_as_none_not_guessed(self):
        r = langton(500); self.assertIsNone(r["vector"]); self.assertIsNone(escape_direction(r["vector"]))
    def test_highway_rate_over_cell_addresses_is_measured(self):
        found = 0; dirs = {}
        for i in range(40):
            r = langton(10000, seed_from_address(f"{i}.62.080"), extra=400); found += r["vector"] is not None
            if r["vector"]: dirs[escape_direction(r["vector"])] = dirs.get(escape_direction(r["vector"]), 0) + 1
        print("\nhighway within 10,000 steps for", found, "of 40 seeded cells; directions", dirs)
        self.assertGreater(found, 0)

class Colony(unittest.TestCase):
    G = {"s": {"a": 2, "b": 5, "c": 9}, "a": {"b": 1, "d": 7}, "b": {"d": 3, "e": 6}, "c": {"e": 2}, "d": {"t": 4}, "e": {"t": 1, "d": 2}, "t": {}}
    def test_finds_optimal_path_across_seeds(self):
        opt = shortest(self.G, "s", "t"); hits = sum(abs(aco(self.G, "s", "t", seed=s)[1] - opt) < 1e-9 for s in range(40)); self.assertEqual(opt, 10.0); print("\nACO optimal in", hits, "of 40 seeds"); self.assertGreaterEqual(hits / 40, 0.95)
    def test_never_returns_a_path_that_is_not_in_the_graph(self):
        path, cost = aco(self.G, "s", "t", seed=3); self.assertEqual(sum(self.G[a][b] for a, b in zip(path, path[1:])), cost)
    def test_unreachable_returns_none(self): self.assertEqual(aco({"s": {"a": 1}, "a": {}, "t": {}}, "s", "t")[0], None)

class Stream(unittest.TestCase):
    def test_bounded_ring_drops_oldest_and_counts(self):
        c = StreamCell("a", ring=8); [c.publish_D(0.5, "x") for _ in range(20)]; self.assertEqual(len(c.out), 8); self.assertEqual(c.dropped, 12); self.assertEqual(c.out[-1]["seq"], 20)
    def test_gossip_converges_in_log_rounds(self):
        rnd = random.Random(1); cells = [StreamCell(f"c{i}") for i in range(32)]
        for c in cells: c.publish_D(round(rnd.random(), 3), "N")
        rounds = 0
        while not converged(cells) and rounds < 40: gossip_round(cells, rnd); rounds += 1
        print("\n32 cells converged in", rounds, "gossip rounds (log2 32 = 5)"); self.assertTrue(converged(cells)); self.assertLessEqual(rounds, 15)
    def test_latest_value_wins_after_update(self):
        rnd = random.Random(2); cells = [StreamCell(f"c{i}") for i in range(8)]; [c.publish_D(0.9, "N") for c in cells]
        for _ in range(10): gossip_round(cells, rnd)
        cells[3].publish_D(0.1, "S")
        for _ in range(12): gossip_round(cells, rnd)
        self.assertTrue(all(c.cache.d["D:c3"][2]["D"] == 0.1 for c in cells))
    def test_cached_model_answer_serves_other_cells_without_a_second_call(self):
        rnd = random.Random(3); cells = [StreamCell(f"c{i}") for i in range(6)]; cells[0].remember_answer("muse-wonder-1.0", "classify: disk latency spike", "io-bound")
        for _ in range(10): gossip_round(cells, rnd)
        self.assertEqual(cells[5].lookup_answer("muse-wonder-1.0", "classify: disk latency spike"), "io-bound"); self.assertIsNone(cells[5].lookup_answer("muse-spark-1.3", "classify: disk latency spike"))
    def test_stream_update_cost_and_throughput_are_measured(self):
        c = StreamCell("a"); gaps = {k: 0.1 for k in AXES}; eff = {"x": {"speed": -0.1}}; N = 20000; t0 = time.perf_counter()
        for _ in range(N): d = distance(gaps)["D"]; r = direction(gaps, eff, {"x": 1.0}); c.publish_D(d, r[0][0] if r else None)
        dt = time.perf_counter() - t0; print(f"\ncompute D + direction + publish: {dt/N*1e6:.1f} us/update, {N/dt:,.0f} updates/s per cell (single thread)"); self.assertGreater(N / dt, 2000)
if __name__ == "__main__": unittest.main(verbosity=1)
