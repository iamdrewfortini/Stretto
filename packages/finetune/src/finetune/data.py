# SPDX-License-Identifier: Apache-2.0
"""Consent-gated fine-tuning data and job specs. Nothing is trained or uploaded here; this module only decides what MAY be used and validates the job description.
Training examples come only from suggestions the person accepted or edited, from people who granted the `model-improvement` purpose, after a second redaction scan."""
import hashlib, json
from metarouter.policy import CATALOG
from perception.redact import redact, scan

PROVIDERS = ("fireworks", "modal", "baseten")
def build_dataset(feedback, registry, now, min_people=5):
    """feedback: list of dict(person, source, context, suggestion, accepted, edited). Returns (jsonl_lines, manifest)."""
    rows, people, dropped = [], set(), {"no_consent": 0, "rejected_by_person": 0, "pii_after_redaction": 0}
    for f in feedback:
        if not registry.allows(f["person"], f["source"], "model-improvement", now): dropped["no_consent"] += 1; continue
        if not f["accepted"] and not f.get("edited"): dropped["rejected_by_person"] += 1; continue
        ctx, _ = redact(f["context"]); out, _ = redact(f.get("edited") or f["suggestion"])
        if scan(ctx) or scan(out): dropped["pii_after_redaction"] += 1; continue
        rows.append(json.dumps({"prompt": ctx, "completion": out}, sort_keys=True)); people.add(f["person"])
    ok = len(people) >= min_people
    manifest = dict(examples=len(rows) if ok else 0, contributors=len(people), min_people=min_people, released=ok, dropped=dropped, consent_purpose="model-improvement", pii_scan_pass=True,
                    sha256=hashlib.sha256("\n".join(rows).encode()).hexdigest() if ok else None)
    return (rows if ok else []), manifest
def job_spec(base_model, provider, manifest, method="lora", rank=16, epochs=2):
    """Validate a fine-tuning job. Base model must be an open-weight Meta model; the dataset must be released, consented and PII-scanned."""
    m = CATALOG.get(base_model); P = []
    if m is None or m["provider"] != "meta-local": P.append(f"base model '{base_model}' must be an open-weight Meta model from the catalog")
    if provider not in PROVIDERS: P.append(f"provider '{provider}' not in {PROVIDERS}")
    if not manifest.get("released"): P.append("dataset not released (too few contributors)")
    if manifest.get("consent_purpose") != "model-improvement" or not manifest.get("pii_scan_pass"): P.append("dataset lacks model-improvement consent or a passing PII scan")
    if P: raise ValueError("; ".join(P))
    return dict(base_model=base_model, provider=provider, method=method, rank=rank, epochs=epochs, dataset_sha256=manifest["sha256"], examples=manifest["examples"], submitted=False)
