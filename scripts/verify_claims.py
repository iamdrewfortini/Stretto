#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Claims register. Every quantitative claim in the docs carries a tag [C:id]; each id below is a check that can FAIL. This script runs them and writes docs/CLAIMS.md.
  python scripts/verify_claims.py              run all claims that need only Python
  python scripts/verify_claims.py --fast       skip the slow ones (exhaustive table, rollout simulation, installer round trip)
  python scripts/verify_claims.py --require-all  fail if any claim is skipped (needs cargo, gcc, python -m build)
  python scripts/verify_claims.py --write      rewrite docs/CLAIMS.md with the evidence
A claim is PASS (check ran and held), FAIL (check ran and did not hold), or SKIP (tool missing; never counted as proof)."""
import glob, hashlib, itertools, json, math, os, random, re, shutil, statistics, subprocess, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in glob.glob(os.path.join(ROOT, "packages", "*", "src")): sys.path.insert(0, p)
CL = []
def claim(id, text, slow=False, needs=()):
    def deco(fn): CL.append(dict(id=id, text=text, fn=fn, slow=slow, needs=needs)); return fn
    return deco
def sha(b): return hashlib.sha256(b).hexdigest()
def recorded(): return json.load(open(os.path.join(ROOT, "examples", "recorded_cluster.json")))

# ---------------------------------------------------------------- WF-13D
@claim("wf13d-exhaustive", "The packed WF-13D table decodes to the reference arithmetic at all 262,144 addresses.", slow=True)
def _():
    from wf13d.table import Table; from wf13d.bridge import analyze
    blob = open(os.path.join(ROOT, "packages/wf13d/src/wf13d/data/wf13d.tbl"), "rb").read(); T = Table(blob); bad = sum(T.lookup(a) != analyze(a) for a in range(1 << 18))
    assert bad == 0 and len(blob) == 1 << 20; return f"0 mismatches over {1 << 18} addresses; table is {len(blob)} bytes, sha256 {sha(blob)[:16]}"
@claim("wf13d-recorded-tool", "The arithmetic reproduces 10 recorded outputs of the live WF-13D tool exactly (recorded 2026-10-27; the tool itself is not part of this repository).")
def _():
    from wf13d.bridge import analyze, pack
    rec = json.load(open(os.path.join(ROOT, "conformance/wf13d_live_tool.json")))["outputs"]; n = 0
    for key, want in rec.items():
        c, t, s = (int(x) for x in key.split(".")); got = analyze(pack(c, t, s)); want = dict(want, path=want["path"].split())
        for k, v in want.items(): assert got[k] == v, (key, k, got[k], v)
        n += 1
    return f"{n} of {len(rec)} recorded addresses identical on every field"
@claim("loop-dimensions-13", "The WF-13D loop has exactly 13 dimensions D01..D13, so one 13-vector per side gives 13 + 13 = 26 numbers.", slow=True)
def _():
    from wf13d.bridge import analyze
    seen = set()
    for a in range(0, 1 << 18, 5): seen |= set(analyze(a)["path"])
    assert seen == {f"D{i:02d}" for i in range(1, 14)}, sorted(seen); return f"paths over the address space use exactly {len(seen)} distinct dimensions D01..D13"
# ---------------------------------------------------------------- ant
@claim("ant-empty-grid", "On an empty grid Langton's ant starts its highway at step 9,977 (period 104) and is locked and guaranteed after 10,608 steps with escape vector (-2,-2).")
def _():
    from coherence.swarm import langton, langton_until_locked
    r = langton_until_locked(); o = langton(12000)
    assert (r["status"], r["guaranteed"], r["steps_run"], r["lock_step"], r["vector"], r["period"]) == ("LOCKED", True, 10608, 10088, (-2, -2), 104); assert o["onset"] == 9977 and o["period"] == 104
    return f"onset {o['onset']}, locked after {r['steps_run']} steps (lock step {r['lock_step']}), vector {r['vector']}, direction {r['direction']}"
@claim("ant-seeded-cells", "All 40 address-seeded cells lock into a guaranteed highway; the step count varies per cell.")
def _():
    from coherence.swarm import langton_until_locked, seed_from_address
    res = [langton_until_locked(seed_from_address(f"{i}.62.080"), cap=400_000) for i in range(40)]; assert all(r["status"] == "LOCKED" and r["guaranteed"] for r in res)
    s = sorted(r["steps_run"] for r in res); return f"40 of 40 locked; steps_run min {s[0]}, median {s[20]}, max {s[-1]}"
@claim("ant-cap-is-explicit", "If the ant has not locked by the step cap, the result is NOT_LOCKED with no direction (never a guess).")
def _():
    from coherence.swarm import langton_until_locked
    r = langton_until_locked(cap=3000); assert (r["status"], r["guaranteed"], r["direction"]) == ("NOT_LOCKED", False, None); return f"cap 3000 -> {r['status']}"
# ---------------------------------------------------------------- distance from coherence
def _gaps():
    from coherence.metrics import balance_gap, intent_gap
    r = recorded(); cpu = [a / t for a, t in zip(r["allocated_vcpu"], r["threads"])]; ram = [a / t for a, t in zip(r["allocated_ram_gib"], r["ram_gib"])]
    return dict(speed=None, energy=None, balance=balance_gap({"cpu": cpu, "ram": ram}, r["cluster_commit"]), scale=None, intent=intent_gap(len(r["wf13d_known_bits"]))), cpu, ram
@claim("distance-lower-bound", "For the recorded cluster, D is at least 0.2297; it is a lower bound because speed, energy and scale are unmeasured.")
def _():
    from coherence.metrics import distance
    g, cpu, ram = _gaps(); d = distance(g); assert d["lower_bound"] and sorted(d["missing"]) == ["energy", "scale", "speed"] and abs(d["D"] - 0.2297) < 5e-4, d
    return f"D >= {d['D']} (lower bound); missing {sorted(d['missing'])}"
@claim("intent-dominates-D", "In that reading the intent gap is about 95% of D squared and the balance gap about 5%.")
def _():
    from coherence.metrics import distance
    d = distance(_gaps()[0]); tot = sum(d["contribution"].values()); si, sb = d["contribution"]["intent"] / tot, d["contribution"]["balance"] / tot; assert abs(si - 0.947) < 0.01 and abs(sb - 0.053) < 0.01
    return f"intent {si:.1%}, balance {sb:.1%} of D^2"
@claim("cpu-commit-imbalance", "On the recorded cluster the CPU commitment ratios are 0.58, 2.08 and 1.25 (Jain index 0.82), while memory commitment is balanced (Jain 0.99).")
def _():
    from coherence.metrics import jain
    g, cpu, ram = _gaps(); assert [round(x, 2) for x in cpu] == [0.58, 2.08, 1.25] and abs(jain(cpu) - 0.819) < 0.005 and abs(jain(ram) - 0.986) < 0.005
    return f"cpu {[round(x, 2) for x in cpu]} Jain {jain(cpu):.3f}; ram {[round(x, 2) for x in ram]} Jain {jain(ram):.3f}"
@claim("direction-follows-gradient", "The cell's direction asks the human first (largest drop in D per cost) and a descent along chosen actions lowers D.")
def _():
    from coherence.metrics import distance, direction
    g, _, _ = _gaps(); eff = {"ask-human": {"intent": -1 / 6}, "migrate": {"balance": -0.06}}; r = direction(g, eff, {"ask-human": 0.5, "migrate": 3.0}); assert r[0][0] == "ask-human"
    d0 = distance(g)["D"]; g2 = dict(g, intent=g["intent"] - 1 / 6); assert distance(g2)["D"] < d0; return f"top action {r[0][0]}; D {d0:.4f} -> {distance(g2)['D']:.4f} after one answered question"
# ---------------------------------------------------------------- routing
@claim("route-formulas-match-simulation", "Expected time, cost and success of racing three endpoints match a 100,000-trial simulation within 2%.")
def _():
    from metarouter.speed import TimedEndpoint, race_metrics
    eps = []
    for n, m, t, c, p in (("a", "muse-wonder-1.0", 1.0, 0.01, 0.5), ("b", "muse-spark-1.3", 4.0, 0.05, 0.8), ("c", "muse-spark-1.2", 9.0, 0.2, 0.95)):
        e = TimedEndpoint(n, m, "live", c, t); e.stats["t"] = [round(p * 1000), round((1 - p) * 1000)]; eps.append(e)
    Ec, Et, P = race_metrics(eps, "t"); rnd = random.Random(2); N = 100_000; st = sc = sp = 0.0
    for _ in range(N):
        ok = [rnd.random() < e.p("t") for e in eps]; T = min((e.t_eff() for e, o in zip(eps, ok) if o), default=max(e.t_eff() for e in eps)); st += T; sp += any(ok); sc += sum(e.cost * min(1, T / e.t_eff()) for e in eps)
    assert abs(st / N - Et) < 0.02 * Et and abs(sc / N - Ec) < 0.02 * Ec and abs(sp / N - P) < 0.01; return f"formula time {Et:.3f}s cost {Ec:.4f} p_ok {P:.4f}; simulated {st/N:.3f}s {sc/N:.4f} {sp/N:.4f}"
@claim("erlang-c-values", "The queueing delay matches the closed-form M/M/c values (1.0 s for one server at utilisation 0.5; 1/3 s for two servers at arrival rate 1, service rate 1).")
def _():
    from metarouter.speed import erlang_c_wait
    assert abs(erlang_c_wait(0.5, 1, 1) - 1.0) < 1e-12 and abs(erlang_c_wait(1, 1, 2) - 1 / 3) < 1e-12 and erlang_c_wait(1, 1, 1) == math.inf; return "Wq(0.5,1,1)=1.0, Wq(1,1,2)=0.3333, unstable queue -> inf"
@claim("meta-only-policy", "A router, an agent, an assistant and a fine-tuning job all refuse any model that is not an allowed Meta model.")
def _():
    from metarouter.policy import check_agent, CATALOG; from metarouter.router import Endpoint
    for m in ("gpt-5", "claude-opus", "grok-4", "chat-12g"): assert check_agent(dict(id="a", model=m)), m
    refused = 0
    for m in ("gpt-5", "grok-4"):
        try: Endpoint("x", m, "live", 0.1, roles={"coder"})
        except ValueError: refused += 1
    assert refused == 2 and all(v["provider"] in ("meta-api", "meta-local") for v in CATALOG.values()); return f"4 non-Meta/unproven models refused by check_agent; 2 refused at endpoint registration; {len(CATALOG)} catalogued models all Meta"
# ---------------------------------------------------------------- harness
@claim("rollout-gate-simulation", "In a simulator, a change with no effect is promoted at most 3 times in 100 and a real +8% effect at least 85 times in 100 (measured: 0 and 97 of 100).", slow=True)
def _():
    from harness.rollout import Simulator, Ledger, Rollout
    def promoted(eff, seed):
        sim = Simulator(seed, eff); return Rollout(sim, Ledger(), n=60).run("zfs.arc_max", "v", [f"g{i}" for i in range(12)]) == "PROMOTED"
    null = sum(promoted({}, s) for s in range(100)); real = sum(promoted({"zfs.arc_max": {"read_iops": 0.08}}, s) for s in range(100)); assert null <= 3 and real >= 85
    return f"no effect promoted {null}/100; +8% effect promoted {real}/100"
@claim("provenance-detects-tampering", "Altering a stored decision, its evidence, or the ledger is detected by the provenance verifier.")
def _():
    sys.path.insert(0, os.path.join(ROOT, "packages/harness/tests")); import test_optimizer as T
    from harness.optimizer import verify_provenance
    o = T.Provenance().build(); assert verify_provenance(o) == []; o.decisions[0]["chosen"]["value"] = 99; assert verify_provenance(o); return "clean run verifies; edited decision reported"
@claim("boundary-multisig", "The signed outer boundary needs two agent signatures and one human signature; edits without them fail closed.")
def _():
    try: from harness.signing import new_key, sign_with, make_verifier
    except ImportError: raise Skip("cryptography not installed")
    k = {n: new_key() for n in ("a1", "a2", "h1")}; auth = {"a1": ("agent", k["a1"][1]), "a2": ("agent", k["a2"][1]), "h1": ("human", k["h1"][1])}; v = make_verifier(auth); env = {"x": 1}
    sigs = lambda ns, e=env: {n: sign_with(e, k[n][0]) for n in ns}; assert v(env, sigs(["a1", "a2", "h1"]))[0] and not v(env, sigs(["a1", "a2"]))[0] and not v({"x": 2}, sigs(["a1", "a2", "h1"]))[0]
    return "2 agents + 1 human accepted; missing human rejected; edited envelope rejected"
# ---------------------------------------------------------------- people side
@claim("consent-default-deny", "Capture is denied by default, bounded in time, and a revocation takes effect on the very next frame.")
def _():
    from perception import ConsentRegistry, Source
    r = ConsentRegistry(); assert not r.allows("p", "screen", "assist", 0); r.grant("p", ["screen"], ["assist"], 100, 0); assert r.allows("p", "screen", "assist", 50) and not r.allows("p", "screen", "assist", 100)
    frames = iter([b"a", b"b", b"c", None]); clock = [0.0]; got = []
    for f in Source("screen", lambda: next(frames)).items(r, "p", "assist", lambda: clock[0]):
        got.append(f); clock[0] += 1
        if len(got) == 1: r.revoke("p", clock[0])
    assert got == [b"a"]; return "default deny; expiry at ttl; stream stopped after 1 frame once revoked"
@claim("no-raw-media-stored", "The event type has no field for raw media and a captured frame is never kept.")
def _():
    from perception import ConsentRegistry, EventStore, Event, ingest
    r = ConsentRegistry(); r.grant("p", ["screen"], ["assist"], 100, 0); s = EventStore(); raw = b"RAWPIXELS" * 50; ev = ingest(r, s, "p", b"k", "screen", "assist", raw, lambda f: {"activity": "focus", "text": "ok"}, 1)
    assert set(ev) == set(Event.FIELDS) and raw not in repr(s.events).encode(); return f"event fields {sorted(Event.FIELDS)}; raw bytes absent from the store"
@claim("redaction-patterns", "E-mail, phone, SSN-shape, IPv4, API-key shapes and Luhn-valid card numbers are redacted; non-card digit runs are not.")
def _():
    from perception import redact
    t, c = redact("jane@example.com (312) 555-0199 123-45-6789 192.0.2.7 sk-abcdefghijklmnop1234 card 4111 1111 1111 1111 order 1234 5678 9012 3456"); assert set(c) == {"EMAIL", "PHONE", "SSN", "IPV4", "API_KEY", "CARD"} and "1234 5678 9012 3456" in t; return f"redacted kinds {sorted(c)}; the non-Luhn number kept"
@claim("rollup-privacy", "Groups under 5 people are suppressed, one person's contribution is clipped, and the noise scale equals cap/epsilon (checked on 40,000 samples).")
def _():
    from humanflow import PersonalLedger, rollup, laplace
    def mk(n):
        out = []
        for i in range(n):
            L = PersonalLedger(f"p{i}"); [L.add(dict(t=t, activity=a, duration_s=0.0)) for t, a in ((0, "focus"), (3600, "wait"), (4200, "focus"))]; out.append(L.summary(f"p{i}"))
        return out
    r = rollup({"a": mk(4), "b": mk(5)}, k=5, seed=1); assert r["a"]["suppressed"] and not r["b"]["suppressed"]
    rnd = random.Random(5); xs = [laplace(1000.0, rnd) for _ in range(40_000)]; sd = statistics.pstdev(xs); assert abs(sd - 1000.0 * 2 ** 0.5) < 0.05 * 1000.0 * 2 ** 0.5; return f"4 contributors suppressed, 5 released; noise sd {sd:.0f} vs expected {1000*2**0.5:.0f}"
@claim("owner-only-ledger", "Only the person who owns a ledger can read its detail or summary.")
def _():
    from humanflow import PersonalLedger
    L = PersonalLedger("alice"); L.add(dict(t=0, activity="focus", duration_s=1.0)); n = 0
    for who in ("manager", "bob"):
        for fn in (L.detail, L.summary):
            try: fn(who)
            except PermissionError: n += 1
    assert n == 4; return "4 of 4 non-owner reads refused"
@claim("assistant-respects-focus-and-consent", "The assistant makes no model call without consent, holds suggestions during focus, and enforces an hourly budget.")
def _():
    from assistant import Assistant; from perception import ConsentRegistry
    r = ConsentRegistry(); r.grant("a", ["screen"], ["assist"], 10 ** 6, 0); calls = []; a = Assistant("a", r, lambda m, p: calls.append(1) or "ok", max_per_hour=2)
    ev = lambda i, act: dict(id=f"e{i}", t=i, activity=act, text="reading", source="screen", pseudonym="x"); a.on_event(ev(1, "focus"), 1); assert a.suggest(2)["status"] == "HELD" and not calls
    a.on_event(ev(2, "comms"), 2); s = [a.suggest(10 + i)["status"] for i in range(3)]; assert s == ["OK", "OK", "HELD"] and len(calls) == 2; r.revoke("a", 20); assert a.suggest(21)["status"] == "NO_CONSENTED_EVENTS"; return f"focus held; budget 2/hour -> {s}; revoked -> no events"
@claim("finetune-gate", "Fine-tuning data needs model-improvement consent from at least 5 people, and a job must use an open-weight Meta base model.")
def _():
    from finetune import build_dataset, job_spec; from perception import ConsentRegistry
    r = ConsentRegistry(); [r.grant(f"p{i}", ["screen"], ["model-improvement"], 10 ** 6, 0) for i in range(5)]
    fb = lambda i: dict(person=f"p{i}", source="screen", context="status update", suggestion="use the template", accepted=True, edited=None)
    rows4, m4 = build_dataset([fb(i) for i in range(4)], r, 1); rows5, m5 = build_dataset([fb(i) for i in range(5)], r, 1); assert not m4["released"] and m5["released"]; job_spec("muse-glimmer-30b", "fireworks", m5)
    for base in ("muse-spark-1.3", "gpt-5"):
        try: job_spec(base, "fireworks", m5); raise AssertionError(base)
        except ValueError: pass
    return "4 contributors blocked, 5 released; only the open-weight base accepted"
# ---------------------------------------------------------------- Handoff
@claim("handoff-removal-flagged", "On 3 synthetic procedures every removed step that anything depends on is flagged (100%); steps nothing depends on cannot be detected and are listed.")
def _():
    from handoff import removal_audit; from handoff.examples import ALL
    parts = []
    for name, f in ALL.items():
        a = removal_audit(f()); assert a["flagged"] == a["detectable"]; parts.append(f"{name}: {a['flagged']}/{a['detectable']} flagged, {len(a['undetectable'])} undetectable {a['undetectable']}")
    return "; ".join(parts)
@claim("handoff-closes-with-few-questions", "For every detectable removal an expert closes the graph with at most 2 questions and the original order is restored.")
def _():
    from handoff import gaps, close; from handoff.examples import ALL
    n = qmax = 0
    for f in ALL.values():
        orig = f(); order = [s["id"] for s in orig.steps]
        for s in orig.steps:
            q = orig.copy(); q.steps.pop(q.index(s["id"]))
            if not gaps(q): continue
            nxt = order[order.index(s["id"]) + 1] if order.index(s["id"]) + 1 < len(order) else None
            r = close(q, lambda g, s=s, nxt=nxt: dict(insert=s, before=nxt)); assert r["closed"] and [x["id"] for x in r["procedure"].steps] == order; qmax = max(qmax, len(r["asked"])); n += 1
    assert qmax <= 2; return f"{n} removals closed; at most {qmax} question(s) each"
@claim("handoff-guidance-alerts", "The trainee guide stays silent on a correct run and speaks up on skipped steps and unmet preconditions.")
def _():
    from handoff import Guide; from handoff.examples import gearbox
    p = gearbox(); g = Guide(p); assert [a for s in p.steps for a in g.observe(s["id"])] == [] and g.progress() == 1.0
    g2 = Guide(p); g2.observe("g1"); kinds = {a["alert"] for a in g2.observe("g6")}; assert kinds == {"skipped", "precondition_unmet"}; return "in-order run: 0 alerts; jumping to g6: skipped + precondition_unmet"
def _noise():
    return [("clean", dict(p_fact_drop=0.0, p_halluc=0.0)), ("default", dict()), ("heavy", dict(p_fact_drop=0.35, p_halluc=0.25)), ("extreme", dict(p_fact_drop=0.6, p_halluc=0.4)), ("none", dict(p_fact_drop=1.0, p_halluc=0.0))]
@claim("step-score-threshold-swing", "On the same extractions, a word-overlap step score reads recall 0.997 at threshold 0.2 but 0.608 at 0.5 while precision stays above 0.99: a hidden threshold can move the headline recall by more than 0.3.")
def _():
    from handoff.scoring import threshold_curve, sim_text; from handoff.simulate import dataset
    c = {t: (r, p) for t, r, p in threshold_curve(dataset(range(100, 140)), sim_text)}; assert c[0.2][0] >= 0.95 and c[0.5][0] <= 0.7 and min(c[0.2][1], c[0.5][1]) >= 0.99 and c[0.2][0] - c[0.5][0] > 0.3
    return "recall " + ", ".join(f"{t}: {r:.3f}" for t, (r, p) in sorted(c.items())) + f"; precision {c[0.2][1]:.3f}-{c[0.5][1]:.3f}"
@claim("step-score-booster-safe", "Adding the effect signal as a small boost to word overlap is never worse than words alone (within 0.002 F1) in all 5 simulated noise conditions, with optimal one-to-one assignment.")
def _():
    from handoff.scoring import step_scores, sim_text, DEFAULT_THRESHOLD; from handoff.simulate import dataset
    out = []
    for lab, kw in _noise():
        d = dataset(range(100, 140), **kw); rb, pb = step_scores(d); rw, pw = step_scores(d, thr=DEFAULT_THRESHOLD, sim_fn=sim_text); fb, fw = 2 * rb * pb / (rb + pb), 2 * rw * pw / (rw + pw); assert fb >= fw - 0.002, (lab, fb, fw); out.append(f"{lab} {fw:.3f}->{fb:.3f}")
    return "F1 words->boosted: " + "; ".join(out)
@claim("step-signal-agreement", "The agreement (Cohen's kappa) between the word signal and the effect signal falls strictly as inferred effects get noisier (about 0.69 clean to 0 with no effects), so it works as a health check on the extractor.")
def _():
    from handoff.scoring import agreement_kappa; from handoff.simulate import dataset
    ks = [(lab, statistics.fmean(agreement_kappa(e, k) for e, k, t, n in dataset(range(100, 130), **kw))) for lab, kw in _noise()]; assert all(a[1] > b[1] for a, b in zip(ks, ks[1:])) and abs(ks[-1][1]) < 1e-9
    return ", ".join(f"{l} {k:.3f}" for l, k in ks)
@claim("step-benchmark-saturated", "The synthetic step benchmark cannot tell the matchers apart (F1 spread under 0.02), so its scores above 0.99 are not evidence of real-world accuracy.")
def _():
    from handoff.scoring import discriminates, sim_text, boosted; from handoff.simulate import dataset
    ok, f = discriminates(dataset(range(100, 140)), {"words": sim_text, "boosted": boosted}, thr=0.1); assert not ok; return f"F1 words {f['words']:.3f}, boosted {f['boosted']:.3f}; spread {abs(f['words'] - f['boosted']):.4f}"
@claim("dependency-recovery-gap", "Dependency edges between steps are recovered at only about 0.75 on average (worst job 0.33), so graph recovery from an extractor is not claimed; step order is recovered well (Kendall tau about 0.98).")
def _():
    from handoff.scoring import job_report; from handoff.simulate import extract; from handoff.procedure import Procedure; from handoff.examples import ALL
    rep = []
    for name, f in ALL.items():
        for sd in range(100, 120): p = f(); ext, truth = extract(p, random.Random(f"{name}-{sd}")); rep.append(job_report(ext, p.steps, truth, Procedure(ext, p.initial, p.goal), p))
    dep = statistics.fmean(r["dependency_recall"] for r in rep); tau = statistics.fmean(r["order_tau"] for r in rep); lo = min(r["dependency_recall"] for r in rep); assert 0.5 <= dep <= 0.9 and lo < 0.5 and tau >= 0.95
    return f"dependency recall mean {dep:.3f}, min {lo:.3f}; order tau {tau:.3f} over {len(rep)} simulated jobs"
# ---------------------------------------------------------------- mirror / resonance
@claim("mirror-properties", "Mirror coherence is 1 for identical attention, 0 for disjoint attention, symmetric, and always within [0,1] (200 random pairs).")
def _():
    from coherence.mirror import mirror_coherence
    U = [1.0] * 13; sp = lambda i: [1.0 if k == i else 0.0 for k in range(13)]; assert abs(mirror_coherence(U, U) - 1) < 1e-12 and abs(mirror_coherence(sp(0), sp(12))) < 1e-9
    r = random.Random(1)
    for _ in range(200):
        a, b = [r.random() + 0.01 for _ in range(13)], [r.random() + 0.01 for _ in range(13)]; c = mirror_coherence(a, b); assert abs(c - mirror_coherence(b, a)) < 1e-12 and 0 <= c <= 1
    return "identical=1, disjoint=0, symmetric and bounded on 200 random pairs"
@claim("tesseract-counts", "The 4-cube has 16 vertices, 32 edges, 24 squares and 8 cubes (Euler characteristic 16-32+24-8 = 0); each vertex has 4 neighbours; 4 minus the level single-axis moves reach full coherence.")
def _():
    from coherence.mirror import hypercube_counts, hamming_neighbors, tesseract_state, AXES4
    c = hypercube_counts(4); assert c == {0: 16, 1: 32, 2: 24, 3: 8, 4: 1} and c[0] - c[1] + c[2] - c[3] == 0 and all(len(hamming_neighbors(v)) == 4 for v in range(16))
    for v in range(16):
        bits = tuple((v >> (3 - i)) & 1 for i in range(4)); steps = 0
        while tesseract_state(bits)["flips"]: ax = AXES4.index(tesseract_state(bits)["flips"][0]); bits = bits[:ax] + (1,) + bits[ax + 1:]; steps += 1
        assert steps == 4 - sum((v >> (3 - i)) & 1 for i in range(4))
    return f"face counts {c}; 16 vertices checked for shortest path to coherence"
@claim("beats-vanish-when-coherent", "The audible beat between the human and machine tones is exactly 0 Hz when their attention matches and grows as it diverges.")
def _():
    from resonate import beat_hz
    U = [1.0] * 13; s = lambda i: [1.0 if k == i else 0.0 for k in range(13)]; assert beat_hz(U, U) == 0.0 and beat_hz(s(4), s(5)) < beat_hz(s(4), s(9)); return f"beat(match)=0; beat(adjacent)={beat_hz(s(4), s(5)):.1f} Hz < beat(far)={beat_hz(s(4), s(9)):.1f} Hz"
@claim("modality-learning-is-personal", "Two simulated people converge to different best presentation formats, and a person without hearing is never given a tone.")
def _():
    from resonate import Profile
    def sim(truth, seed):
        p, rnd = Profile("x", seed), random.Random(seed)
        for _ in range(400): m = p.choose(); pr, sec = truth[m]; p.record(m, rnd.random() < pr, sec)
        return p
    A = {"number": (0.3, 12), "bar": (0.5, 6), "sentence": (0.6, 9), "analogy": (0.9, 5), "tone": (0.4, 4), "pulse": (0.3, 4)}; B = dict(A, analogy=(0.2, 15), number=(0.95, 3)); pa, pb = sim(A, 1), sim(B, 2); assert pa.best() == "analogy" and pb.best() == "number"
    assert all(pa.choose(can_hear=False, can_feel=False) not in ("tone", "pulse") for _ in range(100)); return f"person A best '{pa.best()}', person B best '{pb.best()}'"
@claim("keyboard-88-keys", "The 88-key keyboard is equal-tempered (A4 = 440 Hz, A0 = 27.5 Hz, C8 about 4186 Hz; every half step is the ratio 2^(1/12); every 12 keys double the frequency) and splits as 3 + 7 x 12 + 1: seven octaves for seven signal families plus 4 anchor keys.")
def _():
    from resonate.keyboard import key_freq, key_name, groups_of_12, encode, decode, FAMILIES, ANCHORS
    assert abs(key_freq(49) - 440) < 1e-9 and abs(key_freq(1) - 27.5) < 1e-9 and abs(key_freq(88) - 4186.0090448) < 1e-6 and all(abs(key_freq(n + 1) / key_freq(n) - 2 ** (1 / 12)) < 1e-12 for n in range(1, 88)) and all(abs(key_freq(n + 12) / key_freq(n) - 2) < 1e-12 for n in range(1, 77))
    enc = {encode(f, l) for f in FAMILIES for l in range(12)}; assert enc == set(range(4, 88)) and len(FAMILIES) == 7 and sorted(ANCHORS) == [1, 2, 3, 88] and [len(g) for g in groups_of_12()] == [12] * 7 + [4]
    assert all(decode(encode(f, l))["family"] == f for f in FAMILIES for l in range(12)); return f"A0 {key_freq(1):.2f} Hz, A4 {key_freq(49):.1f} Hz, C8 {key_freq(88):.3f} Hz; {len(enc)} family keys + {len(ANCHORS)} anchors = 88"
@claim("polyrhythm-geometric-clock", "A polyrhythm a:b repeats after lcm(a,b) pulses and its two regular polygons on the clock circle share exactly gcd(a,b) vertices, for six tested pairs.")
def _():
    from resonate.keyboard import polyrhythm, clock_points
    for a, b in ((3, 4), (2, 3), (4, 6), (5, 7), (6, 9), (12, 8)):
        p = polyrhythm(a, b); assert p["cycle"] == a * b // math.gcd(a, b) and len(p["shared"]) == math.gcd(a, b) and len(set(clock_points(a)) & set(clock_points(b))) == math.gcd(a, b)
    return "cycles " + ", ".join(f"{a}:{b}={polyrhythm(a, b)['cycle']}" for a, b in ((3, 4), (2, 3), (4, 6), (5, 7)))
@claim("tesseract-four-point-symmetry", "Four mutually equidistant vertices of the 4-cube are mapped onto each other in all 24 possible orders by the cube's 384 symmetries (stabilizer of size 24, orbit of 16 positions); together with their dual they make up the 8 even-weight vertices.")
def _():
    from coherence.symmetry import symmetries, COHERENT_FOUR, equidistant, dual, stabilizer, induced_permutations, orbit
    assert len(symmetries()) == 384 and equidistant(COHERENT_FOUR) and equidistant(dual(COHERENT_FOUR)); s = stabilizer(COHERENT_FOUR); o = orbit(COHERENT_FOUR)
    assert len(s) == 24 and len(induced_permutations(COHERENT_FOUR)) == 24 and len(o) * len(s) == 384 and set(COHERENT_FOUR) | set(dual(COHERENT_FOUR)) == {v for v in range(16) if bin(v).count("1") % 2 == 0}
    return f"{len(s)} stabilizing symmetries induce all {len(induced_permutations(COHERENT_FOUR))} orderings; orbit {len(o)} x stabilizer {len(s)} = 384"
@claim("word-keys-are-deterministic", "A word maps to the same key on every run and machine (sha256, not a salted hash), regardless of capitalisation.")
def _():
    code = "from resonate.keyboard import key_for_word; print([key_for_word(w) for w in ('coherence','Coherence','handoff')])"; outs = set()
    for seed in ("0", "1", "2", "3"):
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=os.pathsep.join(sys.path))); assert r.returncode == 0, r.stderr[-200:]; outs.add(r.stdout.strip())
    assert len(outs) == 1; return outs.pop()
@claim("gossip-converges-fast", "32 cells reach identical caches in 8 or fewer gossip rounds on average (log2 32 = 5); measured over 20 seeds.")
def _():
    from coherence.swarm import StreamCell, gossip_round, converged
    rs = []
    for seed in range(20):
        rnd = random.Random(seed); cells = [StreamCell(f"c{i}") for i in range(32)]; [c.publish_D(round(rnd.random(), 3), "N") for c in cells]; k = 0
        while not converged(cells) and k < 40: gossip_round(cells, rnd); k += 1
        rs.append(k)
    assert statistics.fmean(rs) <= 8; return f"rounds min {min(rs)}, mean {statistics.fmean(rs):.1f}, max {max(rs)} over 20 seeds"
@claim("aco-finds-optimum", "The ant-colony search finds the true shortest path on a test graph in at least 38 of 40 seeds.")
def _():
    from coherence.swarm import aco, shortest
    G = {"s": {"a": 2, "b": 5, "c": 9}, "a": {"b": 1, "d": 7}, "b": {"d": 3, "e": 6}, "c": {"e": 2}, "d": {"t": 4}, "e": {"t": 1, "d": 2}, "t": {}}; opt = shortest(G, "s", "t"); h = sum(abs(aco(G, "s", "t", seed=s)[1] - opt) < 1e-9 for s in range(40)); assert h >= 38; return f"optimal cost {opt}; found in {h} of 40 seeds"
# ---------------------------------------------------------------- native + packaging + governance
@claim("rust-conformance", "The Rust crates reproduce the Python table byte for byte and every golden ant line.", slow=True, needs=("cargo",))
def _():
    r = subprocess.run(["cargo", "test", "--release", "--locked", "--manifest-path", os.path.join(ROOT, "crates/Cargo.toml")], capture_output=True, text=True); assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    ok = sum(int(m) for m in re.findall(r"test result: ok\. (\d+) passed", r.stdout)); assert ok >= 7; return f"{ok} Rust tests passed"
@claim("rust-faster", "The Rust ports are at least 10x faster than Python for the WF-13D table build and at least 5x faster for the ant (measured here, ratios vary by machine).", slow=True, needs=("cargo",))
def _():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/bench_record.py"), "--print"], capture_output=True, text=True); assert r.returncode == 0, r.stderr[-500:]
    b = json.loads(r.stdout); assert b["table_speedup"] >= 10 and b["ant_speedup"] >= 5; return f"table {b['table_speedup']:.0f}x, ant {b['ant_speedup']:.0f}x on this machine"
@claim("c-abi-from-c-and-cpp", "A C program and a C++ program link the Rust libraries through the C headers and print the same values as the Python reference.", slow=True, needs=("cargo", "gcc", "g++"))
def _():
    r = subprocess.run(["bash", os.path.join(ROOT, "scripts/c_abi_smoke.sh")], capture_output=True, text=True); assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]; return r.stdout.strip().splitlines()[-1]
@claim("release-gates", "Licensing (Apache-2.0 text, SPDX headers, manifests, version consistency), package isolation and the public-safety scan all pass.")
def _():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/release_check.py")], capture_output=True, text=True); assert r.returncode == 0, r.stdout[-800:]; return r.stdout.strip().splitlines()[0]
@claim("installer-round-trip", "A bundle built from the committed tree installs offline into a clean prefix, passes `metacoh doctor`, and uninstalls leaving no files behind.", slow=True, needs=("cargo", "gcc"))
def _():
    r = subprocess.run(["bash", os.path.join(ROOT, "scripts/test_install.sh")], capture_output=True, text=True); assert r.returncode == 0, r.stdout[-1200:] + r.stderr[-800:]; return [l for l in r.stdout.splitlines() if l.startswith("INSTALL TEST")][-1]
@claim("figures-current", "Every figure in docs/figures is regenerated from the code and data and is byte-identical to the committed file.")
def _():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/make_figures.py"), "--check"], capture_output=True, text=True); assert r.returncode == 0, r.stdout[-600:] + r.stderr[-400:]; return r.stdout.strip().splitlines()[-1]

# ---------------------------------------------------------------- Humanflow
@claim("humanflow-fast-path-budget", "Common spoken commands are answered locally by the Humanflow voice core with p95 under 100 ms over 440 turns and no model call.")
def _():
    from runtime.bus import EventBus; from runtime.core import VoiceCore; from runtime.tools import Tools
    class NoModel:
        def complete(self, body): raise AssertionError("model called on the fast path")
    bus = EventBus(); core = VoiceCore(NoModel(), Tools(bus), bus)
    texts = ["hello", "log twenty five minutes of focus", "I was in meetings for 40 minutes", "start a focus timer", "how's my day",
             "what are my tasks", "add a task: record the demo video, about 30 minutes", "I spent 1.5 hours on email"] * 55
    ms = []
    for t in texts:
        t0 = time.perf_counter(); out = core.turn(t); ms.append((time.perf_counter() - t0) * 1000); assert out["path"] == "fast", t
    p50, p95 = statistics.median(ms), statistics.quantiles(ms, n=20)[18]; assert p95 < 100.0, p95
    return f"n={len(ms)} p50={p50:.3f} ms p95={p95:.3f} ms max={max(ms):.3f} ms; 0 model calls"
@claim("humanflow-gateway-boundary", "The Humanflow runtime gateway refuses all 7 out-of-boundary configurations: off-loopback or non-local start, non-https or non-allowlisted egress, and models outside the Meta registry.")
def _():
    from runtime.bus import EventBus; from runtime.gateway import Gateway, GatewayError, Upstream, serve; from runtime.registry import Registry
    reg = os.path.join(ROOT, "docs/spec/models.registry.json"); base = {"MODEL_API_KEY": "k", "EGRESS_ALLOWLIST": "api.meta.ai", "REGISTRY_PATH": reg}; refused = 0
    for env in ({**base, "RUNTIME_MODE": "local", "GATEWAY_BIND": "0.0.0.0:8787"}, {**base, "RUNTIME_MODE": "cloud", "GATEWAY_BIND": "127.0.0.1:8787"}):
        try: serve(env)
        except SystemExit: refused += 1
    for url in ("http://api.meta.ai/v1", "https://evil.example/v1", "https://api.meta.ai.evil.example/v1"):
        try: Upstream(url, "k", ["api.meta.ai"])
        except GatewayError: refused += 1
    g = Gateway(Registry.load(reg), None, EventBus())
    for m in ("gpt-4o", "muse-glimmer-30b"):
        try: g.complete({"model": m, "messages": [{"role": "user", "content": "x"}]})
        except GatewayError: refused += 1
    assert refused == 7, refused; return f"{refused} of 7 out-of-boundary configurations refused"

class Skip(Exception): pass
def main():
    fast, req, write = "--fast" in sys.argv, "--require-all" in sys.argv, "--write" in sys.argv; res = []
    for c in CL:
        miss = [t for t in c["needs"] if not shutil.which(t)]
        if miss: res.append((c, "SKIP", f"missing tool(s): {', '.join(miss)}")); continue
        if fast and c["slow"]: res.append((c, "SKIP", "slow (run without --fast)")); continue
        t0 = time.time()
        try: ev = c["fn"](); res.append((c, "PASS", f"{ev}"))
        except Skip as e: res.append((c, "SKIP", str(e)))
        except Exception as e: res.append((c, "FAIL", f"{type(e).__name__}: {str(e)[:300]}"))
        print(f"{res[-1][1]:4s} {c['id']:38s} {time.time() - t0:5.1f}s", flush=True)
    npass = sum(r[1] == "PASS" for r in res); nfail = sum(r[1] == "FAIL" for r in res); nskip = sum(r[1] == "SKIP" for r in res); print(f"\n{npass} pass, {nfail} fail, {nskip} skipped of {len(res)} claims")
    if write:
        refs = {}
        for f in glob.glob(os.path.join(ROOT, "docs", "*.md")) + [os.path.join(ROOT, "README.md")]:
            for cid in set(re.findall(r"\[C:([a-z0-9-]+)\]", open(f, encoding="utf-8").read())): refs.setdefault(cid, []).append(os.path.relpath(f, ROOT).replace(os.sep, "/"))
        lines = ["# Claims register", "", "Generated by `python scripts/verify_claims.py --write`. Every quantitative statement in the docs is tagged `[C:id]`; each id below is a check that can fail. **PASS** = the check ran and held on the machine that generated this file. **SKIP** = a required tool was missing (never counted as proof).", "",
                 "| id | claim | status | evidence | cited in |", "|---|---|---|---|---|"]
        for c, st, ev in res: lines.append(f"| `{c['id']}` | {c['text']} | **{st}** | {str(ev).replace('|', '/')} | {', '.join(refs.get(c['id'], [])) or '-'} |")
        open(os.path.join(ROOT, "docs", "CLAIMS.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    sys.exit(1 if nfail or (req and nskip) else 0)
if __name__ == "__main__": main()
