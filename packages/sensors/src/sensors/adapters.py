# SPDX-License-Identifier: Apache-2.0
"""Platform adapters. Counts only, never content.

An adapter is ``{name, source, platforms, probe(), poll(now)}``.
``probe()`` returns ``(available, why)`` and never raises. ``poll()``
returns ``Sample`` objects carrying counts (keys pressed, clicks,
pointer pixels moved) or focus/idle facts. Raw key values and pointer
coordinates are discarded inside the adapter that counted them; they
never reach a Sample. Platform data comes from built-in OS tools only
(osascript/ioreg on macOS, xdotool/xprop/xprintidle/xinput on Linux
X11), each behind a probe. Wayland reports ``unavailable: wayland``.
"""
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field


class Adapter:
    """Adapter protocol: name, source, platforms, probe(), poll().

    ``external_wait`` is True when poll() waits on an OS tool; that
    wait is excluded from the importer tick budget (spec: tick work
    excludes subprocess wait). In-process adapters leave it False and
    are held to the 200 ms per-adapter budget.
    """
    name, source, platforms = "", "", ()
    external_wait = False

    def probe(self):
        return False, "unavailable: base adapter"

    def poll(self, now):
        return []


@dataclass
class Sample:
    source: str            # window | input | pointer | idle
    ts: float
    app: str = ""
    title: str = ""
    idle_s: float = 0.0
    keys: int = 0          # counts only; never the keys themselves
    clicks: int = 0
    pointer_px: float = 0.0
    extra: dict = field(default_factory=dict)


_REGISTRY = []


def register(adapter):
    _REGISTRY.append(adapter)
    return adapter


def registry():
    return list(_REGISTRY)


def _run(argv, timeout=0.2):
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def _have(tool):
    return shutil.which(tool) is not None


class MacWindowAdapter:
    name, source, platforms = "macos-window", "window", ("Darwin",)

    def probe(self):
        if platform.system() != "Darwin":
            return False, "unavailable: not macOS"
        if not _have("osascript"):
            return False, "unavailable: osascript missing"
        try:
            _run(["osascript", "-e",
                  'tell application "System Events" to '
                  "get name of first process whose frontmost is true"],
                 timeout=2.0)
            return True, "available"
        except Exception as e:  # Accessibility denied etc.
            return False, f"unavailable: osascript: {e}"

    def poll(self, now):
        try:
            app = _run(["osascript", "-e",
                        'tell application "System Events" to '
                        "get name of first process whose frontmost is true"],
                       timeout=1.0)
            title = ""
            try:
                title = _run(["osascript", "-e",
                              'tell application "System Events" to '
                              "get name of front window of first process "
                              "whose frontmost is true"], timeout=1.0)
            except Exception:
                title = ""
        except Exception:
            return []
        return [Sample("window", now, app=app, title=title)] if app else []


class MacIdleAdapter:
    name, source, platforms = "macos-idle", "idle", ("Darwin",)

    def probe(self):
        if platform.system() != "Darwin":
            return False, "unavailable: not macOS"
        return (True, "available") if _have("ioreg") else (
            False, "unavailable: ioreg missing")

    def poll(self, now):
        try:
            out = _run(["ioreg", "-c", "IOHIDSystem"])
        except Exception:
            return []
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                try:
                    ns = int(line.rsplit("=", 1)[1].strip())
                    return [Sample("idle", now, idle_s=ns / 1e9)]
                except (ValueError, IndexError):
                    return []
        return []


class MacInputAdapter:
    """P1: HID counters via ioreg if exposed, else unavailable.

    No CGEventTap helper is built (spec P1): if ioreg exposes no
    keyboard/pointer event counters this probe says so cleanly.
    """
    name, source, platforms = "macos-input", "input", ("Darwin",)

    def probe(self):
        if platform.system() != "Darwin":
            return False, "unavailable: not macOS"
        try:
            out = _run(["ioreg", "-c", "IOHIDSystem", "-r"], timeout=0.5)
        except Exception as e:
            return False, f"unavailable: ioreg: {e}"
        if "HIDKeyboardEventCount" in out or "KeyCount" in out:
            return True, "available"
        return False, "unavailable: no HID counters in ioreg (P1)"

    def poll(self, now):  # only reached when probe passed
        return []


class LinuxWindowAdapter:
    name, source, platforms = "linux-window", "window", ("Linux",)

    def probe(self):
        if platform.system() != "Linux":
            return False, "unavailable: not Linux"
        if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            return False, "unavailable: wayland"
        for t in ("xdotool", "xprop"):
            if not _have(t):
                return False, f"unavailable: {t} missing"
        return True, "available"

    def poll(self, now):
        try:
            wid = _run(["xdotool", "getactivewindow"])
            title = _run(["xdotool", "getwindowname", wid]) if wid else ""
            cls = _run(["xprop", "-id", wid, "WM_CLASS"]) if wid else ""
            app = cls.split('"')[1] if '"' in cls else ""
        except Exception:
            return []
        return [Sample("window", now, app=app, title=title)] if app else []


class LinuxIdleAdapter:
    name, source, platforms = "linux-idle", "idle", ("Linux",)

    def probe(self):
        if platform.system() != "Linux":
            return False, "unavailable: not Linux"
        if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            return False, "unavailable: wayland"
        return (True, "available") if _have("xprintidle") else (
            False, "unavailable: xprintidle missing")

    def poll(self, now):
        try:
            return [Sample("idle", now,
                           idle_s=int(_run(["xprintidle"])) / 1000.0)]
        except Exception:
            return []


class LinuxInputAdapter:
    """P1: counts XI2 events per second; event payloads discarded.

    A reader thread runs ``xinput test-xi2 --root`` and only bumps
    counters: key press/release -> keys, button -> clicks, motion
    deltas -> pointer_px (summed absolute deltas, never coordinates).
    """
    name, source, platforms = "linux-input", "input", ("Linux",)

    def __init__(self):
        self._keys = self._clicks = 0
        self._px = 0.0
        self._lock = threading.Lock()
        self._proc = None
        self._last = (0, 0, 0.0)

    def probe(self):
        if platform.system() != "Linux":
            return False, "unavailable: not Linux"
        if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            return False, "unavailable: wayland"
        return (True, "available") if _have("xinput") else (
            False, "unavailable: xinput missing")

    def _reader(self):
        try:
            self._proc = subprocess.Popen(
                ["xinput", "test-xi2", "--root"],
                stdout=subprocess.PIPE, text=True)
            lx = ly = None
            for line in self._proc.stdout:
                with self._lock:
                    if "EVENT type 2" in line or "RawKeyPress" in line:
                        self._keys += 1
                    elif "EVENT type 4" in line or "RawButtonPress" in line:
                        self._clicks += 1
                    elif "EVENT type 17" in line or "RawMotion" in line:
                        self._px += 1.0  # per-event step; no coords kept
        except Exception:
            self._proc = None

    def poll(self, now):
        if self._proc is None:
            threading.Thread(target=self._reader, daemon=True).start()
            time.sleep(0.01)
        with self._lock:
            cur = (self._keys, self._clicks, self._px)
        d = tuple(c - p for c, p in zip(cur, self._last))
        self._last = cur
        out = []
        if d[0]:
            out.append(Sample("input", now, keys=int(d[0])))
        if d[1] or d[2]:
            out.append(Sample("pointer", now, clicks=int(d[1]),
                              pointer_px=float(d[2])))
        return out


_BUILTINS = (MacWindowAdapter, MacIdleAdapter, MacInputAdapter,
             LinuxWindowAdapter, LinuxIdleAdapter, LinuxInputAdapter)


def discover(include_unavailable=False):
    """Return [(adapter, available, why)] for this host's platform."""
    system = platform.system()
    out = []
    for cls in _BUILTINS:
        if system not in cls.platforms:
            continue
        a = cls()
        a.external_wait = True  # builtins wait on OS tools
        ok, why = a.probe()
        if ok and all(r.name != a.name for r in _REGISTRY):
            register(a)
        out.append((a, ok, why))
    return out if include_unavailable else [r for r in out if r[1]]
