# SPDX-License-Identifier: Apache-2.0
"""Environment-derived quality gates: guard margins come from the declared SLOs and the measured headroom, not from hand-set numbers.
margin(metric) = safety * (SLO - observed_p95) / SLO, floored at 0: with no headroom no degradation is allowed."""
import statistics

def p95(x): s = sorted(x); return s[min(len(s) - 1, int(0.95 * len(s)))]

def derive_guards(slo, series, safety=0.5):
    """slo: {metric: ceiling} for lower-is-better metrics, {metric: floor} for higher-is-better under key '>metric'. series: {metric: [values]}."""
    out = {}
    for m, lim in slo.items():
        if m.startswith(">"):                      # floor: headroom = (observed_p05 - floor) / floor
            name = m[1:]; x = sorted(series[name]); obs = x[int(0.05 * len(x))]; out[name] = round(max(0.0, safety * (obs - lim) / lim), 6)
        else:
            obs = p95(series[m]); out[m] = round(max(0.0, safety * (lim - obs) / lim), 6)
    return out

K8S_KNOBS = {      # applied only through the GitOps channel (platform config -> MR -> pipeline); restore = revert the MR
 "k8s.cpu_requests":  dict(cls="A", scope="guest", channel="gitops", obj=("cpu_throttle", "down"), guard=[("p99_latency_ms", .05)], apply="patch platform.yml: resources.requests.cpu={v}", restore="git revert (MR)"),
 "k8s.hpa_target":    dict(cls="A", scope="guest", channel="gitops", obj=("p99_latency_ms", "down"), guard=[("mem_pressure", .05)], apply="patch platform.yml: hpa.targetCPU={v}", restore="git revert (MR)"),
 "k8s.pdb_min":       dict(cls="B", scope="guest", channel="gitops", obj=("availability", "up"), guard=[("p99_latency_ms", .05)], apply="patch platform.yml: pdb.minAvailable={v}", restore="git revert (MR)"),
}
