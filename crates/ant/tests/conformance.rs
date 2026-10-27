// SPDX-License-Identifier: Apache-2.0
// Conformance against results produced by the Python reference (conformance/ant_golden.txt):
// each line: `seed x,y;x,y;... | LOCKED|NOT_LOCKED steps_run lock_step vx vy guaranteed`
use ant::run_until_locked;
const GOLDEN: &str = include_str!("../../../conformance/ant_golden.txt");

#[test] fn empty_grid_matches_the_literature_and_python() {
    let o = run_until_locked(&[], 104, 5, 2_000_000); assert!(o.locked && o.guaranteed); assert_eq!((o.steps_run, o.lock_step, o.vector), (10608, 10088, (-2, -2)));
}
#[test] fn every_golden_line_matches() {
    let (mut n, mut bad) = (0, Vec::new());
    for line in GOLDEN.lines().filter(|l| !l.trim().is_empty()) {
        let (a, b) = line.split_once('|').unwrap(); let seed: Vec<(i32, i32)> = a.trim().strip_prefix("seed").unwrap().trim().split(';').filter(|s| !s.is_empty())
            .map(|p| { let (x, y) = p.split_once(',').unwrap(); (x.trim().parse().unwrap(), y.trim().parse().unwrap()) }).collect();
        let f: Vec<&str> = b.split_whitespace().collect(); let o = run_until_locked(&seed, 104, 5, 400_000); n += 1;
        let want_locked = f[0] == "LOCKED"; let ok = o.locked == want_locked && (!want_locked || (o.steps_run == f[1].parse::<u64>().unwrap() && o.lock_step == f[2].parse::<u64>().unwrap()
            && o.vector == (f[3].parse().unwrap(), f[4].parse().unwrap()) && o.guaranteed == (f[5] == "1")));
        if !ok { bad.push((n, line.to_string(), format!("{:?}", o))); }
    }
    assert!(n >= 40 && bad.is_empty(), "{} lines, mismatches: {:?}", n, bad.iter().take(2).collect::<Vec<_>>());
}
#[test] fn not_locked_is_explicit() { let o = run_until_locked(&[], 104, 5, 3000); assert!(!o.locked && !o.guaranteed && o.steps_run == 3000); }
