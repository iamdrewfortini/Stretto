# SPDX-License-Identifier: Apache-2.0
"""VoiceCore: the single agent the person talks to. One turn = the person's words -> Muse Spark with tools (through the
gateway, role voice.core) -> at most MAX_ROUNDS tool rounds -> a short reply meant to be spoken. Every step is a bus event."""
import json, threading, time, uuid
from datetime import datetime

from runtime import fastpath
from runtime.tools import MUTATING, SCHEMAS, run_tool


def actions_for(calls):
    """UI actions the browser should take after a turn: go to a page the agent opened, refresh after any change."""
    acts = [{"action": "navigate", "page": c["result"]["navigate"]} for c in calls if c["ok"] and isinstance(c.get("result"), dict) and c["result"].get("navigate")]
    if any(c["ok"] and isinstance(c.get("result"), dict) and c["result"].get("hangup") for c in calls):
        acts.append({"action": "hangup"})
    if any(c["ok"] and c["name"] in MUTATING for c in calls):
        acts.append({"action": "refresh"})
    return acts

MAX_ROUNDS = 4
SYSTEM = ("You are the voice of Humanflow, a private time and focus assistant for one person. Your reply is spoken aloud: "
          "one or two short sentences, plain words, no lists, no markdown. You track time, tasks and resources only through "
          "your tools; never invent numbers. When the person states what they did or are doing, log or time it. "
          "If their goal is unclear, ask one short question. Their data is theirs alone. "
          "Act only on the person's latest message: everything earlier in the conversation is already done, so never "
          "repeat an earlier log, timer or task. A question is not a request to log time. "
          "Never start or stop a timer, log time or create a task unless the person explicitly asks; if you think one would help, ask first. "
          "When the person describes how the product should work, what is wrong, or an idea, save it with capture; when they want work "
          "handed to another agent or a local model, write create_job orders and export_jobs. You can open pages with open_page. "
          "Steer like a Socratic coach: you see measurements the person cannot, so ask one short question at a time that helps them "
          "notice where their attention is going and choose for themselves; ground every nudge in a measured number from the context; "
          "when they are drifting or stuck, gently point toward the best-ranked change or their most important open task; never lecture, "
          "never decide for them, and never give medical or mental-health advice.")


class VoiceCore:
    def __init__(self, gateway, tools, bus, history_turns=6, clock=time.time, fast=True):
        self.gw, self.tools, self.bus, self.n, self.clock, self.fast = gateway, tools, bus, history_turns, clock, fast
        self.history, self.lock = [], threading.Lock()

    def _context(self):
        s = self.tools.t_get_summary("today")
        acts = s.get("by_activity_min") or {}
        top = sorted(acts.items(), key=lambda kv: kv[1] or 0, reverse=True)[:3]
        open_tasks = self.tools.t_list_tasks()
        open_tasks = [t for t in open_tasks if t["status"] != "done"][:5]
        steer = ""
        try:  # what the agent knows that the person may not: measured leaks and the best-ranked change
            lk = self.tools.t_get_leaks()
            best = (lk.get("top_changes") or [None])[0]
            steer = f" Leak score {lk['leak_score']} (lower is better), leaking {lk['per_day_min']['total']:.0f} min/day."
            if best:
                steer += f" Best-ranked change: {best['text']} (+{best['winback_hours_year']:.0f} h/yr for {best['adopt_cost_min']:.0f} min setup)."
        except Exception:
            pass
        return (f"Now: {datetime.fromtimestamp(self.clock()).strftime('%A %H:%M')}. Today so far: {json.dumps(dict(top))}. "
                f"Open tasks: {json.dumps([t['title'] for t in open_tasks])}." + steer)

    def turn(self, text):
        with self.lock:  # one person, one conversation: turns are serial
            return self._turn(text)

    def _fast(self, tid, text, t0):
        """Answer common commands locally: no model call, no cost, milliseconds. None = not confidently matched."""
        hit = fastpath.match(text)
        if not hit:
            return None
        name, args = hit
        if name == "greet":
            result, ok = {}, True
        else:
            tool_msg, ok, result = run_tool(self.tools, {"id": "fast", "function": {"name": name, "arguments": json.dumps(args)}}, tid)
        reply = fastpath.reply(name, args, result)
        calls = [] if name == "greet" else [{"name": name, "args": json.dumps(args), "ok": ok, "result": result}]
        self.history = (self.history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-2 * self.n:]
        out = {"turn_id": tid, "reply": reply, "tool_calls": calls, "actions": actions_for(calls), "model": None, "path": "fast",
               "ms": round((time.perf_counter() - t0) * 1000, 2)}
        self.bus.emit("core.turn.completed", out, "runtime.core", correlation_id=tid)
        return out

    def _turn(self, text):
        tid, t0 = "turn_" + uuid.uuid4().hex[:12], time.perf_counter()
        self.bus.emit("core.turn.started", {"turn_id": tid, "text": text}, "runtime.core", correlation_id=tid)
        if self.fast:
            out = self._fast(tid, text, t0)
            if out:
                return out
        hist = self.history[-4:]  # short voice turns: the last 4 messages keep the model fast and cache-hot
        msgs = [{"role": "system", "content": SYSTEM + "\n\n" + self._context()}, *hist, {"role": "user", "content": text}]
        calls, model, reply = [], None, ""
        for _ in range(MAX_ROUNDS + 1):
            data, model, _rid = self.gw.complete({"role": "voice.core", "messages": msgs, "tools": SCHEMAS, "tool_choice": "auto",
                                                  "prompt_cache_key": "humanflow-voice-v1"})
            m = data["choices"][0]["message"]
            tcs = m.get("tool_calls") or []
            if not tcs or len(calls) >= MAX_ROUNDS * 4:
                reply = (m.get("content") or "").strip()
                break
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                tool_msg, ok, result = run_tool(self.tools, tc, tid)
                msgs.append(tool_msg)
                calls.append({"name": tc["function"]["name"], "args": tc["function"].get("arguments"), "ok": ok, "result": result})
                self.bus.emit("tool.result", {"turn_id": tid, **calls[-1]}, "runtime.core", correlation_id=tid)
        if not reply:
            reply = "Done." if calls and all(c["ok"] for c in calls) else "Sorry, I could not finish that."
        self.history = (self.history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-2 * self.n:]
        out = {"turn_id": tid, "reply": reply, "tool_calls": calls, "actions": actions_for(calls), "model": model, "path": "model", "ms": round((time.perf_counter() - t0) * 1000)}
        self.bus.emit("core.turn.completed", out, "runtime.core", correlation_id=tid)
        return out
