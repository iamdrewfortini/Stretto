/* SPDX-License-Identifier: Apache-2.0 */
#ifndef WF13D_CORE_H
#define WF13D_CORE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Packed WF-13D answer for an 18-bit address c(5)|t(6)|s(7); higher bits are ignored.
 * bits 0-9 ask-order permutation rank, 10-11 max_q, 12-13 where_res, 14-17 stops (S2,S3,S4,S6), 18-30 path mask (D01..D13). */
uint32_t wf13d_word(uint32_t address);
#ifdef __cplusplus
}
#endif
#endif
