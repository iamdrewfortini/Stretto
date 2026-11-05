# SPDX-License-Identifier: Apache-2.0
"""Realtime voice bridge: browser mic (PCM s16le over WS) -> Meta realtime ASR -> VoiceCore.

The gateway process owns this module: it calls start_voice_thread(core, bus, env)
once at startup (see Integration notes in the task). Per-connection work lives in
bridge(), which is testable without network: pass fakes for browser_ws and
asr_connect.
"""
import asyncio
import ipaddress
import json
import os
import threading
from urllib.parse import urlsplit

ASR_MODEL = "muse-voice-transcribe-1.0"
ACK_TIMEOUT_S = 10.0
HOLD_S_DEFAULT = 0.7
FILLERS = {"um", "uh", "er", "like"}


def _hold_seconds(hold_s=None):
    """Stutter-debounce hold: env VOICE_HOLD_S, default 0.7 s. Explicit arg wins (tests)."""
    if hold_s is not None:
        return float(hold_s)
    try:
        return float(os.environ.get("VOICE_HOLD_S", HOLD_S_DEFAULT))
    except (TypeError, ValueError):
        return HOLD_S_DEFAULT


def _clean_utterance(text):
    """Strip leading/trailing fillers (um, uh, er, like, you know) and collapse
    immediate word repeats ('I I want' -> 'I want'). Mid-sentence words are kept."""
    toks = text.split()

    def _word(tok):
        return tok.strip(" ,.;:!?\"'()[]").lower()

    def _is_filler(tok):
        return _word(tok) in FILLERS

    def _is_you_know(i):
        return i + 1 < len(toks) and _word(toks[i]) == "you" and _word(toks[i + 1]) == "know"

    while toks:
        if _is_you_know(0):
            del toks[0:2]
        elif _is_filler(toks[0]):
            del toks[0]
        else:
            break
    while toks:
        if len(toks) >= 2 and _is_you_know(len(toks) - 2):
            del toks[-2:]
        elif _is_filler(toks[-1]):
            del toks[-1]
        else:
            break
    out = []
    for tok in toks:
        norm = _word(tok)
        if out and norm and norm == _word(out[-1]):
            continue  # stuttered repeat: keep the first
        out.append(tok)
    return " ".join(out)


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_env(env):
    """Raise SystemExit unless this host may hold the mic socket and call Meta ASR."""
    if env.get("RUNTIME_MODE") != "local":
        raise SystemExit("refusing voice bridge: RUNTIME_MODE must be 'local'")
    bind = env.get("VOICE_BIND", "127.0.0.1:8788") or "127.0.0.1:8788"
    try:
        host, port_s = bind.rsplit(":", 1)
        port = int(port_s)
    except ValueError:
        raise SystemExit(f"refusing voice bridge: bad VOICE_BIND {bind!r}")
    if not _is_loopback(host):
        raise SystemExit(f"refusing voice bridge: VOICE_BIND host {host!r} is not loopback")
    url = env.get("META_ASR_URL", "")
    u = urlsplit(url)
    allow = {h.strip() for h in env.get("EGRESS_ALLOWLIST", "").split(",") if h.strip()}
    if u.scheme != "wss" or not u.hostname or u.hostname not in allow:
        raise SystemExit(f"refusing voice bridge: META_ASR_URL {url!r} is not an allowlisted wss host")
    return host, port


def start_voice_thread(core, bus, env):
    """Serve WS /v1/voice on VOICE_BIND in a daemon thread with its own asyncio loop."""
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    host, port = _check_env(env)
    asr_url = env["META_ASR_URL"]
    api_key = env.get("MODEL_API_KEY", "") or env.get("META_API_KEY", "")

    async def _handler(ws):
        await bridge(ws, core, bus, lambda: connect(asr_url, max_size=None), api_key)

    def _run():
        async def _main():
            async with serve(_handler, host, port):
                await asyncio.Future()  # serve forever; daemon thread dies with the process
        asyncio.run(_main())

    t = threading.Thread(target=_run, name="voice-bridge", daemon=True)
    t.start()
    return t


def _handshake(api_key):
    return {"authorization": {"accessToken": "Bearer " + api_key},
            "audioEncoding": "PCM_16KHZ", "model": ASR_MODEL,
            "mode": "ENDPOINTING", "partialMode": "CUMULATIVE",
            "emitAudioProgress": False}


async def bridge(browser_ws, core, bus, asr_connect, api_key, sample_rate=16000, hold_s=None):
    """One browser voice session. browser_ws speaks {send,recv}; asr_connect()
    returns an awaitable of a connected upstream websocket with the same interface."""
    try:
        first = await browser_ws.recv()
    except Exception:
        return
    try:
        start = json.loads(first) if isinstance(first, str) else {}
    except ValueError:
        start = {}
    if not isinstance(start, dict) or start.get("type") != "start":
        await _send(browser_ws, None, {"type": "error", "message": "expected {\"type\":\"start\"} first"})
        return
    if isinstance(start.get("sample_rate"), int) and start["sample_rate"] > 0:
        sample_rate = start["sample_rate"]
    bus.emit("voice.session.started", {"sample_rate": sample_rate}, "runtime.voice")

    lock = asyncio.Lock()  # one sender at a time on the browser socket
    holder = {}
    turns = asyncio.Queue()
    hold = _hold_seconds(hold_s)
    pending = []  # stutter debounce: finals joined here until HOLD_S of silence
    holder["hold_task"] = None

    def _cancel_hold():
        t = holder.get("hold_task")
        if t is not None and not t.done():
            t.cancel()
        holder["hold_task"] = None

    async def _flush_pending():
        """Run ONE turn on the joined pending utterance (cleaned), then clear it."""
        _cancel_hold()
        if not pending:
            return
        joined = _clean_utterance(" ".join(pending))
        pending.clear()
        if not joined.strip():
            return
        await _send(browser_ws, lock, {"type": "final", "text": joined})
        bus.emit("voice.utterance.final", {"text": joined}, "runtime.voice")
        turns.put_nowait(joined)  # worker serialises core.turn calls

    def _schedule_hold():
        _cancel_hold()

        async def _fire():
            await asyncio.sleep(hold)
            holder["hold_task"] = None
            await _flush_pending()

        holder["hold_task"] = asyncio.create_task(_fire())

    async def _open():
        up = await asr_connect()
        await up.send(json.dumps(_handshake(api_key)))
        try:
            ack_raw = await asyncio.wait_for(up.recv(), ACK_TIMEOUT_S)
        except Exception as e:
            raise ConnectionError(f"no ASR ack: {type(e).__name__}")
        try:
            ack = json.loads(ack_raw) if isinstance(ack_raw, str) else {}
        except ValueError:
            ack = {}
        if not isinstance(ack, dict) or not ack.get("sessionId"):
            raise ConnectionError("bad ASR ack")
        return up

    async def _reopen(reason):
        # Upstream error or unexpected close: tell the browser, then try once more.
        bus.emit("voice.error", {"code": reason[0], "message": reason[1]}, "runtime.voice")
        await _send(browser_ws, lock, {"type": "error", "message": reason[1]})
        if holder.get("reopened"):
            return False
        holder["reopened"] = True
        try:
            holder["up"] = await _open()
            return True
        except Exception as e:
            bus.emit("voice.error", {"code": "reopen-failed", "message": type(e).__name__}, "runtime.voice")
            return False

    async def _turn_worker():
        while True:
            text = await turns.get()
            if text is None:
                turns.task_done()
                return
            try:
                await _send(browser_ws, lock, {"type": "thinking"})
                res = await asyncio.to_thread(core.turn, text)
                names = [c.get("name", "") for c in res.get("tool_calls", [])]
                await _send(browser_ws, lock, {"type": "reply", "text": res.get("reply", ""),
                                               "tools": names, "ms": res.get("ms", 0)})
                for act in res.get("actions", []):  # the agent acts on the app: open a page, refresh after a change
                    await _send(browser_ws, lock, dict(act, type="action"))
            except Exception as e:
                await _send(browser_ws, lock, {"type": "error", "message": f"turn failed: {type(e).__name__}"})
            finally:
                turns.task_done()

    async def _browser_to_upstream():
        # Forward PCM unchanged; on stop send endStream and keep reading until close.
        while True:
            try:
                msg = await browser_ws.recv()
            except Exception:
                return
            if isinstance(msg, bytes):
                try:
                    await holder["up"].send(msg)
                except Exception:
                    pass  # upstream broken; _upstream_to_browser reopens
            else:
                try:
                    obj = json.loads(msg)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "stop":
                    holder["stopped"] = True
                    try:
                        await holder["up"].send(json.dumps({"type": "endStream"}))
                    except Exception:
                        pass

    async def _upstream_to_browser():
        while True:
            try:
                msg = await holder["up"].recv()
            except Exception as e:
                code = getattr(e, "code", None) or "closed"
                if holder.get("stopped"):
                    return  # close after our endStream is the expected end of session
                if await _reopen((code, "asr connection closed")):
                    continue
                return
            if isinstance(msg, bytes):
                continue  # upstream speaks JSON text; ignore anything else
            try:
                ev = json.loads(msg)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            kind = ev.get("type")
            if kind is None:
                continue  # sessionId ack and friends carry no type
            elif kind == "speechStart":
                bus.emit("voice.speech.start", {"turn_id": ev.get("turnId"),
                                                "audio_ms": ev.get("audioProcessedMs")}, "runtime.voice")
                _cancel_hold()  # person is still speaking: keep waiting
            elif kind == "transcript":
                text = ev.get("transcript", "")
                if text:
                    await _send(browser_ws, lock, {"type": "partial", "text": text})
                    _cancel_hold()  # fresh speech: keep waiting
            elif kind == "speechEnd":
                pass
            elif kind == "speechComplete":
                text = ev.get("transcript", "") or ""
                if not text.strip():
                    continue  # ignore empty/whitespace finals
                pending.append(text.strip())
                _schedule_hold()  # one turn when HOLD_S of silence follows
            elif kind == "audioProgress":
                pass
            elif kind == "error":
                if await _reopen(("error", ev.get("message") or "asr error")):
                    continue
                return

    try:
        holder["up"] = await _open()
    except Exception as e:
        bus.emit("voice.error", {"code": "connect-failed", "message": type(e).__name__}, "runtime.voice")
        await _send(browser_ws, lock, {"type": "error", "message": "could not reach speech recognition"})
        bus.emit("voice.session.ended", {}, "runtime.voice")
        return
    await _send(browser_ws, lock, {"type": "ready"})

    worker = asyncio.create_task(_turn_worker())
    to_up = asyncio.create_task(_browser_to_upstream())
    from_up = asyncio.create_task(_upstream_to_browser())
    try:
        await asyncio.wait({to_up, from_up}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        to_up.cancel()
        from_up.cancel()
        await asyncio.gather(to_up, from_up, return_exceptions=True)
        ht = holder.get("hold_task")
        if ht is not None and not ht.done():
            ht.cancel()
            await asyncio.gather(ht, return_exceptions=True)
            holder["hold_task"] = None
        await _flush_pending()  # a stop during the hold still speaks what was heard
        try:
            await holder["up"].close()
        except Exception:
            pass
        await turns.join()  # let the queued turns speak before we hang up
        turns.put_nowait(None)
        await worker
        bus.emit("voice.session.ended", {}, "runtime.voice")


async def _send(ws, lock, obj):
    raw = json.dumps(obj)
    try:
        if lock is None:
            await ws.send(raw)
        else:
            async with lock:
                await ws.send(raw)
    except Exception:
        pass
