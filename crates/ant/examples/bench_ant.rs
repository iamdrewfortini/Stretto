// SPDX-License-Identifier: Apache-2.0
use std::time::Instant;
const GOLDEN: &str = include_str!("../../../conformance/ant_golden.txt");
fn main() {
    let t = Instant::now(); let o = ant::run_until_locked(&[], 104, 5, 2_000_000); let e = t.elapsed();
    println!("rust ant: empty grid locked={} steps_run={} in {:.3} ms ({:.1} ns/step)", o.locked, o.steps_run, e.as_secs_f64() * 1e3, e.as_nanos() as f64 / o.steps_run as f64);
    let t = Instant::now(); let (mut steps, mut n) = (0u64, 0);
    for line in GOLDEN.lines().filter(|l| !l.trim().is_empty()) {
        let a = line.split_once('|').unwrap().0.trim().strip_prefix("seed").unwrap().trim();
        let seed: Vec<(i32, i32)> = a.split(';').filter(|s| !s.is_empty()).map(|p| { let (x, y) = p.split_once(',').unwrap(); (x.parse().unwrap(), y.parse().unwrap()) }).collect();
        let r = ant::run_until_locked(&seed, 104, 5, 400_000); steps += r.steps_run; n += 1;
    }
    let e = t.elapsed(); println!("rust ant: {} seeded cells, {} total steps in {:.3} ms ({:.1} ns/step)", n, steps, e.as_secs_f64() * 1e3, e.as_nanos() as f64 / steps as f64);
}
