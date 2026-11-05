# SPDX-License-Identifier: Apache-2.0
"""Calendar integration components for Google Calendar, iCloud Calendar and Microsoft Outlook.
All three ecosystems import and export iCalendar (.ics), so that is the shipped, verifiable path: export planned
tasks + recorded focus sessions as one .ics, import any .ics back into planned tasks (deduplicated by UID).
Provider cards report their honest state: ICS always ready; live OAuth/CalDAV appear only when the operator has
configured credentials in the environment — never simulated as connected."""
import datetime as dt
import os
import re

PROVIDERS = [
    dict(id="google", name="Google Calendar", how="ICS import/export today. Live sync needs GOOGLE_CALENDAR_CLIENT_ID in the server environment."),
    dict(id="icloud", name="iCloud Calendar", how="ICS import/export today. Live sync needs an app-specific password via ICLOUD_CALDAV_USER in the server environment."),
    dict(id="microsoft", name="Microsoft Outlook", how="ICS import/export today. Live sync needs MICROSOFT_GRAPH_CLIENT_ID in the server environment."),
]
ENV = {"google": "GOOGLE_CALENDAR_CLIENT_ID", "icloud": "ICLOUD_CALDAV_USER", "microsoft": "MICROSOFT_GRAPH_CLIENT_ID"}


def providers():
    return [dict(p, configured=bool(os.environ.get(ENV[p["id"]])), mode="oauth-ready" if os.environ.get(ENV[p["id"]]) else "ics") for p in PROVIDERS]


def _esc(s):
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")[:200]


def _fmt(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def export_ics(tasks, sessions):
    """Planned tasks (planned_start) + focus sessions as VEVENTs. UIDs are stable so re-import dedupes."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Stretto//Calendar 1.0//EN", "CALSCALE:GREGORIAN"]
    for t in tasks:
        if not t.get("planned_start"):
            continue
        start = float(t["planned_start"]); end = start + (t.get("est_min") or 25) * 60
        lines += ["BEGIN:VEVENT", f"UID:stretto-task-{t['id']}@stretto.local", f"DTSTART:{_fmt(start)}", f"DTEND:{_fmt(end)}",
                  f"SUMMARY:{_esc(t['title'])}", "END:VEVENT"]
    for s in sessions:
        start = float(s["start"]); end = float(s.get("end") or start + 1500)
        lines += ["BEGIN:VEVENT", f"UID:stretto-session-{s['id']}@stretto.local", f"DTSTART:{_fmt(start)}", f"DTEND:{_fmt(end)}",
                  f"SUMMARY:{_esc(s.get('task_title') or s.get('label') or 'Focus session')}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def parse_ics(text):
    """Minimal VEVENT reader: UID, SUMMARY, DTSTART. Returns [{uid, title, start_ts}]. Bad events are skipped."""
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", str(text), re.S):
        uid = (re.search(r"^UID:(.+)$", block, re.M) or [None, ""])[1].strip()
        title = (re.search(r"^SUMMARY:(.+)$", block, re.M) or [None, ""])[1].strip()
        raw = (re.search(r"^DTSTART[^:]*:(.+)$", block, re.M) or [None, ""])[1].strip()
        if not title or not raw:
            continue
        try:
            when = dt.datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            try:
                when = dt.datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()
            except ValueError:
                continue
        out.append(dict(uid=uid, title=title.replace("\\,", ",").replace("\\;", ";")[:200], start_ts=when))
    return out
