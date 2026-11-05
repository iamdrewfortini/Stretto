# Install Stretto — the exact fresh-install walk

Verified by walking it on a clean data folder. Every output below is real.

## What you need

| Need | Minimum | Notes |
|---|---|---|
| Python | 3.8+ | Nothing to pip install, stdlib only |
| Disk | ~50 MB | Plus your local database, which grows with use |
| Network | None to run | Only the Meta call leaves the machine, after consent |
| OS | macOS, Windows, Linux | Agent probes per OS, server identical |

## Step 1 — Get the code

```sh
git clone https://github.com/iamdrewfortini/Stretto.git
cd Stretto/apps/stretto
```

## Step 2 — Install (creates data, prepares keys file, checks health)

macOS / Linux:

```sh
sh install.sh            # set up and start
sh install.sh --no-start # set up only
```

Windows (PowerShell): `.\install.ps1`. What happens, in order:

1. Creates the data folder (`~/.stretto`, or `$STRETTO_DATA`).
2. Copies `.env.example` to `<data>/.env` with owner-only permissions. Your Meta key goes there, never in the repo.
3. Runs `python3 -m stretto doctor` (below).
4. Starts the server, or prints `Set up. Start later with: sh run.sh`.

## Step 3 — Read the doctor

```sh
python3 -m stretto doctor
```

Expect on a fresh install: server files ready, durability `wal/FULL/fullfsync=on`, agent files ready,
Meta access `NOT SET` (fine — everything except Insights works), and one `[warn]` per unaccepted notice.
The last line reads `Start: python3 -m stretto --data <data> then open http://127.0.0.1:8760`.

## Step 4 — Start, and meet the bond

```sh
sh run.sh   # or: python3 -m stretto
```

First line names the address and durability. Second line prints your install **Bond** id.
The bond permanently fuses gateway, client and agent (hashes only). Check its locks any time:

```sh
python3 -m stretto bond
```

Fresh install reads `PRESSURIZED` (~75%): transport, auth, consent, ledger, cache and geometry sealed;
agent and learning open until a device enrols and the learner first runs. That is the honest state.

## Step 5 — Open the app and follow the light

Open http://127.0.0.1:8760. The bottom guide walks five steps. Do them in order:

1. **Privacy** — read a notice, use the single form (name, tick families, type `I AGREE: ALL`), or accept per family.
2. **Today** — enrol/start the agent from Devices, or load the labelled simulated day to look around first.
3. **Challenges** — read the grouped loss; pin one challenge.
4. **Focus** — run one 25-minute block.
5. **Insights** — optional: add `MODEL_API_KEY=` to `<data>/.env`, restart, accept the meta-insights notice, generate.

## Step 6 — Add the Meta key (optional, for Insights and the model gateway)

Put `MODEL_API_KEY=<your key>` in `<data>/.env` and restart. All model traffic in the whole system —
Insights, voice subagents, any component — goes through the single hosted runtime at `POST /api/model/chat`
(consent-gated, tiered wonder/spark, ledgered, budget-capped). No key: the endpoint answers a structured
`503 no_model_access`, and the rest of Stretto is unaffected. Keyless judging: `STRETTO_REPLAY=<folder>`.

## Updating and removing

Update: `git pull`, restart. Your data folder is untouched by updates. Remove: stop the server and delete
the data folder. Revoke a device or purge a consent family any time in Privacy; both survive restarts.
