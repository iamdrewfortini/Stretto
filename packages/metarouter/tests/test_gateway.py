# SPDX-License-Identifier: Apache-2.0
"""Real loopback HTTP contract checks; no upstream model is called."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch

from metarouter.gateway import GatewayClient, GatewayConfig, GatewayError, LiveGate, REQUEST_BYTE_LIMIT


MODEL = "muse-wonder-1.0"
MESSAGES = [{"role": "user", "content": "Produce a proposed patch."}]
GATE = LiveGate(True, True, "offline-circuit-evidence", "owner-authorization-evidence")
TOKEN_ENV = "METACOH_TEST_VIRTUAL_KEY"
TOKEN = "loopback-fixture-key-never-production"


def response():
    return {"model": "meta/" + MODEL, "choices": [{"message": {
        "role": "assistant", "content": "proposed code"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}


@contextmanager
def server(payload=None, code=200, headers=None, raw=None, stall=False):
    state = {"requests": [], "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state["requests"].append({"path": self.path, "headers": self.headers,
                                      "body": json.loads(body)})
            if stall:
                state["release"].wait(2)
                return
            self.send_response(code)
            for key, value in (headers or {"Content-Type": "application/json"}).items():
                self.send_header(key, value)
            self.end_headers()
            data = raw if raw is not None else json.dumps(response() if payload is None else payload).encode()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", state
    finally:
        state["release"].set()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


class GatewayTransport(unittest.TestCase):
    def client(self, url, gate=GATE, **kw):
        return GatewayClient(GatewayConfig(url, TOKEN_ENV, allow_loopback_http=True, **kw), gate)

    def call(self, client, **kwargs):
        with patch.dict(os.environ, {TOKEN_ENV: TOKEN}):
            return client.complete(MODEL, MESSAGES, **kwargs)

    def test_post_contract_and_generated_proposal_status(self):
        with server() as (url, state):
            client = self.client(url)
            out = self.call(client)
        request = state["requests"][0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["x-bf-vk"], TOKEN)
        self.assertEqual(request["headers"]["x-bf-disable-content-logging"], "true")
        self.assertIsNone(request["headers"].get("Authorization"))
        self.assertEqual(request["body"], {"model": "meta/" + MODEL, "messages": MESSAGES, "max_tokens": 1024})
        self.assertEqual((out["status"], out["content"], out["usage"]["total_tokens"]),
                         ("UNVERIFIED", "proposed code", 6))
        self.assertEqual(out["evidence_scope"], "generated_proposal")
        self.assertNotIn(TOKEN, repr(out) + repr(client.config))

    def test_v1_base_is_not_duplicated(self):
        with server() as (url, state):
            self.call(self.client(url + "/v1/"))
        self.assertEqual(state["requests"][0]["path"], "/v1/chat/completions")

    def test_preview_never_reads_key_or_opens_network(self):
        client = GatewayClient(GatewayConfig("https://gateway.example.internal:8443"))
        with patch.dict(os.environ, {}, clear=True), patch.object(client._opener, "open", side_effect=AssertionError("network")):
            preview = client.request_preview(MODEL, MESSAGES)
        self.assertEqual(preview["status"], "UNTESTED")
        self.assertNotIn("headers", preview)

    def test_default_and_incomplete_gates_block_before_network(self):
        gates = [None, LiveGate(True, True), LiveGate(True, False, "proof", "owner"),
                 LiveGate(False, True, "proof", "owner"), LiveGate(True, True, " ", "owner")]
        with server() as (url, state):
            for gate in gates:
                with self.subTest(gate=gate), self.assertRaises(GatewayError) as error:
                    self.call(self.client(url, gate))
                self.assertEqual(error.exception.status, "BLOCKED")
        self.assertEqual(state["requests"], [])

    def test_refuses_non_meta_unknown_nonchat_provider_and_role(self):
        with server() as (url, state):
            client = self.client(url)
            for model in ["gpt-5", "chat-12g", "unknown", "muse-glimmer-30b", "sam-3.1", "muse-image-1.0"]:
                with self.subTest(model=model), self.assertRaises(GatewayError) as error:
                    client.request_preview(model, MESSAGES)
                self.assertEqual(error.exception.status, "NO_SIGNAL")
            for kw in [{"provider": "openai"}, {"role": "embed"}]:
                with self.assertRaises(GatewayError):
                    self.call(client, **kw)
        self.assertEqual(state["requests"], [])

    def test_missing_key_and_header_injection_are_safe(self):
        with server() as (url, state):
            client = self.client(url)
            for key in [None, TOKEN + "\r\nInjected: x"]:
                env = {} if key is None else {TOKEN_ENV: key}
                with patch.dict(os.environ, env, clear=True), self.assertRaises(GatewayError) as error:
                    client.complete(MODEL, MESSAGES)
                self.assertEqual(error.exception.status, "BLOCKED")
                self.assertNotIn(TOKEN, str(error.exception))
        self.assertEqual(state["requests"], [])

    def test_redirect_cannot_forward_virtual_key(self):
        with server() as (target, target_state):
            with server(code=307, headers={"Location": target + "/stolen"}) as (url, source_state):
                with self.assertRaises(GatewayError):
                    self.call(self.client(url))
        self.assertEqual(len(source_state["requests"]), 1)
        self.assertEqual(target_state["requests"], [])

    def test_remote_error_body_is_not_disclosed(self):
        with server(code=401, raw=TOKEN.encode()) as (url, state):
            with self.assertRaises(GatewayError) as error:
                self.call(self.client(url))
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertIn("401", str(error.exception))

    def test_success_response_cannot_echo_credential(self):
        payload = response()
        payload["choices"][0]["message"]["content"] = TOKEN
        with server(payload=payload) as (url, state):
            with self.assertRaises(GatewayError) as error:
                self.call(self.client(url))
        self.assertNotIn(TOKEN, str(error.exception))

    def test_transport_timeout_is_bounded_and_sanitized(self):
        with server(stall=True) as (url, state):
            with self.assertRaises(GatewayError) as error:
                self.call(self.client(url, timeout_s=0.03))
        self.assertIn("timed out", str(error.exception))
        self.assertNotIn(TOKEN, str(error.exception))

    def test_response_byte_bound(self):
        with server(raw=b"x" * 100) as (url, state):
            with self.assertRaises(GatewayError) as error:
                self.call(self.client(url, max_response_bytes=32))
        self.assertIn("byte limit", str(error.exception))

    def test_response_shape_and_accounting_fail_closed(self):
        variants = []
        for mutation in [lambda p: p.update(model="nonmeta-model"),
                         lambda p: p.update(choices=[]),
                         lambda p: p["choices"][0]["message"].update(content=None),
                         lambda p: p["choices"][0]["message"].update(tool_calls=[{}]),
                         lambda p: p["usage"].update(total_tokens=-1),
                         lambda p: p["usage"].update(total_tokens=True),
                         lambda p: p["usage"].update(total_tokens=99)]:
            item = response()
            mutation(item)
            variants.append(item)
        for item in variants:
            with self.subTest(payload=item), server(payload=item) as (url, state):
                with self.assertRaises(GatewayError):
                    self.call(self.client(url))

    def test_bad_json_duplicates_content_type_and_nonfinite_refused(self):
        cases = [(b"not-json", None), (b'{"model":"a","model":"b"}', None),
                 (b'{"value":NaN}', None), (b"{}", {"Content-Type": "text/plain"})]
        for raw, headers in cases:
            with self.subTest(raw=raw), server(raw=raw, headers=headers) as (url, state):
                with self.assertRaises(GatewayError):
                    self.call(self.client(url))

    def test_invalid_messages_and_limits_do_not_send(self):
        client = GatewayClient(GatewayConfig("https://gateway.example.internal"))
        for messages in [[], [{"role": "tool", "content": "x"}], [{"role": "user", "content": []}],
                         [{"role": "user", "content": "x", "other": TOKEN}]]:
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                client.request_preview(MODEL, messages)
        for limit in [0, -1, True, 1.5]:
            with self.assertRaises(ValueError):
                client.request_preview(MODEL, MESSAGES, max_tokens=limit)

    def test_oversize_requests_are_rejected_without_network(self):
        oversized = [
            [{"role": "user", "content": "x" * (REQUEST_BYTE_LIMIT + 1)}],
            [{"role": "user", "content": "x" * (REQUEST_BYTE_LIMIT // 2)}] * 3,
            [{"role": "user", "content": "\u20ac" * (REQUEST_BYTE_LIMIT // 2)}],
            [{"role": "user", "content": "x"}] * 129,
        ]
        with server() as (url, state):
            client = self.client(url)
            with patch.dict(os.environ, {TOKEN_ENV: TOKEN}):
                for messages in oversized:
                    with self.subTest(count=len(messages)), self.assertRaises(ValueError):
                        client.complete(MODEL, messages)
        self.assertEqual(state["requests"], [])

    def test_config_refuses_unsafe_origin_and_limits(self):
        for url in ["http://example.com", "http://localhost", "http://127.0.0.2:1?key=x", "https://u:p@example.com", "file:///tmp/a"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                GatewayConfig(url)
        for values in [{"timeout_s": 0}, {"timeout_s": float("inf")}, {"max_response_bytes": True},
                       {"max_response_bytes": 0}, {"token_env": "not an env variable"}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                GatewayConfig("https://gateway.example.internal", **values)


if __name__ == "__main__":
    unittest.main()
