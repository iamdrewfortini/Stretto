# SPDX-License-Identifier: Apache-2.0
"""Agent configuration and paths. Stdlib only, Python 3.8+."""
import json
import os
import platform
import socket
import sys
import uuid

DEFAULTS = dict(server="http://127.0.0.1:8760", token_file="", device="", device_name="", interval=5, idle_after_s=120,
                import_every_s=1800, enabled_sources=[], redact=["1password", "keepass", "bitwarden", "lastpass", "dashlane", "enpass", "nordpass", "keeper"])


def system():
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def config_dir():
    if os.environ.get("STRETTO_AGENT_HOME"):      # lets tests and trial runs keep their config out of the user's profile
        return os.environ["STRETTO_AGENT_HOME"]
    if system() == "windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StrettoAgent")
    if system() == "macos":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "StrettoAgent")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "stretto-agent")


def path(name, base=None):
    d = base or config_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def load(base=None):
    p = path("config.json", base)
    cfg = dict(DEFAULTS)
    try:
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if not cfg["device"]:
        cfg["device"] = uuid.uuid4().hex[:12]    # stable id for this computer; the server keys everything by it
        cfg["device_name"] = socket.gethostname()[:60]
        save(cfg, base)
    return cfg


def save(cfg, base=None):
    with open(path("config.json", base), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def token(cfg):
    if not cfg.get("token_file"):
        return ""
    try:
        with open(os.path.expanduser(cfg["token_file"]), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def device_key(cfg):
    if not cfg.get("device_key_file"):
        return ""
    try:
        with open(os.path.expanduser(cfg["device_key_file"]), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_secret(path_, text):
    """Write a secret readable only by the current user."""
    fd = os.open(path_, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def os_label():
    return f"{platform.system()} {platform.release()}"[:40]
