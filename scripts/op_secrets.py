# SPDX-License-Identifier: Apache-2.0
"""Operator CLI for 1Password-backed secrets (issue #28). Never prints a value.

  python3 scripts/op_secrets.py --check        names, refs, token presence only
  python3 scripts/op_secrets.py --github-env   resolve registry refs, mask them,
                                               and append NAME=value to $GITHUB_ENV
  python3 scripts/op_secrets.py --env-file .env.local   write a 0600 env file

Bootstrap: OP_SERVICE_ACCOUNT_TOKEN (the 1st key) is the operator's own
read-only 1Password service-account token. Forks/clones use their own token
and vault, or no 1Password at all (plain 0600 .env). Without a token this
script reports the honest not-configured state and exits 2.
"""
import argparse, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packages", "runtime", "src"))
from runtime import secrets as S  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--github-env", action="store_true")
    g.add_argument("--env-file")
    a = ap.parse_args()
    reg = S.load_registry()
    present = S.token_present()
    for name, e in sorted(reg.items()):
        print(f"{name} ref={e['ref'] or '-'} required={e['required']}")
    print(f"{S.TOKEN_ENV} present={present}")
    if a.check:
        return 0 if present else 2
    if not present:
        print("not configured: no bootstrap token; skipping (keys stay operator-supplied via .env)", file=sys.stderr)
        return 2
    refs = {k: v["ref"] for k, v in reg.items() if v["ref"]}
    import asyncio
    values = asyncio.run(S.resolve_refs(refs, os.environ[S.TOKEN_ENV])) if refs else {}
    if a.github_env:
        target = os.environ.get("GITHUB_ENV")
        if not target:
            print("GITHUB_ENV not set; refusing to print values", file=sys.stderr)
            return 2
        with open(target, "a", encoding="utf-8") as fh:
            for k, v in values.items():
                print(f"::add-mask::{v}")
                fh.write(f"{k}={v}\n")
        print(f"resolved {len(values)} secret(s) into GITHUB_ENV (values masked, names only here): {sorted(values)}")
        return 0
    fd = os.open(a.env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for k, v in values.items():
            fh.write(f"{k}={v}\n")
    print(f"wrote {len(values)} secret(s) to {a.env_file} (mode 0600): {sorted(values)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
