# SPDX-License-Identifier: Apache-2.0
"""Raw samples to blocks. Pure functions, no I/O. A block is one stretch in one app (or one site in a browser)."""
import hashlib
import re

FOCUS = {"Build", "Write", "Learn", "Plan", "Design", "Research"}
BROWSERS = re.compile(r"^(chrome|msedge|firefox|brave|opera|vivaldi|safari|arc|chromium|google chrome|microsoft edge)", re.I)
SITES = {"youtube": "youtube.com", "reddit": "reddit.com", "github": "github.com", "gitlab": "gitlab.com", "stack overflow": "stackoverflow.com",
         "gmail": "mail.google.com", "google docs": "docs.google.com", "google calendar": "calendar.google.com", "linkedin": "linkedin.com",
         "facebook": "facebook.com", "instagram": "instagram.com", "tiktok": "tiktok.com", "netflix": "netflix.com", "twitch": "twitch.tv",
         "discord": "discord.com", "claude": "claude.ai", "chatgpt": "chatgpt.com", "notion": "notion.so", "figma": "figma.com",
         "wikipedia": "wikipedia.org", "arxiv": "arxiv.org", "cerebral valley": "cerebralvalley.ai", "proxmox": "proxmox.local"}
DEFAULT_RULES = [
    ("app", r"^(code|cursor|pycharm|idea|webstorm|goland|clion|rider|devenv|sublime_text|notepad\+\+|xcode|android studio|vim|nvim|emacs)", "Build"),
    ("app", r"^(windowsterminal|wt|powershell|pwsh|cmd|conhost|terminal|iterm2?|wezterm|alacritty|kitty|gnome-terminal|konsole|wsl|ubuntu)", "Build"),
    ("app", r"^(winword|word|pages|libreoffice|obsidian|typora|notepad|textedit|onenote|logseq)", "Write"),
    ("app", r"^(excel|numbers|powerpnt|keynote|figma|photoshop|illustrator|premiere|resolve|blender|obs64?|ableton|reaper|audacity)", "Design"),
    ("app", r"^(git|shell)$", "Build"),
    ("app", r"^(slack|teams|ms-teams|discord|zoom|skype|telegram|whatsapp|signal|outlook|thunderbird|mail|messages)", "Communication"),
    ("app", r"^(spotify|vlc|steam|epicgameslauncher|netflix)", "Distraction"),
    ("domain", r"(^|\.)(github\.com|gitlab\.com|stackoverflow\.com|localhost|127\.0\.0\.1)$", "Build"),
    ("domain", r"(^|\.)(wikipedia\.org|arxiv\.org|docs\.google\.com|claude\.ai|chatgpt\.com|notion\.so|figma\.com)$", "Research"),
    ("domain", r"(^|\.)(youtube\.com|netflix\.com|twitch\.tv|reddit\.com|x\.com|twitter\.com|facebook\.com|instagram\.com|tiktok\.com)$", "Distraction"),
    ("domain", r"(^|\.)(mail\.google\.com|outlook\.office\.com|discord\.com|linkedin\.com)$", "Communication"),
    ("domain", r"(^|\.)calendar\.google\.com$", "Plan"),
]
_COMPILED = [(f, re.compile(p, re.I), c) for f, p, c in DEFAULT_RULES]
DEFAULT_SIG = hashlib.sha1(repr(DEFAULT_RULES).encode()).hexdigest()[:12]   # a change to the built-in rules invalidates cached days


def site_from_title(title):
    t = (title or "").lower()
    for name, dom in SITES.items():
        if name in t:
            return dom
    return ""


_MEMO = {}
_MEMO_MAX = 100_000


def classify(ev, user_rules=()):
    """Returns (category, key). key decides which samples merge into one block.
    Pure in (idle, app, domain, title, rules), and real data has few distinct combinations, so results are memoised."""
    mk = (ev.get("idle"), ev.get("app"), ev.get("domain"), ev.get("title"), tuple(user_rules))
    hit = _MEMO.get(mk)
    if hit is not None:
        return hit
    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[mk] = r = _classify(ev, user_rules)
    return r


def _classify(ev, user_rules=()):
    if ev.get("idle"):
        return "Idle", ("idle",)
    app = (ev.get("app") or "").lower().removesuffix(".exe")
    domain = (ev.get("domain") or "") or (site_from_title(ev.get("title")) if BROWSERS.match(app) else "")
    field = dict(app=app, domain=domain, title=ev.get("title") or "")
    for f, pat, cat in list(user_rules) + _COMPILED:
        pat = pat if hasattr(pat, "search") else re.compile(pat, re.I)
        if pat.search(field.get(f, "")):
            return cat, (app, domain if BROWSERS.match(app) else "")
    return ("Browsing" if BROWSERS.match(app) else "Other"), (app, domain if BROWSERS.match(app) else "")


def blocks(events, user_rules=(), gap=90, default_dur=5):
    """Merge consecutive same-key samples (gap seconds tolerance) into blocks. Seconds count sample coverage only."""
    out, cur = [], None
    multi = len({e.get("device") for e in events}) > 1                  # several computers: moving between them is a change of place
    for e in sorted(events, key=lambda e: e["ts"]):
        d = min(float(e.get("dur") or default_dur), gap)
        cat, key = classify(e, user_rules)
        if multi and key != ("idle",):
            key = key + (e.get("device"),)
        end = e["ts"] + d
        inp = e.get("inp")
        if cur and cur["key"] == key and e["ts"] - cur["end"] <= gap:
            cur["end"], cur["seconds"], cur["n"] = max(cur["end"], end), cur["seconds"] + d, cur["n"] + 1
            if inp is not None:
                cur["inp"], cur["inp_s"] = (cur["inp"] or 0) + inp, cur["inp_s"] + d     # inp_s: seconds that actually carry a count
        else:
            if cur:
                out.append(cur)
            dom = key[1] if len(key) > 1 else ""
            cur = dict(key=key, start=e["ts"], end=end, seconds=d, n=1, app=e["app"], domain=dom,
                       title=e.get("title", ""), category=cat, ctl=e.get("ctl", ""), inp=inp, inp_s=d if inp is not None else 0.0,
                       device=e.get("device", ""))
    if cur:
        out.append(cur)
    return out