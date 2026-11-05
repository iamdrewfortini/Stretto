# SPDX-License-Identifier: Apache-2.0
"""Route table for the Stretto frontend's /api/* contract. Domain modules register handlers with @route; the gateway
dispatches. A handler takes (ctx, req) and returns a JSON-serialisable object, or raises ApiError(status, message).
ctx = {"bus", "tools", "core", "gateway", "registry", "clock", "store"}; req = {"method", "path", "params", "query", "body"}.
`store` is a small dict for state that is not in the ledger (settings, projects, habits, consent); persist it via the bus.
Live events: register translators with @event_translator; each maps one bus event to zero or more (name, data) pairs for
the Stretto stream, whose names are hello, timer, block and day."""
import re

ROUTES = []          # (method, compiled regex, param names, handler)
TRANSLATORS = []     # fn(ctx, bus_event) -> list[(event_name, data)]


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message); self.status = status


def route(method, pattern):
    """@route("GET", "/api/tasks/{id}"): {name} matches one path segment."""
    names = re.findall(r"{(\w+)}", pattern)
    rx = re.compile("^" + re.sub(r"{\w+}", r"([^/]+)", re.escape(pattern).replace(r"\{", "{").replace(r"\}", "}")) + "$")

    def deco(fn):
        ROUTES.append((method.upper(), rx, names, fn))
        return fn
    return deco


def event_translator(fn):
    TRANSLATORS.append(fn)
    return fn


def dispatch(ctx, method, path, query, body):
    for m, rx, names, fn in ROUTES:
        mt = rx.match(path)
        if mt and m == method.upper():
            req = {"method": method.upper(), "path": path, "params": dict(zip(names, mt.groups())), "query": query, "body": body or {}}
            return 200, fn(ctx, req)
    if any(rx.match(path) for _, rx, _, _ in ROUTES):
        return 405, {"error": f"{method} not allowed on {path}"}
    return 404, {"error": f"no such endpoint: {path}"}


def translate(ctx, ev):
    out = []
    for fn in TRANSLATORS:
        try:
            out.extend(fn(ctx, ev) or [])
        except Exception:  # a broken translator must not break the stream
            pass
    return out


def load():
    """Import every domain module so its routes register. Missing modules are skipped (built in parallel)."""
    loaded = []
    for name in ("stretto_api_day", "stretto_api_meta"):
        try:
            __import__(f"runtime.{name}")
            loaded.append(name)
        except ImportError:
            pass
    return loaded
