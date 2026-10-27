# SPDX-License-Identifier: Apache-2.0
"""Text redaction applied BEFORE anything is stored or sent to a model. Conservative patterns; a miss is possible, so downstream stores also run `scan()` and refuse on any hit."""
import re

def luhn(digits):
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch); d = d * 2 - 9 if alt and d * 2 > 9 else (d * 2 if alt else d); s += d; alt = not alt
    return s % 10 == 0
PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("API_KEY", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")),
]
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
def redact(text):
    """Returns (clean_text, counts). Cards are redacted only when the digits pass the Luhn check, so order numbers are left alone."""
    counts = {}
    def card(m):
        d = re.sub(r"\D", "", m.group(0))
        if 13 <= len(d) <= 19 and luhn(d): counts["CARD"] = counts.get("CARD", 0) + 1; return "[CARD]"
        return m.group(0)
    text = CARD.sub(card, text)
    for name, pat in PATTERNS:
        text, n = pat.subn(f"[{name}]", text)
        if n: counts[name] = counts.get(name, 0) + n
    return text, counts
def scan(text): return redact(text)[1]            # non-empty result = something that should have been redacted
