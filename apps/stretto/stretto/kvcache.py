# SPDX-License-Identifier: Apache-2.0
"""Stable in-memory KV cache (Cookbook 01/05 prompt caching, applied locally).
Content-addressed keys (sha256 of the stable prefix + payload), LRU eviction, hit/miss accounting. 'Stable' means
the same input always lands on the same key across processes: the system-prompt prefix of every Meta call is one
entry, so token spend on it is paid once per process and reported, never re-derived."""
import hashlib
from collections import OrderedDict

_cache = OrderedDict()
_stats = dict(hits=0, misses=0, puts=0)
MAX = 1024


def key(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]


def get(k):
    if k in _cache:
        _cache.move_to_end(k); _stats["hits"] += 1
        return _cache[k]
    _stats["misses"] += 1
    return None


def put(k, v):
    _cache[k] = v; _cache.move_to_end(k); _stats["puts"] += 1
    while len(_cache) > MAX:
        _cache.popitem(last=False)
    return v


def stats():
    return dict(_stats, size=len(_cache), max=MAX)
