# SPDX-License-Identifier: Apache-2.0
"""1Password SDK secret resolution (BYOK, issue #28).

Bootstrap model: one operator-owned token (the "1st key"), supplied as the
OP_SERVICE_ACCOUNT_TOKEN environment variable, lets the SDK resolve
op://<vault>/<item>/<field> references from the operator's own vault.
Nothing here knows any maintainer vault or key: every clone/fork uses its
own vault, service account and token, or skips 1Password entirely and puts
its own keys in the 0600 .env as before.

Secret values are never logged, printed, or returned in metadata helpers.
The SDK (onepassword-sdk) is imported lazily, only when a token is present,
so tests and keyless runs need no extra dependency.
"""
import asyncio, json, os

DEFAULT_REGISTRY = "docs/spec/secrets.registry.json"
TOKEN_ENV = "OP_SERVICE_ACCOUNT_TOKEN"
INTEGRATION = ("stretto-humanflow", "0.1.0")


def load_registry(path=None):
    """Registry maps env names to secret metadata (refs only, never values)."""
    p = path or os.environ.get("SECRETS_REGISTRY", DEFAULT_REGISTRY)
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for name, entry in data.get("secrets", {}).items():
        ref = os.environ.get(f"OP_REF_{name}") or entry.get("ref", "")
        out[name] = dict(ref=ref, required=bool(entry.get("required")))
    return out


def token_present(env=None):
    return bool((env or os.environ).get(TOKEN_ENV))


async def _default_client(token):
    from onepassword import Client
    return await Client.authenticate(token, INTEGRATION[0], INTEGRATION[1])


async def resolve_refs(refs, token, client_factory=None):
    """Resolve {env_name: op_ref} to {env_name: value}. Values stay in memory."""
    factory = client_factory or _default_client
    client = await factory(token)
    out = {}
    for name, ref in refs.items():
        if ref:
            out[name] = await client.secrets.resolve(ref)
    return out


def resolve_missing(env, registry=None, client_factory=None):
    """Fill missing env values from the operator vault. Returns names filled.

    No-ops (returns []) when no bootstrap token is configured, so keyless
    and fork runs behave exactly as before. Never mutates values already set:
    an explicit .env key always wins over the vault.
    """
    if not token_present(env):
        return []
    reg = registry if registry is not None else load_registry()
    wanted = {k: v["ref"] for k, v in reg.items() if not env.get(k) and v.get("ref")}
    if not wanted:
        return []
    values = asyncio.run(resolve_refs(wanted, env[TOKEN_ENV], client_factory))
    for k, v in values.items():
        env[k] = v
    return sorted(values)
