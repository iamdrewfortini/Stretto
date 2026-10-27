/* SPDX-License-Identifier: Apache-2.0 */
#ifndef METACOH_ANT_H
#define METACOH_ANT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Langton's ant run until its flip pattern locks. seed_xy: n (x,y) int32 pairs (may be NULL when n == 0).
 * Returns 1 if locked, 0 if `cap` steps passed without a lock. Any output pointer may be NULL. guaranteed = 1 when the frontier is also clean. */
uint8_t ant_run(const int32_t *seed_xy, size_t n, uint64_t period, size_t locks, uint64_t cap,
                uint64_t *steps_run, uint64_t *lock_step, int32_t *vx, int32_t *vy, uint8_t *guaranteed);
#ifdef __cplusplus
}
#endif
#endif
