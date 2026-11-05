# SPDX-License-Identifier: Apache-2.0
"""Meta-model coaching over MEASURED findings. The model may phrase and prioritise; it may not create facts.

What goes to Meta: app names, site domains, durations and Stretto's own findings for ONE day. Never titles, URLs or screenshots.
What comes back is checked before anyone sees it: an action must cite a real finding id, any number above 5 must exist in the
facts, medical or mental-health advice is dropped, and invisible characters are stripped. Whatever fails is counted and shown."""
import hashlib
import json
import re
import time

from . import meta

ZERO_WIDTH = re.compile("[​-‏‪-‮⁠-⁤﻿]")
MEDICAL = re.compile(r"\b(diagnos\w*|medicat\w*|therapy|therapist|depress\w*|anxiety|adhd|disorder|clinical|prescri\w*|symptom\w*|mental health)\b", re.I)
SYSTEM = ("You are Stretto's efficiency coach. You receive MEASURED facts about one person's computer day as JSON. "
          "Use only those facts. Do not invent numbers, apps, sites or findings. Do not give medical or mental-health advice. "
          "Reply with JSON only, shaped exactly: {\"headline\": string (max 120 chars), \"actions\": [{\"finding\": \"f0\", \"title\": string (max 80), "
          "\"how\": string (max 280, one concrete change)}]}. Each action must cite one finding id from the facts. At most 4 actions, biggest loss first.")


def facts(day):
    """The only thing sent to Meta. Aggregates and names; no titles, no URLs."""
    sm = day["summary"]
    fs = []
    for i, f in enumerate(day["findings"][:8]):
        fs.append(dict(id=f"f{i}", kind=f["kind"], places=f["where"][:6], minutes=max(1, round(f["seconds"] / 60)),
                       times=f.get("runs") or f.get("visits") or 1))
    total = max(sm["total_s"], 1)
    return dict(date=day["date"], active_minutes=round(sm["total_s"] / 60), focus_minutes=round(sm["focus_s"] / 60),
                distraction_minutes=round(sm["distraction_s"] / 60), idle_minutes=round(sm["idle_s"] / 60), switches=sm["switches"],
                lost_minutes=round(day["loss_s"] / 60), tightness_percent=max(0, round(100 * (1 - day["loss_s"] / total))),
                top_places=[dict(name=n, minutes=round(s / 60)) for n, s in sm["by_app"][:8]], findings=fs,
                estimated_sources=[s["src"] for s in day.get("sources", []) if s.get("estimated")])


def messages(f):
    return [dict(role="system", content=SYSTEM), dict(role="user", content="FACTS:\n" + json.dumps(f, sort_keys=True))]


def _numbers(text):
    return {int(n) for n in re.findall(r"\d+", text)}


def validate(raw, f):
    """Returns (result, dropped counts). Never raises on model output."""
    dropped = dict(malformed=0, unknown_finding=0, invented_number=0, blocked_topic=0, sanitized=0)
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    a, b = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[a:b + 1]) if a >= 0 and b > a else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        dropped["malformed"] = 1
        return dict(headline="", actions=[]), dropped
    allowed = _numbers(json.dumps(f)) | set(range(6))
    ids = {x["id"] for x in f["findings"]}

    def clean(s, n):
        s = str(s)
        c = ZERO_WIDTH.sub("", s)
        if c != s:
            dropped["sanitized"] += 1
        return c.strip()[:n]

    def ok(s):
        if MEDICAL.search(s):
            dropped["blocked_topic"] += 1
            return False
        if not _numbers(s) <= allowed:
            dropped["invented_number"] += 1
            return False
        return True

    head = clean(data.get("headline", ""), 120)
    head = head if head and ok(head) else ""
    actions = []
    for act in (data.get("actions") or [])[:6]:
        if not isinstance(act, dict):
            dropped["malformed"] += 1
            continue
        if act.get("finding") not in ids:
            dropped["unknown_finding"] += 1
            continue
        t, how = clean(act.get("title", ""), 80), clean(act.get("how", ""), 280)
        if t and how and ok(t) and ok(how):
            actions.append(dict(finding=act["finding"], title=t, how=how))
    return dict(headline=head, actions=actions[:4]), dropped


def generate(store, day, device, budget_usd, refresh=False):
    f = facts(day)
    sha = hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:20]
    if not refresh:
        hit = store.q("SELECT result FROM insight_cache WHERE date=? AND device=? AND facts_sha=?", (day["date"], device, sha))
        if hit:
            return dict(json.loads(hit[0]["result"]), cached=True)
    call = meta.chat(store, "insights", messages(f), budget_usd, max_tokens=1200)
    result, dropped = validate(call["text"], f)
    out = dict(date=day["date"], basis="inferred", headline=result["headline"], actions=result["actions"], dropped=dropped,
               model=call["model"], mode=call["mode"], call_id=call["call_id"], cost_usd=call["cost_usd"], tokens=call["tokens"],
               facts_sha=sha, cached=False)
    store.x("INSERT OR REPLACE INTO insight_cache(date,device,facts_sha,result,ts) VALUES(?,?,?,?,?)", (day["date"], device, sha, json.dumps(out), time.time()))
    return out
