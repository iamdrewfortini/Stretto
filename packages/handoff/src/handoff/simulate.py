# SPDX-License-Identifier: Apache-2.0
"""A SIMULATED extractor, for testing the scorer only: it paraphrases step wording, drops some steps, and infers effects with noise. Its noise rates are assumptions, not measurements of any real model."""
import random
from .procedure import Procedure, step
from . import examples

SYN = {"Remove": "Take off", "Unplug": "Disconnect", "Unbolt": "Undo the bolts on", "Release": "Free", "Grease": "Lubricate", "Inspect": "Check", "Close": "Shut", "Refit": "Put back", "Replace": "Put back on",
       "Reconnect": "Plug back in", "Photograph": "Snap a picture of", "Take": "Grab", "Confirm": "Verify", "Mount": "Fit", "Unbox": "Open", "Slide": "Push", "Connect": "Attach", "Boot": "Power up",
       "Install": "Set up", "Register": "Log", "Rinse": "Wash down", "Foam": "Lather", "Dry": "Towel off", "Polish": "Buff", "Apply": "Put on", "Clean": "Wipe", "Dress": "Treat", "Clay": "Use clay on", "Final": "Last"}
def paraphrase(text):
    w = text.split(" "); return " ".join(SYN.get(w[0], w[0]).split(" ") + w[1:])
def extract(proc, rng, p_drop=0.1, p_fact_drop=0.15, p_halluc=0.10, p_swap=0.05, wording="paraphrase"):
    """Returns (extracted_steps, truth{key_index: extracted_index}). Wording is 'same' or 'paraphrase'; effects are copied with noise."""
    vocab = sorted({f for s in proc.steps for f in s["requires"] + s["adds"] + s["removes"]}); out, truth = [], {}
    for i, s in enumerate(proc.steps):
        if rng.random() < p_drop: continue
        keep = lambda fs: [f for f in fs if rng.random() >= p_fact_drop]
        e = step(f"x{len(out)}", paraphrase(s["text"]) if wording == "paraphrase" else s["text"], keep(s["requires"]), keep(s["adds"]), keep(s["removes"]))
        if rng.random() < p_halluc: e["adds"].append(rng.choice(vocab))
        truth[i] = len(out); out.append(e)
    for j in range(len(out) - 1):
        if rng.random() < p_swap: out[j], out[j + 1] = out[j + 1], out[j]; truth = {k: (j + 1 if v == j else j if v == j + 1 else v) for k, v in truth.items()}
    return out, truth
def dataset(seeds, procs=None, **kw):
    """[(extracted_steps, key_steps, truth)] over the three synthetic procedures."""
    data = []
    for name, f in (procs or examples.ALL).items():
        for sd in seeds: p = f(); rng = random.Random(f"{name}-{sd}"); ext, truth = extract(p, rng, **kw); data.append((ext, p.steps, truth, name))
    return data
