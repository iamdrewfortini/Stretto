# SPDX-License-Identifier: Apache-2.0
"""MODEL-REGISTRY-01 loader. The registry JSON is the single source of truth for model ids, roles, fallbacks and prices."""
import json
from pathlib import Path


class Registry:
    def __init__(self, data):
        self.data = data
        self.models = data["models"]
        self.bindings = data["role_bindings"]

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def chain(self, role=None, model=None):
        """Models to try, in order. A raw model must be in the registry; a role resolves to primary + fallbacks."""
        if model:
            if model not in self.models or self.models[model].get("provider", "meta-api") != "meta-api":
                raise LookupError(f"model not served by the Meta Model API registry: {model}")
            return [model]
        b = self.bindings.get(role or "")
        if not b or not b.get("primary"):
            raise LookupError(f"no Meta model bound to role {role!r}" + (f" ({b['status']})" if b and b.get("status") else ""))
        return [b["primary"], *b.get("fallback", [])]

    def effort(self, role, model, asked=None):
        """Clamp the requested (or role default) effort to what the model accepts; None if the model takes none."""
        allowed = self.models.get(model, {}).get("reasoning_effort")
        want = asked or self.bindings.get(role or "", {}).get("effort")
        if not want or not allowed:
            return None
        if want in allowed:
            return want
        order = ["minimal", "low", "medium", "high", "xhigh", "max"]
        i = order.index(want) if want in order else 1
        return max((e for e in allowed if e in order and order.index(e) <= i), key=order.index, default=allowed[0])

    def cost(self, model, usage):
        p = self.models.get(model, {}).get("price_per_mtok")
        if not p or not usage:
            return None
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        fresh = max(usage.get("prompt_tokens", 0) - cached, 0)
        return round((fresh * p["in"] + cached * p["cached"] + usage.get("completion_tokens", 0) * p["out"]) / 1e6, 6)
