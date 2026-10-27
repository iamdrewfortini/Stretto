// SPDX-License-Identifier: Apache-2.0
use std::time::Instant;
fn main() {
    let t = Instant::now(); let blob = wf13d_core::build_table(); let build = t.elapsed();
    let t = Instant::now(); let mut acc = 0u64; for r in 0..20u32 { for a in 0..(1u32 << 18) { acc = acc.wrapping_add(wf13d_core::word(a ^ (r & 1)) as u64); } } let per = t.elapsed().as_nanos() as f64 / (20.0 * 262144.0);
    println!("rust wf13d: build 262,144-entry table {:.2} ms ({} bytes); word() {:.1} ns/address (checksum {})", build.as_secs_f64() * 1e3, blob.len(), per, acc);
}
