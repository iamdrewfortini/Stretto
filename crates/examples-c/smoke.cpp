// SPDX-License-Identifier: Apache-2.0
#include <cstdint>
#include <cstdio>
#include "wf13d_core.h"
#include "ant.h"
int main() {
    const uint32_t a = (31u << 13) | (63u << 7) | 127u;
    std::printf("word=%u\n", wf13d_word(a));
    uint64_t steps = 0, lock = 0; int32_t vx = 0, vy = 0; uint8_t g = 0;
    const uint8_t ok = ant_run(nullptr, 0, 104, 5, 2000000, &steps, &lock, &vx, &vy, &g);
    std::printf("ant ok=%u steps=%llu lock=%llu v=%d,%d guaranteed=%u\n", ok, static_cast<unsigned long long>(steps), static_cast<unsigned long long>(lock), vx, vy, g);
    return ok ? 0 : 1;
}
