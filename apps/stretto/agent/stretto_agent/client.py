"""HTTP client for the Stretto server, and the offline spool. A batch is deleted from disk only after the server confirms it."""
import json
import os
import time
import urllib.error
import urllib.request

from . import cfg as C


class ConsentRequired(Exception):
    def __init__(self, family):
        super().__init__(f"consent required: {family}")
        self.family = family


class Client:
    def __init__(self, server, token="", timeout=20, device_key=""):
        self.server, self.token, self.device_key, self.timeout = server.rstrip("/"), token, device_key, timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # local server: never via a proxy

    def _call(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.device_key:                       # an enrolled agent proves itself with its own key, never the master token
            headers["X-Stretto-Device-Key"] = self.device_key
        elif self.token:
            headers["X-Stretto-Token"] = self.token
        req = urllib.request.Request(self.server + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            data = {}
            try:
                data = json.loads(e.read() or b"{}")
            except ValueError:
                pass
            if e.code == 403 and data.get("error") == "consent_required":
                raise ConsentRequired(data.get("family", "?")) from None
            raise RuntimeError(f"server answered {e.code}: {data.get('error', '')}") from None

    def get(self, path):
        return self._call("GET", path)

    def post(self, path, body):
        return self._call("POST", path, body)

    def consent(self, device):
        return self.get(f"/api/consent?device={device}")["families"]


class Spool:
    """Batches waiting to be sent. Survives restarts and offline periods."""

    def __init__(self, base=None):
        self.dir = C.path("spool", base)
        os.makedirs(self.dir, exist_ok=True)

    def add(self, body):
        name = os.path.join(self.dir, f"{time.time():.3f}-{os.getpid()}.json")
        tmp = name + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f)
        os.replace(tmp, name)

    def pending(self):
        return sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))

    def flush(self, client):
        """Send oldest first; stop at the first failure so order is kept. Returns (sent, left)."""
        sent = 0
        for name in self.pending():
            p = os.path.join(self.dir, name)
            with open(p, encoding="utf-8") as f:
                body = json.load(f)
            try:
                client.post("/api/ingest", body)
            except ConsentRequired:
                raise
            except (RuntimeError, OSError):
                break
            os.remove(p)
            sent += 1
        return sent, len(self.pending())
