// SPDX-License-Identifier: Apache-2.0
// Conformance: the Rust implementation must reproduce the shipped Python-generated table (1,048,576 bytes) bit for bit, for every one of the 2^18 addresses.
use wf13d_core::{word, wf13d_word};
const TABLE: &[u8] = include_bytes!("../../../packages/wf13d/src/wf13d/data/wf13d.tbl");

#[test] fn table_is_the_right_size() { assert_eq!(TABLE.len(), 4 << 18); }
#[test] fn every_address_matches_the_python_table() {
    let mut bad = 0u32; let mut first = None;
    for a in 0..(1u32 << 18) {
        let w = u32::from_le_bytes([TABLE[4 * a as usize], TABLE[4 * a as usize + 1], TABLE[4 * a as usize + 2], TABLE[4 * a as usize + 3]]);
        if word(a) != w { bad += 1; if first.is_none() { first = Some((a, word(a), w)); } }
    }
    assert_eq!(bad, 0, "first mismatch (address, rust, python): {:?}", first);
}
#[test] fn c_abi_agrees_and_masks_the_address() { assert_eq!(wf13d_word(31 << 13 | 63 << 7 | 127), word(31 << 13 | 63 << 7 | 127)); assert_eq!(wf13d_word(0x4_0000), word(0)); }
#[test] fn build_table_reproduces_the_file() { #[cfg(feature = "std")] assert_eq!(wf13d_core::build_table(), TABLE); }
