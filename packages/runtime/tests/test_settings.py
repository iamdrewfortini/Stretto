# SPDX-License-Identifier: Apache-2.0
import json
import os
import stat
import tempfile
import unittest

from runtime.gateway import apply_consent, consent_state, store_key


class SettingsKey(unittest.TestCase):
    def test_stores_key_without_echoing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, "runtime.env")
            with open(env, "w", encoding="utf-8") as f:
                f.write("RUNTIME_MODE=local\nMODEL_API_KEY=\n")
            n, fp = store_key(env, "x" * 24)
            body = open(env, encoding="utf-8").read()
            self.assertIn("MODEL_API_KEY=" + "x" * 24, body)
            self.assertIn("RUNTIME_MODE=local", body)
            self.assertEqual(stat.S_IMODE(os.stat(env).st_mode), 0o600)
            self.assertEqual(n, 24)
            self.assertNotIn("x" * 24, fp)

    def test_short_key_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, "runtime.env")
            with self.assertRaises(ValueError):
                store_key(env, "short")


class SettingsConsent(unittest.TestCase):
    def test_grant_then_revoke_roundtrip_and_titles_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "consent.json")
            apply_consent(path, "set_titles", [], titles=True, now=100.0)
            ev = apply_consent(path, "grant", ["window", "idle"],
                               ttl_s=3600.0, now=100.0)
            self.assertEqual(ev["action"], "grant")
            state = consent_state(path, now=200.0)
            self.assertTrue(state["sources"]["window"])
            self.assertTrue(state["sources"]["idle"])
            self.assertFalse(state["sources"]["input"])
            self.assertTrue(state["titles"])
            apply_consent(path, "revoke", ["window"], now=300.0)
            state = consent_state(path, now=300.0)
            self.assertFalse(state["sources"]["window"])
            self.assertTrue(state["sources"]["idle"])
            self.assertTrue(state["titles"])  # grant/revoke keep prefs
            apply_consent(path, "revoke", None, now=400.0)
            state = consent_state(path, now=400.0)
            self.assertFalse(any(state["sources"].values()))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            raw = json.load(open(path, encoding="utf-8"))
            self.assertIn("grants", raw)

    def test_unknown_source_and_bad_ttl_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "consent.json")
            with self.assertRaises(ValueError):
                apply_consent(path, "grant", ["camera"], ttl_s=60.0, now=0.0)
            with self.assertRaises(ValueError):
                apply_consent(path, "grant", ["window"], ttl_s=0.0, now=0.0)

    def test_expired_grant_reads_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "consent.json")
            apply_consent(path, "grant", ["window"], ttl_s=10.0, now=0.0)
            self.assertFalse(consent_state(path, now=11.0)["sources"]["window"])


class SettingsHttp(unittest.TestCase):
    def test_settings_page_key_and_consent_over_http(self):
        import io
        import urllib.request
        from http.server import ThreadingHTTPServer

        from runtime.bus import EventBus
        from runtime.gateway import Gateway, make_handler
        from runtime.registry import Registry

        class FakeUp:
            key, base = "k", "https://api.meta.ai/v1"

            def post(self, path, body, timeout=120):
                return io.BytesIO(b"{}")

        reg_path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "docs", "spec", "models.registry.json")
        with tempfile.TemporaryDirectory() as tmp:
            envp = os.path.join(tmp, "runtime.env")
            conp = os.path.join(tmp, "consent.json")
            bus = EventBus()
            gw = Gateway(Registry.load(reg_path), FakeUp(), bus,
                         sleep=lambda s: None)
            srv = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(
                    gw, bus, gw.reg,
                    env={"HUMANFLOW_ENV": envp, "SENSORS_CONSENT": conp}))
            import threading
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                page = urllib.request.urlopen(base + "/settings").read().decode()
                self.assertIn("Privacy: what may be sensed", page)
                self.assertIn("/v1/settings/key", page)

                def post(path, obj):
                    req = urllib.request.Request(
                        base + path, data=json.dumps(obj).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    return json.loads(urllib.request.urlopen(req).read())

                out = post("/v1/settings/key", {"api_key": "y" * 24})
                self.assertEqual(out["len"], 24)
                self.assertNotIn("y" * 24, json.dumps(out))
                out = post("/v1/settings/consent",
                           {"action": "grant", "sources": ["window"],
                            "ttl_s": 3600})
                self.assertTrue(out["state"]["sources"]["window"])
                state = json.loads(urllib.request.urlopen(
                    base + "/v1/settings/consent").read())
                self.assertTrue(state["sources"]["window"])
            finally:
                srv.shutdown()


class KeylessStart(unittest.TestCase):
    def test_model_call_without_key_points_at_settings(self):
        import urllib.error

        from runtime.gateway import Gateway, Upstream

        reg_path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "docs", "spec", "models.registry.json")
        from runtime.bus import EventBus
        from runtime.registry import Registry
        gw = Gateway(Registry.load(reg_path),
                     Upstream("https://api.meta.ai/v1", "", {"api.meta.ai"}),
                     EventBus(), sleep=lambda s: None)
        with self.assertRaises(Exception) as cm:
            gw.complete({"role": "voice.core",
                         "messages": [{"role": "user", "content": "hi"}]})
        self.assertIn("/settings", str(cm.exception))
        self.assertEqual(getattr(cm.exception, "status", None), 503)

    def test_settings_key_post_enables_model_without_restart(self):
        import io
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from runtime.bus import EventBus
        from runtime.gateway import Gateway, Upstream, make_handler
        from runtime.registry import Registry

        reg_path = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "docs", "spec", "models.registry.json")
        with tempfile.TemporaryDirectory() as tmp:
            envp = os.path.join(tmp, "runtime.env")
            bus = EventBus()
            up = Upstream("https://api.meta.ai/v1", "", {"api.meta.ai"})
            gw = Gateway(Registry.load(reg_path), up, bus,
                         sleep=lambda s: None)
            srv = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(
                    gw, bus, gw.reg, env={"HUMANFLOW_ENV": envp,
                                          "SENSORS_CONSENT": os.path.join(tmp, "c.json")}))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                req = urllib.request.Request(
                    base + "/v1/settings/key",
                    data=json.dumps({"api_key": "z" * 24}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                json.loads(urllib.request.urlopen(req).read())
                self.assertEqual(up.key, "z" * 24)  # live, no restart
            finally:
                srv.shutdown()


if __name__ == "__main__":
    unittest.main()
