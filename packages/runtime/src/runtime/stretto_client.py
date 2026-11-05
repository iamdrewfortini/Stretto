# SPDX-License-Identifier: Apache-2.0
"""Server-to-server client for the Stretto API on loopback, so voice tools change the real app (timer, tasks), not a copy.
The token is read from Stretto's data folder (STRETTO_TOKEN_FILE); it is never logged or returned."""
import http.client, json
from urllib.parse import urlsplit


class StrettoClient:
    def __init__(self, url, token_file, timeout=5.0):
        u = urlsplit(url)
        self.host, self.port, self.timeout = u.hostname, u.port or 80, timeout
        self.token_file = token_file

    def _token(self):
        with open(self.token_file, encoding="utf-8") as f:
            return f.read().strip()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            data = None if body is None else json.dumps(body)
            conn.request(method, path, body=data, headers={"Content-Type": "application/json", "X-Stretto-Token": self._token()})
            r = conn.getresponse(); raw = r.read()
            out = json.loads(raw or b"{}")
            if r.status >= 400:
                raise RuntimeError(out.get("error") or f"Stretto {r.status}")
            return out
        finally:
            conn.close()
