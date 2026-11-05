# SPDX-License-Identifier: Apache-2.0
"""Meta Model API client. Three routes, one code path:
  DIRECT  MODEL_API_KEY in the environment or a .env file: calls https://api.meta.ai/v1 with the operator's own key.
  RECORD  STRETTO_RECORD=<dir>: also saves each reply so others can replay it.
  REPLAY  STRETTO_REPLAY=<dir>: answers from recorded Meta replies, no key and no network (judges' keyless mode).
Every call is written to the model_calls ledger (hash-chained): model, tokens, estimated cost, seconds. A reply without a usage
report is refused (its cost could not be seen), a reply served by a non-Meta model is refused, and a daily spend cap applies.
Stdlib only."""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from . import kvcache

BASE = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
# USD per million tokens, list price (dev.meta.ai/models/muse-spark). Costs are estimates; Meta's billing is the record.
PRICES = {"muse-spark-1.3": dict(input=1.25, cached=0.15, output=4.25)}
META_PREFIXES = ("muse-", "sam-", "llama")
# Models with known list prices. Any other Meta-prefixed model may be selected; its ledger cost is then None (unknown, never invented).
KNOWN_MODELS = ("muse-spark-1.3",)


TIERS = dict(main="muse-wonder-1.0", sub="muse-spark-1.3")   # Cookbook agent-framework tiering: wonder reasons, spark executes


def model_for(tier, store=None):
    """main -> muse-wonder-1.0 (or STRETTO_MODEL_MAIN), sub -> the person's selected spark-tier model."""
    if tier == "main":
        return os.environ.get("STRETTO_MODEL_MAIN", "").strip() or TIERS["main"]
    return current_model(store)


def current_model(store=None):
    """Selected model: STRETTO_MODEL env wins, then the person's `model` setting, then DEFAULT_MODEL. Non-Meta names fall back to the default."""
    m = os.environ.get("STRETTO_MODEL", "").strip()
    if not m and store is not None:
        try:
            m = str(store.setting("model", "") or "").strip()
        except Exception:
            m = ""
    return m if m.startswith(META_PREFIXES) else DEFAULT_MODEL


class ModelUnavailable(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def env_files(data_dir=None):
    """Where a .env may live, in priority order. The first one that exists is used. Real environment variables always win."""
    return [p for p in (os.environ.get("STRETTO_ENV_FILE"), os.path.join(data_dir, ".env") if data_dir else None, os.path.join(os.getcwd(), ".env")) if p]


def load_env(data_dir=None):
    """Read KEY=VALUE lines from the first .env found. Values are never printed or logged. Returns the path used, or None."""
    for path in env_files(data_dir):
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if v.strip().strip('"').strip("'"):
                                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except OSError:
                return None
            return path
    return None


load_env()


def mode():
    if os.environ.get("MODEL_API_KEY"):
        return "direct"
    if os.environ.get("STRETTO_REPLAY"):
        return "replay"
    return None


GATEWAY_DEFAULT = "http://127.0.0.1:8787"


def gateway_url():
    """The backend gateway this app passes the model key to (loopback only)."""
    u = os.environ.get("STRETTO_GATEWAY_URL", GATEWAY_DEFAULT).rstrip("/")
    from urllib.parse import urlsplit
    if urlsplit(u).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ModelUnavailable("STRETTO_GATEWAY_URL must be a loopback address")
    return u


def _gateway(method, path, body=None, timeout=2.5):
    """One call to the backend gateway. The key is never logged or returned."""
    req = urllib.request.Request(gateway_url() + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read(1_000_000) or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error", "")
        except ValueError:
            msg = ""
        raise ModelUnavailable(f"backend gateway answered {e.code}" + (f": {msg}" if msg else "")) from None
    except (urllib.error.URLError, OSError):
        raise ModelUnavailable("backend gateway unreachable: start it first (metacoh gateway), then save the key again") from None


def gateway_status():
    """{gateway_up, key_present} for the settings page; down is a state, not an error."""
    try:
        r = _gateway("GET", "/healthz")
        return {"gateway_up": True, "key_present": bool(r.get("key_present"))}
    except ModelUnavailable:
        return {"gateway_up": False, "key_present": False}


def gateway_set_key(key):
    """Pass the person's key through to the backend gateway, its only holder.

    Stretto never stores the key: not in its settings, database or logs.
    The gateway writes it to its protected env file and answers with a
    length and fingerprint only, which is all this returns.
    """
    key = str(key or "").strip()
    if len(key) < 20:
        raise ModelUnavailable("that key looks too short; refusing to save it")
    return _gateway("POST", "/v1/settings/key", {"api_key": key})


def cost_usd(model, prompt, cached, completion):
    p = PRICES.get(model)
    return round(((prompt - cached) * p["input"] + cached * p["cached"] + completion * p["output"]) / 1e6, 6) if p else None


def _cassette(path, body):
    return hashlib.sha256((path + "\n" + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def _post(path, body, timeout=60, retries=2):
    """One POST to Meta. Replaced in tests. 429 and 5xx are retried with backoff; the error body is withheld (it may echo content)."""
    req = urllib.request.Request(BASE + path, method="POST", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["MODEL_API_KEY"].strip(), "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(retries + 1):
        try:
            with opener.open(req, timeout=timeout) as r:
                return json.loads(r.read(5_000_000))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ModelUnavailable(f"Meta Model API answered {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ModelUnavailable(f"Meta Model API unreachable: {type(e).__name__}") from None


def status(store, budget_usd):
    import datetime as dt
    t0 = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    row = store.q("SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS spent FROM model_calls WHERE ts>=? AND status='ok'", (t0,))[0]
    return dict(mode=mode(), model=current_model(store), tiers={k: model_for(k, store) for k in TIERS}, kv=kvcache.stats(), known_models=list(KNOWN_MODELS), calls_today=row["n"], spent_today_usd=round(row["spent"], 6), budget_usd=budget_usd,
                chain_ok=verify_chain(store))


def _ledger(store, **e):
    prev = (store.q("SELECT hash FROM model_calls ORDER BY id DESC LIMIT 1") or [{"hash": "0" * 64}])[0]["hash"]
    h = hashlib.sha256((prev + json.dumps(e, sort_keys=True, default=str)).encode()).hexdigest()
    cols = ("ts", "purpose", "model", "served", "mode", "prompt_tokens", "completion_tokens", "reasoning_tokens", "cost_usd", "seconds", "status", "req_sha", "reply_text")
    store.x(f"INSERT INTO model_calls({','.join(cols)},prev,hash) VALUES({','.join('?' * len(cols))},?,?)", tuple(e.get(c) for c in cols) + (prev, h))
    return h


def verify_chain(store):
    prev = "0" * 64
    cols = ("ts", "purpose", "model", "served", "mode", "prompt_tokens", "completion_tokens", "reasoning_tokens", "cost_usd", "seconds", "status", "req_sha", "reply_text")
    for r in store.q("SELECT * FROM model_calls ORDER BY id"):
        if r["prev"] != prev or r["hash"] != hashlib.sha256((prev + json.dumps({c: r[c] for c in cols}, sort_keys=True, default=str)).encode()).hexdigest():
            return False
        prev = r["hash"]
    return True


def chat(store, purpose, messages, budget_usd, model=None, max_tokens=1500):
    """One metered chat call to a Meta model. Returns dict(text, call_id, cost_usd, tokens). Raises ModelUnavailable or BudgetExceeded."""
    model = model or current_model(store)
    m = mode()
    if not m:
        raise ModelUnavailable("no Meta model access: set MODEL_API_KEY (see .env.example) or STRETTO_REPLAY=<dir> to use recorded runs")
    if not str(model).startswith(META_PREFIXES):
        raise ModelUnavailable("only Meta models are allowed")
    if m == "direct" and status(store, budget_usd)["spent_today_usd"] >= budget_usd:
        raise BudgetExceeded(f"daily model budget of ${budget_usd:.2f} is used up")
    body = dict(model=model, messages=messages, max_tokens=max_tokens)
    key, t0, e = _cassette("/chat/completions", body), time.time(), dict(ts=time.time(), purpose=purpose, model=model, mode=m)
    e["req_sha"] = key[:32]
    try:
        if m == "replay":
            f = os.path.join(os.environ["STRETTO_REPLAY"], key + ".json")
            if not os.path.isfile(f):
                raise ModelUnavailable("this request is not in the recorded run (replay mode)")
            reply = json.load(open(f, encoding="utf-8"))
        else:
            reply = _post("/chat/completions", body)
            rec = os.environ.get("STRETTO_RECORD")
            if rec:
                os.makedirs(rec, exist_ok=True)
                json.dump(reply, open(os.path.join(rec, key + ".json"), "w", encoding="utf-8"))
        e["seconds"] = round(time.time() - t0, 3)
        e["served"] = str(reply.get("model", ""))
        u = reply.get("usage") or {}
        if not (isinstance(u.get("prompt_tokens"), int) and isinstance(u.get("completion_tokens"), int)):
            raise ModelUnavailable("the reply carried no usage report: refused, because its cost could not be seen")
        if e["served"] and not e["served"].split("/")[-1].lower().startswith(META_PREFIXES):
            raise ModelUnavailable(f"refused: a non-Meta model answered ({e['served']!r})")
        p, c = u["prompt_tokens"], u["completion_tokens"]
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        e.update(prompt_tokens=p, completion_tokens=c, reasoning_tokens=(u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                 cost_usd=cost_usd(model, p, cached, c))
        text = ((reply.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        e["reply_text"] = str(text)[:4000]
        e["status"] = "ok"
        cid = _ledger(store, **e)
        return dict(text=str(text), call_id=cid[:16], cost_usd=e["cost_usd"], tokens=p + c, mode=m, model=model)
    except (ModelUnavailable, BudgetExceeded) as ex:
        e.setdefault("seconds", round(time.time() - t0, 3))
        e.update(status="failed", reply_text=str(ex)[:300])
        _ledger(store, **e)
        raise
