"""Native permission model. What does THIS computer require before each capability works, is it granted, which operating-system
panel grants it, and what is the exact elevated command when one is needed?

Rules that make this safe:
  * Every panel and every elevated command comes from the fixed table in this file. Nothing here is built from server data, so a
    server can show these to a person but can never make the agent run anything.
  * Nothing elevates silently. `run` prints the exact command, a person types a confirmation, and only then the OS's own
    authorisation (Windows UAC, macOS administrator dialog, Linux polkit) asks the person again.
  * Checking a permission never reads user data: it asks the OS whether access is granted (or reports 'unknown')."""
import getpass
import os
import re
import shutil
import subprocess
import sys

from . import cfg as C

STATUS = ("granted", "missing", "unknown", "unsupported", "not_applicable")


def _run(argv, timeout=8):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def is_admin():
    try:
        if C.system() == "windows":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def _ax_trusted():
    """macOS: has the user granted this process Accessibility? Asks the OS; reads nothing."""
    try:
        import ctypes
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        return None


def _history_readable():
    from . import importers
    found = [i for i in importers.discover() if i.family == "browser-history"]
    if not found:
        return "not_applicable"
    return "granted" if all(os.access(i.path, os.R_OK) for i in found) else "missing"


def _username():
    u = re.sub(r"[^\w.\- ]", "", getpass.getuser())
    d = re.sub(r"[^\w.\-]", "", os.environ.get("USERDOMAIN", ""))
    return f"{d}\\{u}" if d else u


def _pkg_manager():
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            text = f.read().lower()
    except OSError:
        return None
    ids = " ".join(re.findall(r"^(?:id|id_like)=(.*)$", text, re.M))
    for key, mgr in (("debian", "apt"), ("ubuntu", "apt"), ("fedora", "dnf"), ("rhel", "dnf"), ("arch", "pacman"), ("suse", "zypper")):
        if key in ids:
            return mgr
    return None


def _ELEV_INNER():
    return f"Add-LocalGroupMember -Group 'Event Log Readers' -Member '{_username()}'"


def _ELEV_OUTER():
    """The command that asks Windows (UAC) to run the inner command elevated. Inner single quotes are doubled for PowerShell."""
    return "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-Command','" + _ELEV_INNER().replace("'", "''") + "'"


def _item(id, source, label, why, status, *, required=False, available=True, panel=None, elevated=None, note=""):
    return dict(id=id, source=source, label=label, why=why, status=status, required=required, available=available, panel=panel, elevated=elevated, note=note)


def _panel_windows(label, uri):
    return dict(label=label, uri=uri, argv=["cmd", "/c", "start", "", uri])


def _panel_mac(label, anchor):
    uri = "x-apple.systempreferences:com.apple.preference.security?" + anchor
    return dict(label=label, uri=uri, argv=["open", uri])


def detect():
    """The permission plan for this computer. Fixed table, live checks, no network."""
    s, items = C.system(), []
    if s == "windows":
        code, out = _run(["wevtutil", "gli", "System"])            # log INFO, not log content
        items += [
            _item("foreground-window", "collector", "See which program is in front and its title",
                  "Windows lets a normal program read this without any permission.", "granted", required=True,
                  note="Windows protects programs that run as administrator: while one is in front its title may be empty unless the agent also runs elevated. That is a Windows rule, not a bug."),
            _item("browser-history-files", "browser-history", "Read your browsers' history files (a copy, read-only)",
                  "The history databases are ordinary files in your own profile.", _history_readable(),
                  note="Chrome and Edge lock the file while open; Stretto reads a temporary copy."),
            _item("system-event-log", "power", "Read start-up, shutdown, sleep and wake times",
                  "The System event log records them. Reading it is allowed for normal users on most Windows installs.",
                  "granted" if code == 0 else "missing"),
            _item("security-log", "lock-unlock", "Also see when you lock and unlock the screen (planned, optional)",
                  "Lock and unlock events live in the Security log, which only administrators and the 'Event Log Readers' group may read.",
                  "granted" if (is_admin() or "event log readers" in _run(["whoami", "/groups"])[1].lower()) else "missing", available=False,
                  panel=None,
                  elevated=dict(description="Add your account to the 'Event Log Readers' group so the agent can read lock/unlock events without running as administrator. Sign out and in afterwards.",
                                display=_ELEV_INNER(), how="Windows asks you to approve in a UAC prompt",
                                argv=["powershell", "-NoProfile", "-Command", _ELEV_OUTER()])),
            _item("activity-history", "app-activity", "Windows activity history (planned, optional)",
                  "If you turn Activity History on, Windows keeps its own record of app use that Stretto could import for the days before it was installed.",
                  "unknown", available=False, panel=_panel_windows("Windows Settings: Activity history", "ms-settings:privacy-activityhistory")),
        ]
    elif s == "macos":
        ax = _ax_trusted()
        py = os.path.realpath(sys.executable)
        items += [
            _item("accessibility", "collector", "See window titles",
                  "macOS asks you to allow Accessibility before a program can read another program's window title. Without it Stretto sees the program name but not titles.",
                  "granted" if ax else "missing" if ax is False else "unknown", required=False,
                  panel=_panel_mac("System Settings: Privacy & Security > Accessibility", "Privacy_Accessibility"),
                  note=f"Switch on the program that runs the agent. Right now that is: {py}"),
            _item("automation-browsers", "collector", "See which site is open in Chrome, Safari, Edge or Brave",
                  "macOS asks you to allow Automation before the agent can ask a browser for its current address. Only the domain is kept.",
                  "unknown", panel=_panel_mac("System Settings: Privacy & Security > Automation", "Privacy_Automation"),
                  note="macOS shows its own prompt the first time; you can also switch it on here."),
            _item("browser-history-files", "browser-history", "Read your browsers' history files (a copy, read-only)",
                  "Chrome, Edge, Brave and Firefox keep history in ordinary files in your profile.", _history_readable()),
        ]
    else:
        wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"
        have = {t: bool(shutil.which(t)) for t in ("xdotool", "xprintidle")}
        mgr = _pkg_manager()
        cmds = {"apt": ["apt-get", "install", "-y"], "dnf": ["dnf", "install", "-y"], "pacman": ["pacman", "-S", "--noconfirm"], "zypper": ["zypper", "--non-interactive", "install"]}
        elev = None
        if mgr and not all(have.values()):
            argv = cmds[mgr] + [t for t, ok in have.items() if not ok]
            elev = dict(description="Install the small helper programs the agent uses to see the front window and idle time.",
                        display="sudo " + " ".join(argv), how="the system's own authorisation dialog (polkit) or your sudo password",
                        argv=["pkexec"] + argv if shutil.which("pkexec") else ["sudo"] + argv)
        items += [
            _item("display-session", "collector", "See the front window, its title and idle time",
                  "On Linux this needs an X11 session and two helper programs (xdotool, xprintidle).",
                  "unsupported" if wayland else "granted" if all(have.values()) and os.environ.get("DISPLAY") else "missing",
                  required=True, elevated=elev,
                  note="Wayland does not let programs read other windows. Choose an X11 session at login (for example 'Ubuntu on Xorg') to use window tracking." if wayland else ""),
            _item("browser-history-files", "browser-history", "Read your browsers' history files (a copy, read-only)",
                  "Browsers keep history in ordinary files in your home folder.", _history_readable()),
        ]
    missing = [i["id"] for i in items if i["required"] and i["available"] and i["status"] in ("missing", "unsupported")]
    return dict(os=s, os_label=C.os_label(), user=getpass.getuser(), admin=is_admin(), items=items, required_missing=missing, source="agent fixed table")


def open_panel(item_id):
    """Open the native settings page for an item. Harmless: it only shows a settings window."""
    for it in detect()["items"]:
        if it["id"] == item_id and it["panel"]:
            subprocess.Popen(it["panel"]["argv"])
            return True
    return False


def run_elevated(item_id):
    """Run an item's elevated command through the OS's own authorisation prompt. Caller must have confirmed with a person."""
    for it in detect()["items"]:
        if it["id"] == item_id and it["elevated"]:
            r = subprocess.run(it["elevated"]["argv"], timeout=600)
            return r.returncode
    return None


def public(plan):
    """The plan as sent to the server for display: no argv, only what a person needs to read."""
    out = dict(plan, items=[])
    for it in plan["items"]:
        c = dict(it)
        if c.get("panel"):
            c["panel"] = {k: v for k, v in c["panel"].items() if k != "argv"}
        if c.get("elevated"):
            c["elevated"] = {k: v for k, v in c["elevated"].items() if k != "argv"}
        out["items"].append(c)
    return out
