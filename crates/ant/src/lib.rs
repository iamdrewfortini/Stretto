// SPDX-License-Identifier: Apache-2.0
//! Langton's ant until locked. Lock = the NET cell changes of `locks` consecutive periods are identical after translating to the ant, with the same non-zero displacement.
//! `guaranteed` also requires that no black cell lies ahead of the motif's footprint. Mirrors `coherence.swarm.langton_until_locked` exactly.
use std::collections::HashSet;
use std::hash::{BuildHasherDefault, Hasher};

/// Fast non-cryptographic hasher (FxHash-style) for small integer keys. The ant's inputs are its own coordinates, so hash-flooding is not a concern here.
#[derive(Default)] pub struct Fx(u64);
impl Hasher for Fx {
    #[inline] fn finish(&self) -> u64 { self.0 }
    #[inline] fn write(&mut self, bytes: &[u8]) { for &b in bytes { self.0 = (self.0.rotate_left(5) ^ b as u64).wrapping_mul(0x517c_c1b7_2722_0a95); } }
    #[inline] fn write_i32(&mut self, i: i32) { self.0 = (self.0.rotate_left(5) ^ (i as u32 as u64)).wrapping_mul(0x517c_c1b7_2722_0a95); }
}
type Set = HashSet<(i32, i32), BuildHasherDefault<Fx>>;

const DIRS: [(i32, i32); 4] = [(0, 1), (1, 0), (0, -1), (-1, 0)];
#[derive(Debug, Clone, PartialEq)]
pub struct Outcome { pub locked: bool, pub guaranteed: bool, pub steps_run: u64, pub lock_step: u64, pub vector: (i32, i32), pub black: usize }

pub fn run_until_locked(seed: &[(i32, i32)], period: u64, locks: usize, cap: u64) -> Outcome {
    let mut black: Set = Set::default(); black.extend(seed.iter().copied()); let (mut x, mut y, mut d) = (0i32, 0i32, 0usize); let mut step = 0u64;
    let mut cur: Set = Set::default(); let mut sigs: Vec<(u64, usize, Vec<(i32, i32)>, (i32, i32))> = Vec::new();
    while step < cap {
        if black.contains(&(x, y)) { d = (d + 3) % 4; black.remove(&(x, y)); } else { d = (d + 1) % 4; black.insert((x, y)); }
        if !cur.remove(&(x, y)) { cur.insert((x, y)); }
        x += DIRS[d].0; y += DIRS[d].1; step += 1;
        if step % period != 0 { continue; }
        let mut rel: Vec<(i32, i32)> = cur.iter().map(|&(cx, cy)| (cx - x, cy - y)).collect(); rel.sort_unstable(); cur.clear();
        sigs.push((step, d, rel, (x, y)));
        if sigs.len() < locks + 1 { continue; }
        let tail = &sigs[sigs.len() - (locks + 1)..];
        let same = tail.iter().all(|t| t.1 == tail[0].1 && t.2 == tail[0].2);
        let disp: Vec<(i32, i32)> = tail.windows(2).map(|w| (w[1].3 .0 - w[0].3 .0, w[1].3 .1 - w[0].3 .1)).collect();
        if same && disp.iter().all(|v| *v == disp[0]) && disp[0] != (0, 0) {
            let v = disp[0]; let n = ((v.0 * v.0 + v.1 * v.1) as f64).sqrt(); let (ux, uy) = (v.0 as f64 / n, v.1 as f64 / n);
            let reach = tail[locks].2.iter().map(|&(cx, cy)| cx as f64 * ux + cy as f64 * uy).fold(f64::NEG_INFINITY, f64::max);
            let reach = if tail[locks].2.is_empty() { 0.0 } else { reach };
            let ahead = black.iter().map(|&(bx, by)| (bx - x) as f64 * ux + (by - y) as f64 * uy).fold(f64::NEG_INFINITY, f64::max);
            return Outcome { locked: true, guaranteed: ahead <= reach + 1e-9, steps_run: step, lock_step: tail[0].0, vector: v, black: black.len() };
        }
    }
    Outcome { locked: false, guaranteed: false, steps_run: step, lock_step: 0, vector: (0, 0), black: black.len() }
}

/// C ABI: returns 1 if locked. Seed is `n` (x,y) pairs. Outputs through the pointers; any pointer may be null.
#[no_mangle] pub unsafe extern "C" fn ant_run(seed_xy: *const i32, n: usize, period: u64, locks: usize, cap: u64, steps_run: *mut u64, lock_step: *mut u64, vx: *mut i32, vy: *mut i32, guaranteed: *mut u8) -> u8 {
    let seed: Vec<(i32, i32)> = (0..n).map(|i| (*seed_xy.add(2 * i), *seed_xy.add(2 * i + 1))).collect(); let o = run_until_locked(&seed, period, locks, cap);
    if !steps_run.is_null() { *steps_run = o.steps_run; } if !lock_step.is_null() { *lock_step = o.lock_step; }
    if !vx.is_null() { *vx = o.vector.0; } if !vy.is_null() { *vy = o.vector.1; } if !guaranteed.is_null() { *guaranteed = o.guaranteed as u8; }
    o.locked as u8
}
