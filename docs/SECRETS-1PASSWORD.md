# Secrets: 1Password SDK bootstrap (BYOK)

> Repo home → Docs → Secrets: 1Password SDK bootstrap
> Source of truth for references: [docs/spec/secrets.registry.json](spec/secrets.registry.json) · Tracker: [#28](https://github.com/iamdrewfortini/Stretto/issues/28)

Every operator — maintainer, clone, or fork — uses **their own keys**. No
maintainer key, vault, or token is in this repo, and none is ever shared.
GitHub Secrets hold exactly one value: the bootstrap token (the 1st key).
Everything else is fetched at runtime by the 1Password SDK from the
operator's own vault and is never printed, logged, or committed.

## Two supported paths

1. **No 1Password.** Put your own `MODEL_API_KEY` in a `.env` file with
   mode `0600` next to the repo (see `.env.example`). Everything works;
   this is the default and the fallback.
2. **1Password.** Create a vault named `Stretto-CI` in your own account
   (or edit the references in `docs/spec/secrets.registry.json`, or set
   `OP_REF_<NAME>` environment overrides to your own vault/items). Add
   your items there, create a **read-only service account** scoped to
   that vault, and supply its token as `OP_SERVICE_ACCOUNT_TOKEN`.

## Where the 1st key goes

- **Local runtime:** add `OP_SERVICE_ACCOUNT_TOKEN=<your token>` to the
  repo `.env` (`0600`). With a plain `MODEL_API_KEY` already set, the
  vault is never consulted — your explicit key always wins. With only
  the token set, the Humanflow gateway resolves missing keys in memory
  at startup through `runtime.secrets` and refuses to start, as before,
  if no key can be obtained.
- **GitHub Actions:** in your repo Settings → Secrets, add one secret
  named `OP_SERVICE_ACCOUNT_TOKEN`. Using `gh`, the operator runs
  `gh secret set OP_SERVICE_ACCOUNT_TOKEN` and pastes at the masked
  prompt — the value never appears in shell history or chat. Workflows
  pass that secret to `scripts/op_secrets.py --github-env`, which
  resolves the registry references, masks every value, and writes only
  names to the log. Add no other keys as repo secrets.

## Root Host DD inventory

The maintainer's host file `Root_HostDD.txt` lives outside the repo
(Desktop, mode `0600`, kept as the offline original). Its items belong
in the operator vault as the `Root Host DD` item; the registry reference
`ROOT_HOST_DD` points there. Automation checks item *names and
references only* (`python3 scripts/op_secrets.py --check`); it never
reads or displays the file's values.

## Forks and pull requests

GitHub does not pass repo secrets to workflows on pull requests from
forks, and this design keeps that safe: without a bootstrap token the
resolver is a no-op, model-backed cells report `skip`, and deterministic
CI stays green. A fork is never failed for lacking someone else's keys,
and a fork's own token only ever unlocks that fork owner's vault.

## Verifying

```bash
python3 scripts/op_secrets.py --check   # names, refs, token presence only
python3 -m unittest tests.test_op_secrets -v
```
