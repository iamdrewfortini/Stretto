// SPDX-License-Identifier: Apache-2.0
//! WF-13D bridge arithmetic. An address is `c(5) | t(6) | s(7)` packed into 18 bits. `word(a)` returns the same 32-bit packed answer as the Python
//! `wf13d.table` (bits 0-9 ask-order permutation rank, 10-11 max_q, 12-13 where_res, 14-17 stops, 18-30 path mask). No allocation, no branches on data beyond the rules.
#![no_std]
#[cfg(feature = "std")]
extern crate std;

const WHAT: u32 = 32; const WHERE: u32 = 16; const WHY: u32 = 4; const U: u32 = 1;           // sub-question bits used directly (the others are handled via the ask-order indices below)
const DOMAIN: u32 = 16; const SCOPE: u32 = 8; const HORIZON: u32 = 2; const DEF: u32 = 1;
const AR: u32 = 32; const CP: u32 = 16; const IR: u32 = 8; const MU: u32 = 4; const EP: u32 = 2; const PB: u32 = 1;
/// Indices into (WHO, WHAT, WHERE, WHEN, WHY, HOW).
const IWHO: u8 = 0; const IWHAT: u8 = 1; const IWHERE: u8 = 2; const IWHEN: u8 = 3; const IWHY: u8 = 4; const IHOW: u8 = 5;

#[inline] fn to_front(order: &mut [u8; 6], who: u8) {
    let pos = order.iter().position(|&x| x == who).unwrap(); let mut i = pos; while i > 0 { order[i] = order[i - 1]; i -= 1; } order[0] = who;
}
/// Lexicographic rank (0..719) of a permutation of 0..5: the Lehmer code.
#[inline] fn rank(p: &[u8; 6]) -> u32 {
    const F: [u32; 6] = [120, 24, 6, 2, 1, 1]; let mut r = 0u32;
    for i in 0..6 { let mut smaller = 0u32; for j in (i + 1)..6 { if p[j] < p[i] { smaller += 1; } } r += smaller * F[i]; }
    r
}
#[inline] pub fn unpack(a: u32) -> (u32, u32, u32) { ((a >> 13) & 31, (a >> 7) & 63, a & 127) }

/// The packed 32-bit answer for address `a` (0 <= a < 2^18).
pub fn word(a: u32) -> u32 {
    let (c, t, s) = unpack(a);
    let mut order: [u8; 6] = [IWHAT, IWHY, IWHO, IWHERE, IWHEN, IHOW];                         // baseline WHAT WHY WHO WHERE WHEN HOW
    if t & CP != 0 { to_front(&mut order, IHOW); }
    if t & MU != 0 { to_front(&mut order, IWHO); }
    if t & PB != 0 { to_front(&mut order, IWHERE); }
    if s & U != 0 { to_front(&mut order, IWHEN); }
    if c & DEF != 0 { to_front(&mut order, IWHAT); }
    let gaps = 6 - (s >> 1).count_ones();
    let max_q = if s & U != 0 { 1 } else if gaps > 3 { 2 } else { 3 };
    let wr = if t & PB != 0 && s & WHERE == 0 { if c & SCOPE != 0 { 2 } else if c & DOMAIN == 0 { 1 } else { 3 } } else { 0 };
    let ir = t & IR != 0;
    let mut stops = 0u32;
    if ir { stops |= 1; }                                           // S2
    if t & EP != 0 && ir { stops |= 2; }                            // S3
    if s & U != 0 && gaps >= 4 { stops |= 4; }                      // S4
    if c & SCOPE != 0 && t & MU != 0 && ir { stops |= 8; }          // S6
    let far = c & HORIZON != 0; let mut path = 0b11u32 | 0b100;     // D01 D02 D03
    path |= 1 << 9;                                                 // D10
    if c & DEF != 0 || s & WHAT == 0 { path |= 0b11 << 3; }         // D04 D05
    if far || t & MU != 0 { path |= 0b11 << 5; }                    // D06 D07
    if t & EP != 0 || s & WHY == 0 { path |= 1 << 7; }              // D08
    if ir { path |= 1 << 8; }                                       // D09
    if t & AR != 0 || t & CP != 0 { path |= 1 << 10; }              // D11
    if far { path |= 0b11 << 11; }                                  // D12 D13
    rank(&order) | (max_q << 10) | (wr << 12) | (stops << 14) | (path << 18)
}
#[inline] pub fn ready_count(a: u32) -> u32 { ((a & 127) >> 1).count_ones() }

/// C ABI for C/C++, Swift, Kotlin/JNI, or any FFI: `uint32_t wf13d_word(uint32_t address)`.
#[no_mangle] pub extern "C" fn wf13d_word(address: u32) -> u32 { word(address & 0x3FFFF) }

#[cfg(feature = "std")]
pub fn build_table() -> std::vec::Vec<u8> {
    let mut v = std::vec::Vec::with_capacity(4 << 18); for a in 0..(1u32 << 18) { v.extend_from_slice(&word(a).to_le_bytes()); } v
}
