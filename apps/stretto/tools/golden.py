#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Re-derive every golden dataset in stretto/golden/ from a fixed synthetic input, through the real modules.
  python3 tools/golden.py          rewrite the golden files
  python3 tools/golden.py --check  fail (exit 1) if any file differs from a fresh derivation
Golden means: same input, same numbers, byte-identical — a silent change anywhere in the chain fails loudly."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stretto import analyze, challenges, coach, embedder, honeycomb, lattice, predict, segment  # noqa: E402

T0 = 1_700_000_000
BLOCKS = [dict(app="Code", title="x", domain="", category="Build", seconds=600, start=T0, end=T0 + 600),
          dict(app="slack", title="y", domain="", category="Communication", seconds=300, start=T0 + 600, end=T0 + 900),
          dict(app="Code", title="x", domain="", category="Build", seconds=900, start=T0 + 900, end=T0 + 1800),
          dict(app="slack", title="y", domain="", category="Communication", seconds=120, start=T0 + 1800, end=T0 + 1920),
          dict(app="Code", title="x", domain="", category="Build", seconds=600, start=T0 + 1920, end=T0 + 2520)]
FACTS = dict(date="2026-11-04", active_minutes=400, focus_minutes=240, distraction_minutes=60, idle_minutes=60,
             switches=40, lost_minutes=30, tightness_percent=92, top_places=[dict(name="code", minutes=200)],
             findings=[dict(id="f0", kind="detour", places=["slack"], minutes=14, times=1)], estimated_sources=[])


def day():
    seg = [dict(b, key="") for b in BLOCKS]
    found, loss = analyze.findings([dict(b) for b in BLOCKS])
    return dict(date="2026-11-04", simulated=False, summary=analyze.summary([dict(b) for b in BLOCKS]),
                transitions=analyze.transitions([dict(b) for b in BLOCKS]), findings=found, loss_s=loss, blocks=seg)


def datasets():
    d = day()
    vec = honeycomb.vector(FACTS)
    return {
        "transitions": d["transitions"],
        "findings": [dict(kind=f["kind"], where=f["where"], seconds=f["seconds"]) for f in d["findings"]],
        "day_vector": dict(vector=vec, cell=list(honeycomb.cell(vec)), signature=honeycomb.signature(FACTS)),
        "embedding": dict(text="focus detour slack", dims=embedder.DIMS,
                          first8=embedder.dense("focus detour slack", ["focus", "detour", "slack"])[:8]),
        "challenges": challenges.group([day(), dict(day(), date="2026-11-03")]),
        "coach_ramp": coach.plan(dict(best_window=dict(start_hour=9, end_hour=12, avg_focus_s=3600)), 40, 200),
        "predict_next": predict.next_places(d["transitions"], "code"),
        "philosophy": lattice.PRINCIPLES,
    }


def main():
    check = "--check" in sys.argv
    out_dir = os.path.join(os.path.dirname(__file__), "..", "stretto", "golden")
    bad = []
    for name, data in datasets().items():
        text = json.dumps(data, indent=1, sort_keys=True, default=str) + "\n"
        path = os.path.join(out_dir, name + ".json")
        if check:
            if not os.path.isfile(path) or open(path, encoding="utf-8").read() != text:
                bad.append(name)
        else:
            open(path, "w", encoding="utf-8").write(text)
            print("golden:", name)
    if bad:
        print("STALE golden datasets:", ", ".join(bad), "— run: python3 tools/golden.py")
        return 1
    print("golden datasets re-derived byte-identical" if check else "done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
