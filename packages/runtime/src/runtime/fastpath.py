# SPDX-License-Identifier: Apache-2.0
"""Local fast path. Common spoken commands are parsed and executed on this machine with no model call, so the
reply is ready in milliseconds and costs nothing. Anything not matched with confidence returns None and the
voice core sends it to the model. The parser is deliberately strict: a wrong fast answer is worse than a slow right one."""
import re

ACTIVITY = [  # (spoken words, ledger category); first match wins, so specific phrases come first
    (r"deep work|focus(?:ed|ing)?|coding|programming|writing|design(?:ing)?|building", "focus"),
    (r"meetings?|calls?|stand-?ups?|sync|one on one|1:1", "meeting"),
    (r"e-?mails?|slack|chat(?:ting)?|messages?|messaging|comms", "comms"),
    (r"search(?:ing)?|looking for|research(?:ing)?", "search"),
    (r"wait(?:ing)?|blocked|stuck", "wait"),
    (r"admin|paperwork|expenses|invoic(?:es|ing)", "admin"),
]
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
       "twenty five": 25, "thirty five": 35, "half an": 0.5, "half a": 0.5}
NUMBER = r"(\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, NUM), key=len, reverse=True)) + r")"


def _norm(text):
    t = text.lower().strip()
    t = re.sub(r"[^\w\s:'.-]", " ", t)
    return re.sub(r"\s+", " ", t).strip(" .")


def _activity(t):
    for words, cat in ACTIVITY:
        if re.search(rf"\b(?:{words})\b", t):
            return cat
    return None


def _minutes(t):
    m = re.search(rf"\b{NUMBER}\s*(hours?|hrs?|h|minutes?|mins?|m)\b", t)
    if not m:
        return None
    n = float(m.group(1)) if m.group(1)[0].isdigit() else NUM[m.group(1)]
    mins = n * 60 if m.group(2).startswith("h") else n
    return int(round(mins)) if 1 <= mins <= 600 else None


def _plural(n, word):
    return f"{n:g} {word}" + ("" if n == 1 else "s")


def match(text):
    """Return (tool_name, args) or None. Pure function: no side effects, so it can be tested and timed in isolation."""
    t = _norm(text)
    if not t or len(t) > 160:
        return None
    if re.fullmatch(r"(hi|hello|hey|hey there|good (morning|afternoon|evening))( humanflow)?", t):
        return ("greet", {})
    m = re.search(r"\b(?:open|go to|take me to|switch to)\s+(?:the\s+|my\s+)?(today|focus|tasks|calendar|paths|reports|goals|habits|insights|leaks|privacy|devices|settings)(?:\s+page)?\b", t)
    if m:
        return ("open_page", {"page": m.group(1)})
    if re.search(r"\bleak(s|ing|ed)?\b|leak score|how much time (am i|do i|have i) (los|wast)|what should i (change|fix|improve)", t):
        return ("get_leaks", {})
    if re.search(r"how('s| is| was)? (my )?day|\bsummary\b|how am i doing|where did my time go", t):
        return ("get_summary", {"range": "today"})
    if re.search(r"\b(list|what are|show)\b.*\btasks?\b|\bmy tasks\b", t):
        return ("list_tasks", {})
    m = re.match(r"(?:add|create|new) (?:a )?task(?: to)?[: ]+(.{3,120}?)(?:,? (?:about|around|for|taking) " + NUMBER + r"\s*(hours?|minutes?|mins?))?$", t)
    if m:
        args = {"title": m.group(1).strip(" ,")}
        if m.group(2):
            n = float(m.group(2)) if m.group(2)[0].isdigit() else NUM[m.group(2)]
            args["estimate_min"] = int(n * 60 if m.group(3).startswith("h") else n)
        return ("create_task", args)
    if re.search(r"\b(stop|end|pause|finish)\b.*\btimer\b|\b(i'?m|i am) done\b", t):
        return ("stop_timer", {})
    if re.search(r"\bstart\b.*\btimer\b|\b(start|starting|begin|beginning)\b", t):
        act = _activity(t)
        return ("start_timer", {"activity": act}) if act else None
    if re.search(r"\b(log|logged|add|record|track|spent|was in|i was|i did|i've been|been)\b", t):
        mins, act = _minutes(t), _activity(t)
        if mins and act:
            return ("log_time", {"activity": act, "minutes": mins})
    return None


def reply(tool, args, result):
    """Short spoken reply for a fast-path result. Numbers come only from the tool result."""
    if tool == "greet":
        return "Hi, I'm listening."
    if "error" in (result if isinstance(result, dict) else {}):
        return "There's no timer running." if tool == "stop_timer" else "I couldn't do that."
    if tool == "log_time":
        return f"Logged {_plural(result['minutes'], 'minute')} of {result['activity']}."
    if tool == "start_timer":
        return f"{result['activity'].capitalize()} timer started."
    if tool == "stop_timer":
        return f"Stopped. {_plural(result['minutes'], 'minute')} of {result['activity']}."
    if tool == "create_task":
        return f"Added: {result['title']}."
    if tool == "list_tasks":
        open_ = [x["title"] for x in result if x["status"] != "done"]
        return "No open tasks." if not open_ else f"{len(open_)} open: " + "; ".join(open_[:3]) + "."
    if tool == "open_page":
        return f"Opening {result['navigate']}." if "navigate" in result else "I couldn't open that page."
    if tool == "get_leaks":
        per_day = result["per_day_min"]["total"]
        if not per_day:
            return f"Leak score {result['leak_score']}. No leaks measured yet; log some switching, waiting or searching."
        year = result["compounded"]["year"]
        out = (f"Leak score {result['leak_score']}, lower is better. About {per_day:.0f} minutes a day, "
               f"which is {year['hours']:.0f} hours a year, about ${year['usd']:,.0f}.")
        if result["top_changes"]:
            c = result["top_changes"][0]
            out += f" Best change: {c['text'].rstrip('.')}. That wins back {c['winback_hours_year']:.0f} hours a year for {c['adopt_cost_min']:.0f} minutes of setup."
        return out
    if tool == "get_summary":
        by = result.get("by_activity_min") or {}
        if not by:
            return "Nothing logged yet today."
        top = sorted(by.items(), key=lambda kv: -kv[1])[:3]
        parts = ", ".join(f"{_plural(v, 'minute')} {k}" for k, v in top)
        run = result.get("running_timer")
        return f"Today: {parts}." + (f" {run['activity'].capitalize()} timer is running." if run else "")
    return "Done."
