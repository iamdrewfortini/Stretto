# SPDX-License-Identifier: Apache-2.0
"""Title redaction for the sensor agent (stdlib-only mirror).

Window titles are the only free text the agent touches. They pass
through this redactor and are truncated to 80 chars before they can
leave the process; ``SENSORS_TITLES=off`` drops them entirely. The
patterns mirror ``perception.redact`` (email, API key, SSN, IPv4,
phone, Luhn-checked card) so the standalone agent enforces the same
bar without importing a sibling package. Tests cross-check parity
against ``perception.redact`` when that package is importable.
"""
import hashlib
import re

MAX_TITLE = 80


def _luhn(digits):
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        d = d * 2 - 9 if alt and d * 2 > 9 else (d * 2 if alt else d)
        s += d
        alt = not alt
    return s % 10 == 0


_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("API_KEY", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|"
        r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|"
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PHONE", re.compile(
        r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")),
]
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def redact(text):
    """Return (clean_text, counts) with secrets replaced by tags."""
    counts = {}
    text = text or ""
    # Fast path: digit/@ patterns need a digit or '@'; the API-key
    # shapes are the only ones that can appear without either, so
    # their literal prefixes must also be absent. Most window titles
    # have none of these; skip all regex work for them.
    if not any(ch.isdigit() for ch in text) and "@" not in text and \
            not any(k in text for k in ("eyJ", "sk-", "ghp_", "AKIA", "xox")):
        return text, counts

    def card(m):
        d = re.sub(r"\D", "", m.group(0))
        if 13 <= len(d) <= 19 and _luhn(d):
            counts["CARD"] = counts.get("CARD", 0) + 1
            return "[CARD]"
        return m.group(0)

    text = _CARD.sub(card, text)
    for name, pat in _PATTERNS:
        text, n = pat.subn(f"[{name}]", text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


_title_cache = {}
_TITLE_CACHE_MAX = 128


def clean_title(raw, titles_on=True):
    """Redact + truncate a window title; None when titles are off.

    Most ticks repeat the previous title verbatim, so recent
    results are cached (bounded, oldest evicted). Keys are SHA-256
    digests: raw titles are never retained, only redacted results.
    """
    if not titles_on or raw is None:
        return None
    key = hashlib.sha256(str(raw).encode()).hexdigest()
    hit = _title_cache.get(key)
    if hit is not None:
        return hit
    clean, _ = redact(str(raw))
    clean = clean[:MAX_TITLE]
    if len(_title_cache) >= _TITLE_CACHE_MAX:
        _title_cache.pop(next(iter(_title_cache)))
    _title_cache[key] = clean
    return clean
