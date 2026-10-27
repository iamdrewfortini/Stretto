/* SPDX-License-Identifier: Apache-2.0 */
#include <stdio.h>
#include <stdint.h>
#include "wf13d_core.h"
#include "ant.h"
int main(void) {
    uint32_t a = (31u << 13) | (63u << 7) | 127u;
    printf("word=%u\n", wf13d_word(a));
    uint64_t steps = 0, lock = 0; int32_t vx = 0, vy = 0; uint8_t g = 0;
    uint8_t ok = ant_run(NULL, 0, 104, 5, 2000000, &steps, &lock, &vx, &vy, &g);
    printf("ant ok=%u steps=%llu lock=%llu v=%d,%d guaranteed=%u\n", ok, (unsigned long long)steps, (unsigned long long)lock, vx, vy, g);
    return ok ? 0 : 1;
}
