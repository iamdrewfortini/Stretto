# SPDX-License-Identifier: Apache-2.0
"""Bounded Bifrost chat transport. Generated content is an unverified proposal.

No request is sent without both circuit-proof and owner-authorization evidence.
The HTTP contract is tested on loopback; that does not prove upstream availability.
"""
from dataclasses import dataclass
import ipaddress
import http.client
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .policy import CATALOG, GATEWAY

REQUEST_BYTE_LIMIT = 1048576
MESSAGE_COUNT_LIMIT = 128


class GatewayError(RuntimeError):
    """Safe failure metadata, excluding keys, prompts and remote response bodies."""

    def __init__(self, message, status="FAILED"):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class LiveGate:
    """Trusted-caller attestation, not independent verification of referenced evidence."""

    dry_run_proven: bool = False
    owner_authorized: bool = False
    dry_run_evidence: str = ""
    owner_evidence: str = ""

    def require(self):
        if (self.dry_run_proven is not True or self.owner_authorized is not True
                or not isinstance(self.dry_run_evidence, str) or not self.dry_run_evidence.strip()
                or not isinstance(self.owner_evidence, str) or not self.owner_evidence.strip()):
            raise GatewayError("live call held: circuit proof and owner authorization evidence required", "BLOCKED")


@dataclass(frozen=True)
class GatewayConfig:
    """Owner-reviewed connection settings; never accept model-generated configuration.

    timeout_s is a socket inactivity timeout, not a total wall-clock deadline.
    Slow trickle responses and DNS resolution can exceed that elapsed duration.
    """

    base_url: str
    token_env: str = "META_GATEWAY_VIRTUAL_KEY"
    timeout_s: float = 30.0
    max_response_bytes: int = 1048576
    allow_loopback_http: bool = False

    def __post_init__(self):
        if not isinstance(self.base_url, str):
            raise ValueError("gateway URL must be a string")
        try:
            u = urllib.parse.urlsplit(self.base_url)
            u.port  # Validate malformed or out-of-range ports before constructing a request.
        except ValueError:
            raise ValueError("invalid gateway URL") from None
        if not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("gateway URL must have a host and no credentials, query or fragment")
        if u.scheme != "https":
            try:
                loopback = ipaddress.ip_address(u.hostname).is_loopback
            except ValueError:
                loopback = False
            if not (u.scheme == "http" and self.allow_loopback_http is True and loopback):
                raise ValueError("gateway requires HTTPS; HTTP is permitted only for explicit loopback tests")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.token_env):
            raise ValueError("token_env must name an environment variable")
        if (isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float))
                or not math.isfinite(self.timeout_s) or not 0 < self.timeout_s <= 300):
            raise ValueError("timeout_s must be finite and within (0, 300]")
        if (isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int)
                or not 1 <= self.max_response_bytes <= 16777216):
            raise ValueError("max_response_bytes must be within [1, 16777216]")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


class GatewayClient:
    """Meta-only, single-origin transport. Token values never enter configuration."""

    def __init__(self, config, gate=None):
        if not isinstance(config, GatewayConfig):
            raise TypeError("GatewayConfig required")
        self.config = config
        self.gate = gate if gate is not None else LiveGate()
        if not isinstance(self.gate, LiveGate):
            raise TypeError("LiveGate required")
        # Do not inherit proxy environment variables or follow redirects with credentials.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _body(self, model, messages, role, max_tokens, provider):
        info = CATALOG.get(model)
        if (provider != "meta" or info is None or info["provider"] != "meta-api"
                or model not in GATEWAY["providers"]["meta"]["models"]
                or not ({"planner", "coder", "general"} & info["roles"])):
            raise GatewayError("model/provider has no allowed Meta gateway route", "NO_SIGNAL")
        if role not in info["roles"]:
            raise GatewayError("model does not support the requested role", "NO_SIGNAL")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1048576:
            raise ValueError("max_tokens must be a positive bounded integer")
        if (not isinstance(messages, (list, tuple)) or not messages
                or len(messages) > MESSAGE_COUNT_LIMIT):
            raise ValueError("messages must be a nonempty bounded sequence")
        safe = []
        text_chars = 0
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message["role"] not in {"system", "user", "assistant"}
                    or not isinstance(message["content"], str)
                    or len(message["content"]) > REQUEST_BYTE_LIMIT
                    or not message["content"].strip()):
                raise ValueError("messages require supported role and nonempty text content only")
            text_chars += len(message["content"])
            if text_chars > REQUEST_BYTE_LIMIT:
                raise ValueError("request text exceeds the size limit")
            safe.append(dict(message))
        body = {"model": f"meta/{model}", "messages": safe, "max_tokens": max_tokens}
        if len(self._serialize(body)) > REQUEST_BYTE_LIMIT:
            raise ValueError("serialized request exceeds the byte limit")
        return body

    @staticmethod
    def _serialize(body):
        return json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")

    def request_preview(self, model, messages, role="coder", max_tokens=1024, provider="meta"):
        """Construct a request without reading credentials or touching the network."""
        body = self._body(model, messages, role, max_tokens, provider)
        return {"status": "UNTESTED", "url": self._url(), "body": body,
                "header_names": ["Content-Type", "x-bf-vk", "x-bf-disable-content-logging"]}

    def _url(self):
        base = self.config.base_url.rstrip("/")
        return base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")

    def complete(self, model, messages, role="coder", max_tokens=1024, provider="meta"):
        self.gate.require()
        body = self._body(model, messages, role, max_tokens, provider)
        token = os.environ.get(self.config.token_env)
        if not token:
            raise GatewayError("gateway credential environment variable is unset", "BLOCKED")
        if any(ord(character) < 32 or ord(character) == 127 for character in token):
            raise GatewayError("gateway credential has invalid characters", "BLOCKED")
        payload = self._serialize(body)
        request = urllib.request.Request(self._url(), data=payload, method="POST", headers={
            "Content-Type": "application/json", "x-bf-vk": token,
            "x-bf-disable-content-logging": "true"})
        try:
            with self._opener.open(request, timeout=self.config.timeout_s) as response:
                if response.status != 200:
                    raise GatewayError("gateway returned an unexpected HTTP status")
                if response.headers.get_content_type() != "application/json":
                    raise GatewayError("gateway response is not JSON")
                raw = response.read(self.config.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise GatewayError(f"gateway HTTP request rejected ({code})") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError):
            raise GatewayError("gateway transport failed or timed out") from None
        if len(raw) > self.config.max_response_bytes:
            raise GatewayError("gateway response exceeds the byte limit")
        if token.encode("utf-8") in raw:
            raise GatewayError("gateway response contains credential material")
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
            return self._parse(data, model)
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
            raise GatewayError("gateway response does not match the chat contract") from None

    @staticmethod
    def _parse(data, model):
        if not isinstance(data, dict) or data.get("error") is not None:
            raise ValueError("invalid response")
        if data.get("model") not in {model, f"meta/{model}"}:
            raise ValueError("response model mismatch")
        choices = data["choices"]
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("missing choices")
        choice = choices[0]
        message = choice["message"]
        if (not isinstance(message, dict) or message.get("role") != "assistant"
                or not isinstance(message.get("content"), str) or not message["content"].strip()
                or message.get("tool_calls") or message.get("function_call")):
            raise ValueError("unsupported assistant response")
        if choice.get("finish_reason") not in {"stop", "length", "content_filter"}:
            raise ValueError("invalid finish reason")
        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            raise ValueError("invalid usage")
        clean_usage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if key in usage:
                value = usage[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("invalid token accounting")
                clean_usage[key] = value
        if all(key in clean_usage for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
            if clean_usage["prompt_tokens"] + clean_usage["completion_tokens"] != clean_usage["total_tokens"]:
                raise ValueError("inconsistent token accounting")
        return {"status": "UNVERIFIED", "content": message["content"], "model": model,
                "usage": clean_usage, "finish_reason": choice["finish_reason"],
                "evidence_scope": "generated_proposal"}
