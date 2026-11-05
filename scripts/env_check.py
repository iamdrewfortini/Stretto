#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ENV-STANDARD-01 check. Proves the runtime environment is local-only and the secrets file is private.
Never prints a secret: presence, length and an 8-hex sha256 fingerprint only. Exit 0 = all checks pass."""
import hashlib, ipaddress, os, stat, subprocess, sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
# The real env file lives OUTSIDE every worktree (default:
# ~/.config/humanflow/runtime.env). HUMANFLOW_ENV overrides the
# location. The repo-root .env is a legacy fallback only.
ENV = Path(os.environ.get(
    "HUMANFLOW_ENV",
    Path.home() / ".config" / "humanflow" / "runtime.env"))
if not os.environ.get("HUMANFLOW_ENV") and not ENV.is_file():
    ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
SECRETS = {"MODEL_API_KEY"}


def parse(path):
    out = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            raise ValueError(f"{path.name}:{n}: not KEY=VALUE")
        k, v = s.split("=", 1)
        v = v.split(" #", 1)[0].strip() if not v.lstrip().startswith(("'", '"')) else v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True)


def main():
    quiet = "--quiet" in sys.argv
    res = []
    ok = lambda name, cond, detail="": res.append((name, bool(cond), detail))

    ok("env.exists", ENV.is_file(), str(ENV))
    if not ENV.is_file():
        return report(res, quiet)
    st = ENV.stat()
    ok("env.mode_600", stat.S_IMODE(st.st_mode) == 0o600, oct(stat.S_IMODE(st.st_mode)))
    ok("env.owner", st.st_uid == os.getuid())
    top = git("rev-parse", "--show-toplevel")
    in_tree = top.returncode == 0 and str(ENV).startswith(
        top.stdout.strip() + os.sep)
    ok("env.outside_worktree", not in_tree, str(ENV))
    if in_tree:
        rel = str(ENV.relative_to(top.stdout.strip()))
        ok("env.gitignored", git("check-ignore", "-q", rel).returncode == 0)
        ok("env.untracked",
           git("ls-files", "--error-unmatch", rel).returncode != 0)

    env, ex = parse(ENV), parse(EXAMPLE)
    missing = [k for k in ex if k not in env]
    ok("keys.complete", not missing, ",".join(missing))
    ok("example.no_secret_values", all(not ex.get(k) for k in SECRETS))

    for k in sorted(SECRETS):
        v = env.get(k, "")
        fp = hashlib.sha256(v.encode()).hexdigest()[:8] if v else "-"
        ok(f"secret.{k}.present", len(v) >= 20, f"len={len(v)} sha256:{fp}")
        # pattern goes through stdin, never argv, so it cannot show up in `ps`
        leaked = subprocess.run(["git", "-C", str(ROOT), "grep", "-l", "-F", "-f", "/dev/stdin", "HEAD"], input=v,
                                capture_output=True, text=True).stdout.split() if v else []
        ok(f"secret.{k}.not_in_tree", not leaked, ",".join(leaked))

    ok("boundary.mode_local", env.get("RUNTIME_MODE") == "local", env.get("RUNTIME_MODE", ""))
    host = env.get("GATEWAY_BIND", "").rsplit(":", 1)[0]
    try:
        loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loop = host == "localhost"
    ok("boundary.bind_loopback", loop, env.get("GATEWAY_BIND", ""))
    allow = {h.strip() for h in env.get("EGRESS_ALLOWLIST", "").split(",") if h.strip()}
    ok("boundary.egress_meta_only", allow == {"api.meta.ai"}, ",".join(sorted(allow)))
    for k in ("META_BASE_URL", "META_ASR_URL"):
        u = urlsplit(env.get(k, ""))
        ok(f"boundary.{k}", u.scheme in ("https", "wss") and u.hostname in allow, f"{u.scheme}://{u.hostname}")
    return report(res, quiet)


def report(res, quiet):
    bad = [r for r in res if not r[1]]
    if not quiet or bad:
        for name, passed, detail in res:
            print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        print(f"env check: {'ok' if not bad else f'{len(bad)} failed'} ({len(res)} checks)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
