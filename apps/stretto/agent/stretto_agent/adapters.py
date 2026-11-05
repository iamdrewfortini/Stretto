# SPDX-License-Identifier: Apache-2.0
"""Foreground-window capture per operating system, plus privacy filtering. Stdlib only.

Captured: front application, its window title, idle time, pointer position. NOT captured: keystrokes, screen contents, clipboard,
microphone, camera. Nothing here runs unless the person has accepted the 'host-system' notice (the run loop checks, and so does the server)."""
import os
import re
import subprocess
import sys

from . import cfg as C

PRIVATE_WINDOW = re.compile(r"(inprivate|incognito|private browsing|private window)", re.I)


def filter_sample(app, title, redact):
    """Privacy filter. Returns (app, title) or None to drop the sample entirely."""
    if PRIVATE_WINDOW.search(title or ""):
        return None
    hay = f"{app} {title}".lower()
    if any(p and p.lower() in hay for p in redact):
        return app, ""            # keep that time was spent in the app, never the title
    return app, title


# ---------------------------------------------------------------- Windows
def _win():
    import ctypes
    import ctypes.wintypes as wt
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetForegroundWindow.restype = wt.HWND
    u.GetWindowTextLengthW.argtypes = [wt.HWND]
    u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    k.OpenProcess.restype = wt.HANDLE
    k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k.CloseHandle.argtypes = [wt.HANDLE]

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

    class GTI(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND), ("hwndCapture", wt.HWND),
                    ("hwndMenuOwner", wt.HWND), ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]

    u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GTI)]
    st = dict(last=None, paths={})

    def capture():
        hwnd = u.GetForegroundWindow()
        li = LII()
        li.cbSize = ctypes.sizeof(li)
        u.GetLastInputInfo(ctypes.byref(li))
        idle = (k.GetTickCount() - li.dwTime) & 0xFFFFFFFF
        inputs = 0 if st["last"] is None or st["last"] == li.dwTime else 1       # did the OS register input since the previous look?
        st["last"] = li.dwTime
        pt = wt.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        app = title = ctl = path = ""
        if hwnd:
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            pid = wt.DWORD()
            tid = u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = k.OpenProcess(0x1000, False, pid.value)      # PROCESS_QUERY_LIMITED_INFORMATION: no admin needed
            if h:
                size, b = wt.DWORD(1024), ctypes.create_unicode_buffer(1024)
                if k.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(size)):
                    path = b.value
                    app = os.path.basename(path)
                k.CloseHandle(h)
            gi = GTI()
            gi.cbSize = ctypes.sizeof(gi)
            if u.GetGUIThreadInfo(tid, ctypes.byref(gi)) and gi.hwndFocus:           # which CONTROL has the focus: its class name, never its text
                cb = ctypes.create_unicode_buffer(128)
                if u.GetClassNameW(gi.hwndFocus, cb, 128):
                    ctl = cb.value
        return dict(app=app, title=title, domain="", idle_ms=int(idle), cx=pt.x, cy=pt.y, ctl=ctl, inputs=inputs, path=path)

    def version_info(path):
        """Display name, publisher and version of a program, from the version resource inside its own .exe."""
        if path in st["paths"]:
            return st["paths"][path]
        info = {}
        try:
            v = ctypes.windll.version
            size = v.GetFileVersionInfoSizeW(path, None)
            blob = ctypes.create_string_buffer(size) if size else None
            if blob is not None and v.GetFileVersionInfoW(path, 0, size, blob):
                lp, ln = ctypes.c_void_p(), wt.UINT()
                if v.VerQueryValueW(blob, "\\VarFileInfo\\Translation", ctypes.byref(lp), ctypes.byref(ln)) and ln.value >= 4:
                    lang, cp = ctypes.cast(lp, ctypes.POINTER(ctypes.c_ushort * 2)).contents

                    def q(name):
                        p, n = ctypes.c_wchar_p(), wt.UINT()
                        if v.VerQueryValueW(blob, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{name}", ctypes.byref(p), ctypes.byref(n)) and p.value:
                            return p.value
                        return ""
                    info = dict(display=q("FileDescription") or q("ProductName"), publisher=q("CompanyName"), version=q("ProductVersion"))
        except Exception:
            info = {}
        st["paths"][path] = info
        return info
    capture.version_info = version_info
    return capture


# ---------------------------------------------------------------- macOS
_MAC_SCRIPT = ('tell application "System Events"\n set p to first application process whose frontmost is true\n set n to name of p\n set t to ""\n'
               ' try\n set t to name of front window of p\n end try\n return n & "\\n" & t\nend tell')
_BROWSER_URL = {"Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
                "Safari": 'tell application "Safari" to get URL of current tab of front window',
                "Microsoft Edge": 'tell application "Microsoft Edge" to get URL of active tab of front window',
                "Brave Browser": 'tell application "Brave Browser" to get URL of active tab of front window'}


def _osascript(src, timeout=3):
    return subprocess.run(["osascript", "-e", src], capture_output=True, text=True, timeout=timeout).stdout.strip()


def _mac():
    def capture():
        out = _osascript(_MAC_SCRIPT).split("\n", 1)
        app, title = out[0], (out[1] if len(out) > 1 else "")
        domain = ""
        if app in _BROWSER_URL:
            from urllib.parse import urlsplit
            try:
                domain = (urlsplit(_osascript(_BROWSER_URL[app])).hostname or "").lower()
            except Exception:
                domain = ""
        io = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', io)
        return dict(app=app, title=title, domain=domain, idle_ms=int(int(m.group(1)) / 1_000_000) if m else 0, cx=None, cy=None)
    return capture


# ---------------------------------------------------------------- Linux (X11 via xdotool/xprintidle)
def _which(name):
    from shutil import which
    return which(name)


def _linux():
    if not os.environ.get("DISPLAY") or not _which("xdotool"):
        return None

    def run(*a):
        return subprocess.run(list(a), capture_output=True, text=True, timeout=3).stdout.strip()

    def capture():
        title = run("xdotool", "getactivewindow", "getwindowname")
        pid = run("xdotool", "getactivewindow", "getwindowpid")
        app = ""
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                    app = f.read().strip()
            except OSError:
                pass
        idle = int(run("xprintidle") or 0) if _which("xprintidle") else 0
        loc = re.search(r"x:(\d+) y:(\d+)", run("xdotool", "getmouselocation"))
        return dict(app=app, title=title, domain="", idle_ms=idle, cx=int(loc.group(1)) if loc else None, cy=int(loc.group(2)) if loc else None)
    return capture


def make():
    """Returns a capture function, or (None, reason) when this system cannot be observed."""
    s = C.system()
    fn = _win() if s == "windows" else _mac() if s == "macos" else _linux()
    if fn is None:
        return None, ("Wayland or missing xdotool: install xdotool (and optionally xprintidle) on an X11 session" if s == "linux" else "unsupported")
    return fn, ""


def poll_interval():
    """How often to look at the front window. Windows is cheap to poll, so it sees fast switches; the others spawn a helper per look."""
    return 0.25 if C.system() == "windows" else 1.0


class FocusTracker:
    """Turns frequent looks at the front window into exact STAYS with real start times and durations, so every focus shift is measured
    when it happened instead of rounded to a 5 s grid. A stay ends when the app, window title, focused control or site changes, when the
    person goes idle, or after flush_s of the same stay (so long stays still reach the server regularly).
    Private windows produce no stay at all. Input ticks are kept only when count_inputs is on (the input-activity notice was accepted)."""

    def __init__(self, cfg, count_inputs=False, flush_s=5.0):
        self.cfg, self.count_inputs, self.flush_s, self.cur = cfg, count_inputs, flush_s, None

    def _key(self, snap):
        if snap["idle_ms"] >= self.cfg["idle_after_s"] * 1000:
            return ("idle", "", "", "")
        f = filter_sample(snap["app"], snap["title"], self.cfg["redact"])
        if f is None or not f[0]:
            return None
        return (re.sub(r"\.exe$", "", f[0], flags=re.I), f[1], snap.get("ctl", ""), snap.get("domain", ""))

    def _close(self, now):
        c = self.cur
        dur = now - c["start"]
        if dur < 0.05:
            return None
        app, title, ctl, dom = c["key"]
        idle = app == "idle"
        return dict(ts=c["start"], dur=round(min(dur, 3600.0), 3), app=app, title=title, domain=dom, idle=int(idle), ctl=ctl,
                    inp=c["inp"] if (self.count_inputs and not idle) else None, cx=c["cx"], cy=c["cy"])

    def update(self, now, snap):
        key, out = self._key(snap), []
        if self.cur and (key != self.cur["key"] or now - self.cur["start"] >= self.flush_s):
            s = self._close(now)
            if s:
                out.append(s)
            self.cur = None
        if key is not None and self.cur is None:
            self.cur = dict(key=key, start=now, inp=0, cx=snap.get("cx"), cy=snap.get("cy"))
        if self.cur:
            self.cur["inp"] += int(snap.get("inputs") or 0)
            self.cur["cx"], self.cur["cy"] = snap.get("cx"), snap.get("cy")
        return out

    def flush(self, now):
        s = self._close(now) if self.cur else None
        self.cur = None
        return [s] if s else []


def sample(capture, cfg, now):
    """One privacy-filtered sample, or None. Idle samples carry no app or title."""
    raw = capture()
    if raw["idle_ms"] >= cfg["idle_after_s"] * 1000:
        return dict(ts=now, dur=cfg["interval"], app="idle", title="", domain="", idle=1, cx=raw["cx"], cy=raw["cy"])
    f = filter_sample(raw["app"], raw["title"], cfg["redact"])
    if f is None or not f[0]:
        return None
    return dict(ts=now, dur=cfg["interval"], app=f[0].removesuffix(".exe") if hasattr(str, "removesuffix") else re.sub(r"\.exe$", "", f[0], flags=re.I),
                title=f[1], domain=raw["domain"], idle=0, cx=raw["cx"], cy=raw["cy"])
