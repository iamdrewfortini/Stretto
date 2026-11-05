# SPDX-License-Identifier: Apache-2.0
"""Calendar integration components for Google Calendar, iCloud Calendar and Microsoft Outlook.
All three ecosystems import and export iCalendar (.ics), so that is the shipped, verifiable path: export planned
tasks + recorded focus sessions as one .ics, import any .ics back into planned tasks (deduplicated by UID).
Provider cards report their honest state: ICS always ready; live OAuth/CalDAV appear only when the operator has
configured credentials in the environment — never simulated as connected."""
import base64
import datetime as dt
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PROVIDERS = [
    dict(id="google", name="Google Calendar", how="ICS import/export today. Live sync needs GOOGLE_CALENDAR_CLIENT_ID in the server environment."),
    dict(id="icloud", name="iCloud Calendar", how="ICS import/export today. Read-only CalDAV sync needs ICLOUD_CALDAV_USER, ICLOUD_CALDAV_PASSWORD (app-specific) and ICLOUD_CALDAV_URL (calendar home) in the server environment."),
    dict(id="microsoft", name="Microsoft Outlook", how="ICS import/export today. Live sync needs MICROSOFT_GRAPH_CLIENT_ID in the server environment."),
]
ENV = {"google": "GOOGLE_CALENDAR_CLIENT_ID", "icloud": "ICLOUD_CALDAV_USER", "microsoft": "MICROSOFT_GRAPH_CLIENT_ID"}


def _configured(pid):
    return not caldav_missing() if pid == "icloud" else bool(os.environ.get(ENV[pid]))


def providers():
    return [dict(p, configured=_configured(p["id"]),
                 mode=("caldav-ready" if p["id"] == "icloud" else "oauth-ready") if _configured(p["id"]) else "ics") for p in PROVIDERS]


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
    text = re.sub(r"\r?\n[ \t]", "", str(text))            # RFC 5545 line unfolding: providers wrap long lines at 75 octets
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        uid = (re.search(r"^UID:(.+)$", block, re.M) or [None, ""])[1].strip()
        title = (re.search(r"^SUMMARY:(.+)$", block, re.M) or [None, ""])[1].strip()
        tzid = (re.search(r"DTSTART;[^:]*TZID=([^;:]+)", block) or [None, None])[1]
        raw = (re.search(r"^DTSTART[^:]*:(.+)$", block, re.M) or [None, ""])[1].strip()
        if not title or not raw:
            continue
        tz = dt.timezone.utc
        if tzid:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tzid.strip())
            except Exception:
                tz = dt.timezone.utc
        try:
            when = dt.datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz).timestamp()
        except ValueError:
            try:
                when = dt.datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=tz).timestamp()
            except ValueError:
                continue
        out.append(dict(uid=uid, title=title.replace("\\,", ",").replace("\\;", ";")[:200], start_ts=when))
    return out


def import_events(store, events_in):
    """The one dedupe path for every calendar import: our own exports (stretto-* UIDs) and any event already planned
    with the same title at the same start are skipped; the rest become planned tasks."""
    created = skipped = 0
    for ev in events_in:
        if ev["uid"].startswith("stretto-"):
            skipped += 1; continue
        if store.q("SELECT id FROM tasks WHERE title=? AND planned_start=?", (ev["title"], ev["start_ts"])):
            skipped += 1; continue
        store.ux("INSERT INTO tasks(title,planned_start,created) VALUES(?,?,?)", (ev["title"], ev["start_ts"], time.time())); created += 1
    return dict(created=created, skipped=skipped, seen=len(events_in))


# --- iCloud CalDAV, read-only ----------------------------------------------------------------------------------
# Only PROPFIND and REPORT are ever sent; nothing is written to the calendar server. Credentials come from the
# environment, travel only in an Authorization header that is never forwarded on redirect, and never appear in a
# return value, an exception message or a log line.
CALDAV_ENV = ("ICLOUD_CALDAV_USER", "ICLOUD_CALDAV_PASSWORD", "ICLOUD_CALDAV_URL")
CALDAV_MAX_BYTES = 5 * 1024 * 1024
CALDAV_WINDOW = (30 * 86400, 90 * 86400)       # look back 30 days, ahead 90
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}

PROPFIND_BODY = ('<?xml version="1.0" encoding="utf-8"?>'
                 '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>')


class CalDAVError(Exception):
    """A sync failure safe to show the caller: carries a short reason code and the HTTP status, never credentials."""
    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.reason, self.status = reason, status


def caldav_missing():
    """Names (never values) of the CalDAV env vars that are unset."""
    return [k for k in CALDAV_ENV if not os.environ.get(k)]


def _report_body(lo, hi):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{_fmt(lo)}" end="{_fmt(hi)}"/>'
            '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')


def caldav_request(method, url, user, password, body, depth):
    """One authenticated WebDAV call. The single network seam: tests replace this function."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise CalDAVError("https_required")
    req = urllib.request.Request(url, data=body.encode(), method=method)
    req.add_header("Content-Type", "application/xml; charset=utf-8")
    req.add_header("Depth", str(depth))
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_unredirected_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(CALDAV_MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise CalDAVError("unauthorized" if e.code in (401, 403) else "upstream_http_error", e.code) from None
    except (urllib.error.URLError, OSError):
        raise CalDAVError("upstream_unreachable") from None
    if len(data) > CALDAV_MAX_BYTES:
        raise CalDAVError("response_too_large")
    return data


def _multistatus(data):
    try:
        return ET.fromstring(data).findall("d:response", NS)
    except ET.ParseError:
        raise CalDAVError("bad_xml") from None


def calendar_urls(home_url, data):
    """Hrefs of the calendar collections in a Depth:1 PROPFIND multistatus, resolved against the home URL."""
    out = []
    for resp in _multistatus(data):
        href = (resp.findtext("d:href", "", NS) or "").strip()
        if href and resp.find(".//d:resourcetype/c:calendar", NS) is not None:
            u = urllib.parse.urljoin(home_url, href)
            if u not in out:
                out.append(u)
    return out


def calendar_data(data):
    """Every calendar-data payload (ICS text) in a REPORT multistatus."""
    return [el.text for el in (r.find(".//c:calendar-data", NS) for r in _multistatus(data)) if el is not None and el.text]


def caldav_fetch_ics(home_url, user, password, now=None):
    """PROPFIND the calendar home for its calendars, then REPORT each for VEVENTs in the window. Returns ICS texts."""
    now = time.time() if now is None else now
    body = _report_body(now - CALDAV_WINDOW[0], now + CALDAV_WINDOW[1])
    texts = []
    for cal in calendar_urls(home_url, caldav_request("PROPFIND", home_url, user, password, PROPFIND_BODY, 1)):
        texts += calendar_data(caldav_request("REPORT", cal, user, password, body, 1))
    return texts


def caldav_sync(store, now=None):
    """Read iCloud via CalDAV and import through the shared dedupe path. Raises CalDAVError("not_configured") when the
    environment lacks any of CALDAV_ENV."""
    if caldav_missing():
        raise CalDAVError("not_configured")
    user, password, url = (os.environ[k] for k in CALDAV_ENV)
    events_in = [ev for text in caldav_fetch_ics(url, user, password, now) for ev in parse_ics(text)]
    return import_events(store, events_in)
