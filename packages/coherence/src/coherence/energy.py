# SPDX-License-Identifier: Apache-2.0
"""Energy measurement primitives. Read-only sources only: Linux RAPL counters (host), UPS watts, NVML GPU watts. No source -> None (NOT MEASURED), never an estimate."""
def rapl_delta_j(e0_uj, e1_uj, max_range_uj):
    """Joules between two RAPL energy_uj readings, handling counter wrap-around at max_energy_range_uj."""
    d = e1_uj - e0_uj
    if d < 0: d += max_range_uj
    return d / 1e6
def attribute(host_joules, cpu_seconds):
    """Split a host's measured joules over guests by their CPU-time share. Conserves the total exactly (sum of parts == host_joules)."""
    tot = sum(cpu_seconds.values())
    if tot <= 0: return {k: 0.0 for k in cpu_seconds}
    return {k: host_joules * v / tot for k, v in cpu_seconds.items()}
def joules_per_job(joules, verified_jobs): return None if joules is None or verified_jobs <= 0 else joules / verified_jobs
def edp(joules, seconds): return None if joules is None else joules * seconds           # energy-delay product: lower is better, penalizes slow AND hungry
def source_report(readings):
    """readings: {source: value|None}. Names which energy sources exist so a missing one is visible, not silent."""
    have = [k for k, v in readings.items() if v is not None]; return dict(measured=have, not_measured=[k for k, v in readings.items() if v is None])
