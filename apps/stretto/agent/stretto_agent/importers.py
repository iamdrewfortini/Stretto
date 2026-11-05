# SPDX-License-Identifier: Apache-2.0
"""Read-only historical importers. Each one:
  * is incremental: it returns only what is newer than the saved cursor, so it can run every few minutes at no cost;
  * copies the source database to a temporary file and reads the copy (the browser keeps its own file locked);
  * stores only domain + title per visit: paths, query strings, content, cookies and passwords are never read into a sample;
  * does nothing about consent itself. The caller (cli) checks the server's consent record BEFORE calling read().
probe() is the only call allowed before consent, and it never opens a database: existence and size only."""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from . import cfg as C

CHROME_EPOCH = 11_644_473_600          # seconds between 1601-01-01 and 1970-01-01
BATCH = 5000
EST_CAP, EST_LAST = 120, 30            # when a browser did not record the stay: gap to the next visit (max 120 s), 30 s for the last


def _roots(kind):
    s, h = C.system(), os.path.expanduser("~")
    la, ra = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")
    table = {
        "chrome": dict(windows=[f"{la}/Google/Chrome/User Data"], macos=[f"{h}/Library/Application Support/Google/Chrome"], linux=[f"{h}/.config/google-chrome"]),
        "edge": dict(windows=[f"{la}/Microsoft/Edge/User Data"], macos=[f"{h}/Library/Application Support/Microsoft Edge"], linux=[f"{h}/.config/microsoft-edge"]),
        "brave": dict(windows=[f"{la}/BraveSoftware/Brave-Browser/User Data"], macos=[f"{h}/Library/Application Support/BraveSoftware/Brave-Browser"], linux=[f"{h}/.config/BraveSoftware/Brave-Browser"]),
        "firefox": dict(windows=[f"{ra}/Mozilla/Firefox/Profiles"], macos=[f"{h}/Library/Application Support/Firefox/Profiles"], linux=[f"{h}/.mozilla/firefox"]),
    }
    return [r for r in table[kind][s] if r and os.path.isdir(r)]


def _copy(path):
    """Copy a database (and its journal files) to a private temp dir. The caller deletes the dir."""
    d = tempfile.mkdtemp(prefix="stretto-")
    dst = os.path.join(d, "db.sqlite")
    shutil.copy2(path, dst)
    for ext in ("-wal", "-journal", "-shm"):
        if os.path.exists(path + ext):
            shutil.copy2(path + ext, dst + ext)
    return d, dst


def _domain(url):
    try:
        u = urlsplit(url)
    except ValueError:
        return ""
    if u.scheme not in ("http", "https"):
        return ""                                   # file://, chrome://, about: and the like are not "sites"
    return (u.hostname or "").lower().removeprefix("www.") if hasattr(str, "removeprefix") else (u.hostname or "").lower()


def _durations(rows):
    """rows: [(ts, dur_or_None, ...)] sorted by ts. Fill missing stays from the gap to the next visit."""
    out = []
    for i, r in enumerate(rows):
        ts, dur = r[0], r[1]
        if not dur or dur <= 0:
            gap = (rows[i + 1][0] - ts) if i + 1 < len(rows) else EST_LAST
            dur = max(1.0, min(gap if gap > 0 else 1.0, EST_CAP))
        out.append(min(dur, 3600.0))
    return out


class Importer:
    family = "browser-history"

    def __init__(self, name, path):
        self.name, self.path = name, path

    def probe(self):
        try:
            return dict(source=self.name, family=self.family, path=self.path, bytes=os.path.getsize(self.path))
        except OSError:
            return None


class ChromiumHistory(Importer):
    """Chrome, Edge, Brave: History -> urls + visits. Cursor = last visit id."""

    def read(self, cursor):
        last = int(cursor or 0)
        d, db = _copy(self.path)
        try:
            con = sqlite3.connect(db)
            try:
                mx = con.execute("SELECT COALESCE(MAX(id),0) FROM visits").fetchone()[0]
                if mx < last:                       # history was cleared and rebuilt: start over (uids prevent double counting)
                    last = 0
                rows = con.execute("SELECT v.id, v.visit_time, v.visit_duration, u.url, u.title FROM visits v JOIN urls u ON u.id=v.url "
                                   "WHERE v.id>? ORDER BY v.id LIMIT ?", (last, BATCH)).fetchall()
            finally:
                con.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)
        if not rows:
            return [], str(last), []
        vis = sorted(((vt / 1e6 - CHROME_EPOCH, vd / 1e6 if vd else None, url, title or "", vid) for vid, vt, vd, url, title in rows), key=lambda r: (r[0], r[4]))
        durs = _durations(vis)
        browser = self.name.split("-")[0]
        out = [dict(ts=t, dur=du, app=browser, title=ti, domain=_domain(url)) for (t, _, url, ti, _), du in zip(vis, durs) if _domain(url)]
        return out, str(rows[-1][0]), []


class FirefoxHistory(Importer):
    """places.sqlite -> moz_historyvisits + moz_places. Cursor = last visit id. Firefox records no stay time."""

    def read(self, cursor):
        last = int(cursor or 0)
        d, db = _copy(self.path)
        try:
            con = sqlite3.connect(db)
            try:
                mx = con.execute("SELECT COALESCE(MAX(id),0) FROM moz_historyvisits").fetchone()[0]
                if mx < last:
                    last = 0
                rows = con.execute("SELECT v.id, v.visit_date, p.url, p.title FROM moz_historyvisits v JOIN moz_places p ON p.id=v.place_id "
                                   "WHERE v.id>? ORDER BY v.id LIMIT ?", (last, BATCH)).fetchall()
            finally:
                con.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)
        if not rows:
            return [], str(last), []
        vis = sorted(((vd / 1e6, None, url, title or "", vid) for vid, vd, url, title in rows if vd), key=lambda r: (r[0], r[4]))
        durs = _durations(vis)
        out = [dict(ts=t, dur=du, app="firefox", title=ti, domain=_domain(url)) for (t, _, url, ti, _), du in zip(vis, durs) if _domain(url)]
        return out, str(rows[-1][0]), []


class WindowsPower(Importer):
    """System event log (readable without admin): start-up, shutdown, sleep, wake. Cursor = last event time (unix seconds)."""
    family = "host-system"
    IDS = {12: "boot", 13: "shutdown", 41: "crash", 42: "sleep", 107: "resume"}

    def __init__(self):
        super().__init__("power", "Windows System event log")

    def probe(self):
        return dict(source=self.name, family=self.family, path=self.path, bytes=None) if C.system() == "windows" else None

    def read(self, cursor):
        since = float(cursor or 0) or 0
        ps = ("$s=[DateTimeOffset]::FromUnixTimeSeconds([int64]%d).UtcDateTime; "
              "Get-WinEvent -FilterHashtable @{LogName='System'; Id=12,13,41,42,107; StartTime=$s} -MaxEvents %d -ErrorAction SilentlyContinue | "
              "Sort-Object TimeCreated | ForEach-Object { '{0}|{1}' -f $_.Id, ([DateTimeOffset]$_.TimeCreated).ToUnixTimeSeconds() }") % (since + 1, BATCH)
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=120).stdout
        power, newest = [], since
        for line in out.splitlines():
            try:
                i, t = line.strip().split("|")
                if int(i) in self.IDS:
                    power.append(dict(ts=float(t), kind=self.IDS[int(i)]))
                    newest = max(newest, float(t))
            except ValueError:
                continue
        return [], str(int(newest)), power


PRUNE = {".git", "node_modules", "venv", ".venv", "__pycache__", ".cache", "target", "dist", "build", ".tox", "Library", "AppData"}


def _git(*args, timeout=60):
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*"] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


class GitHistory(Importer):
    """Commit TIMES and the repository NAME for commits made by you. Never messages, diffs, file names or authors' other details.
    Cursor = newest commit time (unix seconds). A commit is a point in time, so each becomes a 60 s marker, flagged as estimated."""
    family = "work-history"

    def __init__(self, name, path, email):
        super().__init__(name, path)
        self.email = email

    def probe(self):
        return dict(source=self.name, family=self.family, path=self.path, bytes=None)

    def read(self, cursor):
        since = int(float(cursor or 0))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(max(0, since - 1)))
        code, out = _git("-C", self.path, "log", "--all", f"--author={self.email}", f"--since={stamp}", "--format=%at", "--max-count=%d" % BATCH)
        if code != 0:
            return [], str(since), []
        times = sorted({int(x) for x in out.split() if x.isdigit()})
        if not times:
            return [], str(since), []
        repo = os.path.basename(self.path.rstrip("/\\"))
        return [dict(ts=float(t), dur=60.0, app="git", title=repo, domain="") for t in times], str(times[-1]), []


class ShellHistory(Importer):
    """Timestamps from a shell history file. The command text is dropped as each line is read and never stored or sent.
    zsh (EXTENDED_HISTORY: ': <epoch>:<secs>;cmd') and bash (HISTTIMEFORMAT: '#<epoch>' lines). Cursor = newest timestamp."""
    family = "work-history"

    def __init__(self, name, path, kind):
        super().__init__(name, path)
        self.kind = kind

    def read(self, cursor):
        since = float(cursor or 0)
        stamps = set()
        with open(self.path, "rb") as f:
            for raw in f:
                line = raw[:40].decode("utf-8", "ignore")      # only the head of the line: enough for the timestamp, too short to hold a secret
                if self.kind == "zsh" and line.startswith(": "):
                    head = line[2:].split(":", 1)[0]
                elif self.kind == "bash" and line.startswith("#"):
                    head = line[1:].strip()
                else:
                    continue
                if head.isdigit() and int(head) > since:
                    stamps.add(int(head))
        if not stamps:
            return [], str(int(since)), []
        ts = sorted(stamps)[:BATCH]
        return [dict(ts=float(t), dur=30.0, app="shell", title="", domain="") for t in ts], str(ts[-1]), []


class LoginSessions(Importer):
    """Your own logins to THIS computer from `last` (Linux): when you were connected. Not addresses, not other users.
    A session is presence, not activity, so each is capped at 2 hours. Cursor = newest login time."""
    family = "work-history"
    LINE = None

    def __init__(self):
        super().__init__("login-sessions", "last (login records)")

    def probe(self):
        return dict(source=self.name, family=self.family, path=self.path, bytes=None) if C.system() == "linux" and shutil.which("last") else None

    @staticmethod
    def parse(text, now=None):
        import re
        pat = re.compile(r"^(\S+)\s+(\S+)\s+(?:\S+\s+)?(\w{3} \w{3}\s+\d+ \d\d:\d\d:\d\d \d{4})(?:\s+-\s+|\s+)(\w{3} \w{3}\s+\d+ \d\d:\d\d:\d\d \d{4}|crash|down|still logged in)")
        out = []
        for line in text.splitlines():
            m = pat.match(line)
            if not m:
                continue
            try:
                t0 = time.mktime(time.strptime(m.group(3), "%a %b %d %H:%M:%S %Y"))
                end = m.group(4)
                t1 = time.mktime(time.strptime(end, "%a %b %d %H:%M:%S %Y")) if end[0].isalpha() and end not in ("crash", "down", "still logged in") else (now or time.time())
            except ValueError:
                continue
            out.append((t0, max(1.0, min(t1 - t0, 7200.0)), "ssh" if m.group(2).startswith("pts") else "console"))
        return out

    def read(self, cursor):
        import getpass
        since = float(cursor or 0)
        code, out = _git_free(["last", "-F", "-w", getpass.getuser()])
        rows = [r for r in self.parse(out) if r[0] > since]
        if not rows:
            return [], str(int(since)), []
        rows.sort()
        return [dict(ts=t, dur=d, app="login", title=kind, domain="") for t, d, kind in rows], str(int(rows[-1][0])), []


def _git_free(argv, timeout=20):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _git_repos(roots, limit=200, depth=3):
    found = []
    for root in roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        base = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, _ in os.walk(root):
            if ".git" in dirs:
                found.append(cur)
                dirs[:] = []
                if len(found) >= limit:
                    return found
                continue
            if cur.count(os.sep) - base >= depth:
                dirs[:] = []
            else:
                dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith(".")]
    return found


def discover_work():
    """work-history importers for this computer. Opens no repository content: it only locates .git folders and shell history files."""
    found = []
    code, email = _git("config", "--global", "user.email")
    email = email.strip()
    if code == 0 and email:
        roots = [r for r in os.environ.get("STRETTO_GIT_ROOTS", "").split(os.pathsep) if r] or ["~/DEV", "~/Projects", "~/src", "~/code", "~/work"]
        for repo in _git_repos(roots):
            found.append(GitHistory(f"git-history:{os.path.basename(repo)}", repo, email))
    home = os.path.expanduser("~")
    for kind, name in (("zsh", ".zsh_history"), ("bash", ".bash_history")):
        p = os.path.join(home, name)
        if os.path.isfile(p):
            found.append(ShellHistory(f"shell-history:{kind}", p, kind))
    li = LoginSessions()
    if li.probe():
        found.append(li)
    return found


def discover():
    """Every importer this system could run. Opens nothing."""
    found = []
    for browser in ("chrome", "edge", "brave"):
        for root in _roots(browser):
            for prof in ["Default"] + [os.path.basename(p) for p in glob.glob(os.path.join(root, "Profile *"))]:
                p = os.path.join(root, prof, "History")
                if os.path.isfile(p):
                    found.append(ChromiumHistory(f"{browser}-history:{prof}", p))
    for root in _roots("firefox"):
        for p in glob.glob(os.path.join(root, "*", "places.sqlite")):
            found.append(FirefoxHistory(f"firefox-history:{os.path.basename(os.path.dirname(p))}", p))
    if C.system() == "windows":
        found.append(WindowsPower())
    found.extend(discover_work())
    return found
