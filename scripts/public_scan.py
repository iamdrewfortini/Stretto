# SPDX-License-Identifier: Apache-2.0
"""Public-repo safety scan. Fails on private network addresses, real-looking e-mail addresses, personal filesystem paths, key material and API-key shapes.
Known fake fixtures used by the redaction tests are allow-listed by exact value. Optional --deny-file adds organisation-specific words (keep that file OUT of the repo)."""
import os, re, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PRIV_IP = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|internal)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PATHS = re.compile(r"(?:[A-Za-z]:\\Users\\|/home/[a-z][a-z0-9_-]+/|/Users/[A-Za-z]+/)")
KEYS = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{20,}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}\b|\bsk-[A-Za-z0-9_-]{16,}\b")
FIXTURES = {"sk-abcdefghijklmnop1234"}
GENERIC_CIDRS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")        # the three RFC 1918 blocks as policy text; any other private address is still a finding
def main():
    deny = []
    if "--deny-file" in sys.argv: deny = [w.strip().lower() for w in open(sys.argv[sys.argv.index("--deny-file") + 1], encoding="utf-8") if w.strip()]
    bad = []
    for dp, dn, fs in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in (".git", "__pycache__", "target", "dist", ".venv")]
        for f in fs:
            if f.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".tbl", ".pyc", ".so", ".a", ".rlib", ".rmeta", ".d", ".o")) or os.path.getsize(os.path.join(dp, f)) > 2_000_000: continue
            p = os.path.join(dp, f); rel = os.path.relpath(p, ROOT)
            for i, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
                if os.path.basename(p) == "public_scan.py": continue
                for g in GENERIC_CIDRS: line = line.replace(g, "")
                for name, pat in (("private-ip", PRIV_IP), ("email", EMAIL), ("personal-path", PATHS), ("secret-shape", KEYS)):
                    for m in pat.finditer(line):
                        if m.group(0) not in FIXTURES: bad.append(f"{rel}:{i}: {name}: {m.group(0)[:40]}")
                for w in deny:
                    if w in line.lower(): bad.append(f"{rel}:{i}: denied word '{w}'")
    print(f"public scan: {len(bad)} finding(s)"); [print(" ", b) for b in bad[:60]]; return 1 if bad else 0
if __name__ == "__main__": sys.exit(main())
