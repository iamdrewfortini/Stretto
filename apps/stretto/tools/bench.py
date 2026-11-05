"""Benchmark Stretto's read path on a large SYNTHETIC history. Usage: python3 tools/bench.py [days] [profile]
Synthetic means generated here, never real data. Reports wall time per stage so optimisation is driven by measurement."""
import cProfile
import datetime as dt
import os
import pstats
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from stretto import analyze, merge, segment
from stretto.server import Api
from stretto.store import Store

APPS = [("Code", "stretto - {f}.py", ""), ("chrome", "Docs - Google Docs", "docs.google.com"), ("chrome", "Merge request - GitHub", "github.com"),
        ("Slack", "Slack | team", ""), ("chrome", "Funny cats - YouTube", "youtube.com"), ("WindowsTerminal", "pwsh", ""),
        ("chrome", "Stack Overflow - question", "stackoverflow.com"), ("Outlook", "Inbox", ""), ("Notion", "Plan", ""), ("Figma", "design", "")]


def make_day(day0, rnd, hours=8):
    """Sticky random walk over apps: long stays, short detours. Returns sample dicts every 5 s."""
    out, t, end = [], day0 + 9 * 3600, day0 + (9 + hours) * 3600
    while t < end:
        app, title, dom = rnd.choice(APPS[:1] * 4 + APPS)                    # Code is the home base
        dwell = int(rnd.expovariate(1 / 240)) + 20
        f = rnd.choice("abcdefgh")
        for i in range(dwell // 5):
            if t >= end:
                break
            out.append(dict(ts=t, dur=5, app=app, title=title.format(f=f), domain=dom, idle=0, src="collector"))
            t += 5
    return out


def main(days=60, prof=False):
    import tempfile
    from stretto import daycache
    rnd = random.Random(1)
    today = dt.date.today()
    s = Store(os.path.join(tempfile.mkdtemp(), "bench.sqlite"))      # file-backed, so the worker pool is exercised
    t0 = time.time()
    n = 0
    for i in range(days, 0, -1):
        d0 = dt.datetime.combine(today - dt.timedelta(days=i), dt.time()).timestamp()
        n += s.ingest(make_day(d0, rnd), "collector", "bench")
    t_ing = time.time() - t0
    api = Api(s)
    print(f"events: {n:,} over {days} days   ingest: {t_ing:.1f}s ({n / t_ing:,.0f}/s)   cpus: {os.cpu_count()}")
    iso = (today - dt.timedelta(days=1)).isoformat()

    def timed(label, fn):
        t = time.time(); r = fn(); print(f"  {label:<52} {time.time() - t:6.2f}s"); return r
    print("per-day cache:")
    with_pool = daycache.PARALLEL_MIN
    daycache.PARALLEL_MIN = 10 ** 9
    timed("patterns, COLD, one process", lambda: api.patterns(days))
    s.x("DELETE FROM day_cache")
    daycache.PARALLEL_MIN = with_pool
    r = timed(f"patterns, COLD, worker pool (up to {daycache.MAX_WORKERS})", lambda: api.patterns(days))
    timed("patterns, WARM", lambda: api.patterns(days))
    timed("range(7), WARM", lambda: api.range(7))
    timed("one day view, WARM history", lambda: api.day(iso))
    s.ingest([dict(ts=dt.datetime.combine(today - dt.timedelta(days=2), dt.time()).timestamp() + 20 * 3600, dur=5, app="Code", title="x")], "collector", "bench")
    timed("patterns after ONE new event (1 day recomputed)", lambda: api.patterns(days))
    return r


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60, len(sys.argv) > 2)
