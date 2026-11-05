# SPEC-VOICE-RUNTIME-01 · Humanflow voice core on the Meta Model API

- **Version:** 1.0.0 (2026-11-04) · **Derived from:** `packages/{humanflow,assistant,metarouter,perception}` @ 574764c, dev.meta.ai docs read 2026-11-04
- **Supersedes:** the Bifrost route in `metarouter.policy.GATEWAY` (Bifrost is removed from the runtime path)
- **Deadline:** Meta Global AI Developer Hackathon submission, 2026-11-04 21:00 ET (20:00 CT)
- **Companion file:** `docs/spec/models.registry.json` (MODEL-REGISTRY-01), the single source of truth for model ids, endpoints, prices, limits and role bindings

**Contract.** Build one realtime voice agent ("the core") that a person talks to about their own time, tasks and resources. It hears through Meta streaming ASR, thinks and calls tools through Muse Spark, reads and writes the humanflow ledger, and dispatches background agents over one event bus. All model traffic goes through our own runtime gateway. **Done when** a recorded demo shows: speak → live transcript → tool call against the ledger → spoken answer, with the gateway log showing each Meta call, and `scripts/verify_claims.py --require-all` still passes.

---

## 1. Facts the design rests on (from Meta's docs)

| Fact | Consequence |
|---|---|
| Base `https://api.meta.ai/v1`, `Authorization: Bearer $MODEL_API_KEY` | One upstream, one secret, held only by the gateway |
| Chat Completions is OpenAI-shaped; SSE `data:` chunks, `data: [DONE]` | Use the stdlib/OpenAI-compatible client; no SDK lock-in |
| Rejected params: `stop`, `logit_bias`, `frequency_penalty`, `presence_penalty`, `modalities`, `audio`, `web_search_options`; `max_tokens` deprecated → `max_completion_tokens`; `reasoning_effort: "none"` → 400 | Gateway strips/renames these before forwarding |
| Every assistant `tool_calls` entry must be followed by a `tool` message with the matching `tool_call_id`, else 400 | Tool loop must always replay results, including errors |
| Realtime ASR: `wss://api.meta.ai/v1/asr/realtime`, JSON handshake then raw PCM s16le mono 16/24 kHz, 60-min session cap, 5 s backlog cap | Gateway owns the socket; browser streams PCM to the gateway |
| **No text-to-speech, no speech-to-speech** ("It does not synthesize speech or provide a speech-to-speech conversation API") | Speech output is on-device: browser `speechSynthesis`. Say so in the submission |
| **No embeddings endpoint** | Retrieval stays local (`assistant.core.bm25`); semantic store is NO_SIGNAL until a Meta embedder is served |
| Spark 1.3 audio input "not fully supported" | Audio understanding (tone, non-speech) routes to Spark 1.2; speech goes through ASR |
| Contributor tier ≈ 1/12 input and 1/21 output price, ~150 RPM | Background agents use `*-contributor`; the voice hot path never does |
| `muse-spark-open` and Glimmer are self-host only | Offline fallback is out of scope tonight |

Still **UNVERIFIED** (docs page not read): exact `tools` / `tool_choice` / `response_format` JSON. Assumed OpenAI-compatible. **Check V1** (§9) settles it with one live call before any tool code is trusted.

---

## 2. Topology

```
 Browser (Next/React or plain HTML)                Runtime gateway  (replaces Bifrost; one process, stdlib + websockets)
 ┌───────────────────────────┐   WS /v1/voice      ┌──────────────────────────────────────────────────────────┐
 │ mic → AudioWorklet → PCM16 │ ─────────────────▶ │ VoiceSession ── WSS ─▶ api.meta.ai/v1/asr/realtime         │
 │ transcript UI  ◀───────────│ ◀── events ──────── │      │ speechComplete                                       │
 │ speechSynthesis (TTS)      │                     │      ▼                                                     │
 │ timeline / ledger view     │   REST /v1/*        │ VoiceCore (Muse Spark 1.3, tool loop) ── /v1/chat ──▶ Meta │
 └───────────────────────────┘ ◀─────────────────▶ │      │ tool calls          ▲                               │
                                                     │      ▼                     │ results                       │
                                                     │ ToolRegistry ── humanflow.PersonalLedger / rollup / tasks │
                                                     │      │ emits                                             │
                                                     │      ▼                                                    │
                                                     │ EventBus (in-proc pub/sub + append-only JSONL log)         │
                                                     │      │ subscribes                                        │
                                                     │      ▼                                                    │
                                                     │ Agents: classifier · optimizer · planner · summarizer     │
                                                     │         (Spark contributor / Wonder, via the same gateway) │
                                                     └──────────────────────────────────────────────────────────┘
```

One process tonight. Every box is a module with a typed interface, so each can become its own service later without changing messages.

---

## 3. Runtime gateway (`packages/runtime/gateway`)

Replaces Bifrost. Holds the only copy of `MODEL_API_KEY`. Agents and the browser never see it.

**Inbound API (OpenAI-compatible, so existing callers keep working):**

| Route | Purpose |
|---|---|
| `POST /v1/chat/completions` | Body `{role, messages, tools?, stream?, effort?}`. `role` resolves to a model via `role_bindings`; a raw `model` is accepted only if it is in the registry |
| `GET /v1/models` | Registry view with status per model |
| `WS /v1/voice` | Browser voice session (§5) |
| `GET /v1/events?since=` | SSE tail of the event bus for the UI |
| `GET /healthz` | Upstream reachability, key present (presence only), last error |

**Per request the gateway:**
1. Resolves `role → model` from the registry; refuses non-registry models (keeps `[C:meta-only-policy]`).
2. Normalises params: `max_tokens → max_completion_tokens`; drops rejected params; maps `effort` to `reasoning_effort` and clamps to the model's allowed list.
3. Runs `perception.redact.scan` on outbound text; refuses if anything unredacted remains.
4. Token bucket per model family from `rate_limits_per_team`; on 429 honours `Retry-After`; retries 5xx with full-jitter backoff, max 3; on final failure walks `fallback[]`.
5. Emits `gateway.call` to the bus: `{request_id, role, model, latency_ms, prompt_tokens, completion_tokens, cost_usd, status}`; cost from registry prices.

**Env (`.env.example`):**
```
MODEL_API_KEY=            # owner sets it; never committed
META_BASE_URL=https://api.meta.ai/v1
META_ASR_URL=wss://api.meta.ai/v1/asr/realtime
GATEWAY_BIND=127.0.0.1:8787
REGISTRY_PATH=docs/spec/models.registry.json
EVENT_LOG=var/events.jsonl
LEDGER_PATH=var/ledger.jsonl
ALLOW_CONTRIBUTOR=1
VOICE_EFFORT=low
```

---

## 4. Message envelope (every bus event, every service-to-service message)

```json
{
  "id": "evt_01J…",            "type": "ledger.event.added",
  "ts": "2026-11-04T22:10:03.120Z",
  "source": "voice.core",      "subject": "owner:drew",
  "causation_id": "evt_…",     "correlation_id": "turn_…",
  "schema": "ledger.event.added/1",
  "data": { }
}
```

Append-only, one JSON object per line in `EVENT_LOG`. Replays rebuild every projection. Never edit a line; corrections are new events with `causation_id`.

**Event types (v1):**

| Type | Producer | Data |
|---|---|---|
| `voice.speech.start` / `voice.transcript.partial` / `voice.utterance.final` | VoiceSession | `{turn_id, text, audio_ms}` |
| `core.turn.started` / `core.turn.completed` | VoiceCore | `{turn_id, model, tool_calls[], reply}` |
| `tool.called` / `tool.result` | ToolRegistry | `{name, args, ok, result|error}` |
| `ledger.event.added` | ledger tools | humanflow event `{t, activity, duration_s?, text, failed_search?}` |
| `timer.started` / `timer.stopped` | ledger tools | `{task_id, activity, t}` |
| `task.created` / `task.updated` | task tools | `{task_id, title, status, estimate_s?, due?}` |
| `insight.proposed` | agents | `{kind, text, evidence_event_ids[], confidence}` |
| `gateway.call` | gateway | §3 step 5 |
| `consent.changed` | UI | `{source, purpose, allowed}` |

---

## 5. Voice loop

**Browser → gateway (`WS /v1/voice`):** first text frame `{"type":"start","lang":"en","sample_rate":16000}`; then binary PCM16 mono 16 kHz in 20–40 ms frames; `{"type":"stop"}` to end; `{"type":"barge_in"}` when the person starts talking over TTS.

**Gateway → Meta ASR:** on `start`, open `wss://api.meta.ai/v1/asr/realtime` and send within 10 s:
```json
{"authorization":{"accessToken":"Bearer <MODEL_API_KEY>"},
 "audioEncoding":"PCM_16KHZ","model":"muse-voice-transcribe-1.0",
 "mode":"ENDPOINTING","partialMode":"CUMULATIVE","emitAudioProgress":true,
 "keywords":["humanflow","focus","standup"]}
```
Forward PCM unchanged, paced in real time. Map server events: `speechStart → voice.speech.start`, `transcript(final:false) → voice.transcript.partial`, `speechComplete{turnId,transcript} → voice.utterance.final`. Reconnect before 60 min; on close 1008/1011/1013 emit `voice.error` and reopen with backoff.

**VoiceCore turn (on `voice.utterance.final`):**
1. Build messages: system prompt (§7) + last N turns + `ledger_snapshot` (today's `PersonalLedger.summary(owner)`, a few hundred tokens).
2. `POST /v1/chat/completions` role `voice.core` (Spark 1.3, `reasoning_effort: low`, `stream: true`, tools from §6).
3. Stream text deltas to the browser as `{"type":"say.delta"}`; browser speaks each completed sentence with `speechSynthesis` as it arrives (first audio target < 1.5 s after end of speech).
4. On `tool_calls`: execute, append `tool` messages with matching `tool_call_id` (errors too), call again. Max 4 tool rounds per turn.
5. Emit `core.turn.completed`. On `barge_in`, cancel the stream and `speechSynthesis.cancel()`.

---

## 6. Tool surface (the core's "perfectly shaped tooling")

JSON Schema, strict, OpenAI function format. Each tool is a pure function over the ledger/task store plus one bus event.

| Tool | Args | Returns | Backed by |
|---|---|---|---|
| `start_timer` | `{activity: enum CATEGORIES, task_id?: str, note?: str}` | `{timer_id, started_at}` | ledger + `timer.started` |
| `stop_timer` | `{timer_id?: str}` (default: running) | `{seconds, activity}` | ledger + `timer.stopped` |
| `log_time` | `{activity, minutes: int 1..600, note?: str, at?: iso8601}` | `{event_id}` | `PersonalLedger.add` |
| `get_summary` | `{range: enum[today,week], switch_cost_s?: number}` | `PersonalLedger.summary` | humanflow.personal |
| `create_task` | `{title: str, estimate_min?: int, due?: iso8601}` | `{task_id}` | task store |
| `update_task` | `{task_id, status: enum[todo,doing,blocked,done], note?}` | `{task_id, status}` | task store |
| `list_tasks` | `{status?: enum}` | `[{task_id,title,status,estimate_min}]` | task store |
| `suggest_next` | `{}` | `{status, text, questions}` | `Assistant.suggest` (respects focus hold and hourly budget) |
| `find_resource` | `{query: str}` | `[{title, snippet}]` | `assistant.core.bm25` over the owner's own docs |
| `team_rollup` | `{group: str}` | rollup (k ≥ 5, DP noise) or `suppressed` | humanflow.rollup |

Tools never return another person's per-event data; `rollup` keeps its k-anonymity and Laplace noise.

```json
{"type":"function","function":{"name":"log_time","description":"Record time the owner spent on an activity.",
 "parameters":{"type":"object","additionalProperties":false,"required":["activity","minutes"],
  "properties":{"activity":{"type":"string","enum":["focus","meeting","comms","search","wait","admin","other"]},
   "minutes":{"type":"integer","minimum":1,"maximum":600},"note":{"type":"string","maxLength":280},
   "at":{"type":"string","format":"date-time"}}}}}
```

---

## 7. Voice core system prompt (v1)

> You are the voice of Humanflow, a private time and focus assistant for one person. You speak briefly: one or two sentences, plain words, no lists. You track time, tasks and resources only through your tools; never invent numbers. If the person states an activity, log or time it. If their goal is unclear, ask one short question. During focus, speak only when asked. Their per-event data is theirs alone; group views come only from `team_rollup`.

---

## 8. Agent pipelines (bus subscribers)

All run through the gateway on role `agent.background` (Spark contributor) unless noted. Each is idempotent on `event.id`, writes only `insight.proposed`, and never speaks; the core decides whether to say anything.

| Agent | Triggers on | Does | Model |
|---|---|---|---|
| Classifier | `voice.utterance.final`, `ledger.event.added` | Labels free text into CATEGORIES; flags `failed_search` | contributor, effort low |
| Optimizer | every 15 min of ledger time | Computes switches, wait and failed-search loss; proposes one change | contributor, effort medium |
| Planner | `task.created`, start of day | Orders tasks by due date and estimate; proposes a day plan | Wonder 1.0, effort high (only on request) |
| Summarizer | `timer.stopped`, end of day | Writes a 3-line day note to the ledger | contributor |
| Cost guard | `gateway.call` | Running spend per role; trips `ALLOW_CONTRIBUTOR` / effort down past a budget | none (arithmetic) |

**Suggestion ranking (owner requirement, 2026-11-04).** Every suggestion carries its expected time won back (per week, compounded over month, year and decade) and its cost to adopt (minutes of effort plus money). Rank by won-back time divided by cost to adopt, so the largest win-back that is cheapest and fastest to make comes first. Never show a suggestion without both numbers.

Service-to-service messaging = bus events (§4). "Optimizing" = Optimizer + Cost guard, plus `MetaRouter` cost-per-success ordering (already in `metarouter.router`) choosing among each role's fallbacks.

Out of scope tonight: embeddings/semantic store (no Meta route), Glimmer/Spark Open self-hosting, Spark/Glimmer fine-tuning, multi-service deploy, wearables.

---

## 9. Checks (declared before building; each can fail)

| ID | Check | Pass |
|---|---|---|
| V1 | `curl $META_BASE_URL/models` with the key, then one chat call with a `log_time` tool | 200; the model returns `tool_calls[0].function.name == "log_time"` with valid JSON args. Settles the UNVERIFIED tool shape |
| V2 | 10 s WAV through `/v1/asr/transcribe` | non-empty transcript |
| V3 | Realtime ASR: stream a WAV at 1× through the gateway WS | `voice.utterance.final` event with expected words |
| V4 | Unit: gateway strips `stop`, renames `max_tokens`, refuses an unknown model | tests pass |
| V5 | Unit: tool loop replays a failing tool as a `tool` message | no 400 from upstream (mock asserts pairing) |
| V6 | End to end: "I've been in meetings for 40 minutes" → ledger has `meeting` 2400 s → "How was my day?" answer cites it | demo recording |
| V7 | `python scripts/verify_claims.py --require-all` | still passes |

---

## 10. Tonight's cut (≈3 h to 20:00 CT)

| By (CT) | Ship |
|---|---|
| 17:30 | V1 + V2 live against Meta (needs the key set on the dev VM). Gateway: `/v1/chat/completions` + registry + param normalising |
| 18:30 | Tool registry with `log_time`, `start_timer`, `stop_timer`, `get_summary`, `create_task`, `list_tasks`. Text-only core loop works (V5, V6 typed instead of spoken) |
| 19:15 | `WS /v1/voice` ↔ Meta realtime ASR; minimal page: mic button, live transcript, `speechSynthesis` replies (V3) |
| 19:35 | Record the 3-minute demo; update `docs/HACKATHON.md` (Bifrost removed, voice core added, TTS on-device, no embeddings) |
| 19:50 | Submit on the Cerebral Valley form. Agents in §8 beyond Classifier are spec-only in the submission |

**Stops.** Setting the API key (owner signs in). Pushing to a protected branch or submitting the form (owner approves). If V1 shows a different tool shape, stop and adjust §6 before building on it.
