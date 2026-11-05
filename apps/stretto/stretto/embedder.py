# SPDX-License-Identifier: Apache-2.0
"""Tensor embeddings for recall, on this hardware.
Two providers, one interface (dense 128-dim, L2-normalised):
  META   when STRETTO_EMBED_MODEL is set and a Model API key exists: POST /embeddings to Meta (api.meta.ai/v1).
         Any failure falls back at once — recall must never wait on the network.
  TENSOR local, always available: each term is hashed to a stable pseudo-random projection (seeded by the term
         itself, so vectors are identical across processes and machines), summed and normalised. This is a dense
         tensor embedding computed locally in microseconds on a 4-core Intel Mac — not a pretrained transformer;
         its job is stable geometry for clustering/recall, and the provider used is always reported honestly.
Results live in the stable KV cache: the same text embeds once per process."""
import hashlib
import json
import math
import os
import urllib.request

from . import kvcache

DIMS = 128
_mode = {"provider": "tensor", "meta_failures": 0}
_WEIGHTS = {}


def set_weights(w):
    """Learned per-term weights from selftrain: the local geometry bends toward what this person finishes."""
    global _WEIGHTS
    _WEIGHTS = dict(w or {})


def _term_vec(term):
    h = hashlib.sha256(term.encode()).digest()
    seed = int.from_bytes(h[:8], "little")
    out, x = [], seed or 1
    for _ in range(DIMS):   # xorshift64*: deterministic per term, no stored matrix
        x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF; x ^= x >> 7; x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
        out.append(((x % 2000) - 1000) / 1000.0)
    return out


def _local(text, vocab_terms):
    acc = [0.0] * DIMS
    for t in vocab_terms:
        v = [x * _WEIGHTS.get(t, 1.0) for x in _term_vec(t)]
        for i in range(DIMS):
            acc[i] += v[i]
    n = math.sqrt(sum(x * x for x in acc)) or 1.0
    return [round(x / n, 6) for x in acc]


def _meta(text):
    body = dict(model=os.environ["STRETTO_EMBED_MODEL"], input=text[:8000])
    req = urllib.request.Request("https://api.meta.ai/v1/embeddings", method="POST", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["MODEL_API_KEY"].strip(), "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as r:
        data = json.loads(r.read(5_000_000))
    vec = data["data"][0]["embedding"]
    n = math.sqrt(sum(float(x) * float(x) for x in vec)) or 1.0
    return [round(float(x) / n, 6) for x in vec]


def dense(text, vocab_terms):
    """Embedding for text. vocab_terms: topics.terms(text) from the caller (keeps this module vocabulary-free)."""
    wf = hashlib.sha256(json.dumps(sorted(_WEIGHTS.items())).encode()).hexdigest()[:12] if _WEIGHTS else "base"
    k = kvcache.key("embed", wf, text)
    hit = kvcache.get(k)
    if hit is not None:
        return hit
    vec = None
    if os.environ.get("STRETTO_EMBED_MODEL") and os.environ.get("MODEL_API_KEY"):
        try:
            vec = _meta(text); _mode["provider"] = "meta"
        except Exception:
            _mode["meta_failures"] += 1
    if vec is None:
        vec = _local(text, vocab_terms)
    return kvcache.put(k, vec)


def cosine(a, b):
    return round(sum(x * y for x, y in zip(a, b)), 6)


def stats():
    return dict(dims=DIMS, provider=_mode["provider"], meta_failures=_mode["meta_failures"], kv=kvcache.stats())
