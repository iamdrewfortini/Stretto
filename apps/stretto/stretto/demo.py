# SPDX-License-Identifier: Apache-2.0
"""A SIMULATED workday for demos and tests. Everything it creates is stored with src='simulated' and shown as such."""
import random

# (app, title, minutes, idle)
SCRIPT = [
    ("Code", "stretto - store.py", 25, 0), ("chrome", "sqlite docs - Google Docs", 2, 0), ("Code", "stretto - store.py", 4, 0),
    ("chrome", "sqlite docs - Google Docs", 1, 0), ("Code", "stretto - store.py", 3, 0), ("chrome", "sqlite docs - Google Docs", 1, 0),
    ("Code", "stretto - store.py", 4, 0), ("Slack", "Slack | team", 3, 0), ("Code", "stretto - server.py", 20, 0),
    ("chrome", "Funny cats - YouTube", 6, 0), ("Code", "stretto - server.py", 18, 0), ("", "", 15, 1),
    ("Code", "stretto - app.js", 9, 0), ("chrome", "Merge request - GitHub", 2, 0), ("Slack", "Slack | team", 2, 0),
    ("Code", "stretto - app.js", 8, 0), ("chrome", "Merge request - GitHub", 2, 0), ("Slack", "Slack | team", 2, 0),
    ("Code", "stretto - app.js", 8, 0), ("chrome", "Merge request - GitHub", 2, 0), ("Slack", "Slack | team", 2, 0),
    ("Code", "stretto - app.js", 22, 0), ("chrome", "Reddit - front page", 5, 0), ("Code", "stretto - tests", 25, 0),
]


def samples(day_start, start_hour=9, seed=7, step=5):
    rnd, out, t = random.Random(seed), [], day_start + start_hour * 3600
    for app, title, minutes, idle in SCRIPT:
        for _ in range(int(minutes * 60 / step)):
            out.append(dict(ts=t, dur=step, app=app or "idle", title=title, idle=idle, cx=rnd.randint(0, 1919), cy=rnd.randint(0, 1079)))
            t += step
    return out