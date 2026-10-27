# SPDX-License-Identifier: Apache-2.0
"""Meta-only policy. Every learned model or agent in the runtime must be a Meta API model or a Meta open-weight model served on the cluster.
Deterministic code (statistics, solvers) is not a model and is outside this rule. Status strings are evidence labels, not marketing."""
import json, os, re

# provider: meta-api (Meta Model API or the Muse subscription lane) | meta-local (open weights served on the cluster)
CATALOG = {
 "muse-wonder-1.0":   dict(provider="meta-api", roles={"planner", "coder", "general"}, evidence="in `muse` model catalog on dev VM 2026-10-26 (verified)"),
 "muse-spark-1.2":    dict(provider="meta-api", roles={"planner", "coder", "general", "vision"}, evidence="in `muse` catalog on dev VM (verified); on Meta models page"),
 "muse-spark-1.3":    dict(provider="meta-api", roles={"planner", "coder", "general", "vision"}, evidence="in `muse` catalog on dev VM (verified)"),
 "muse-image-1.0":    dict(provider="meta-api", roles={"image"}, evidence="third-party listing; unverified on this account"),
 "muse-voice-transcribe-1.0": dict(provider="meta-api", roles={"voice"}, evidence="hackathon guide + third-party listing; unverified on this account"),
 "sam-3.1":           dict(provider="meta-api", roles={"vision"}, evidence="hackathon guide; unverified on this account"),
 "muse-glimmer-30b":  dict(provider="meta-local", roles={"planner", "coder", "general"}, params=30e9, min_ram_gib=24, license="Apache-2.0",
                           evidence="Meta open weights, 30B dense, ~<20 GB quantized / ~24 GB envelope (press reports; confirm on the model card)"),
}
# Embedding: the Meta Model API lists no embeddings route (searched 2026-10-27). Candidates below are NOT evaluated; the router refuses to route 'embed' until one is deployed AND evaluated.
EMBED_CANDIDATES = {"muse-glimmer-pooled": "hidden-state pooling of the local Glimmer weights (quality unproven)", "fair-sentence-encoder": "a FAIR sentence encoder (e.g. SONAR family) served locally (not evaluated)"}

NON_META = re.compile(r"\b(grok|xai|anthropic|claude|openai|gpt-?\d|chatgpt|gemini|mistral|deepseek|qwen|cohere|perplexity|llama-?cpp)\b", re.I)
RUNTIME = re.compile(r"\b(ollama|vllm|sglang|tgi|triton)\b", re.I)      # runtimes are fine only if they serve a Meta model: flagged as 'verify'

# What the cluster gateway (Bifrost + inference-gw, read 2026-10-27) actually exposes. A name in this table is NOT proof of provenance.
GATEWAY = dict(front="https://gateway.example.internal:8443", providers={
    "meta": dict(upstream="https://api.meta.ai", auth="META_API_KEY (pay-as-you-go credits)", models=["muse-spark-1.3-contributor", "muse-spark-1.3", "muse-wonder-1.0", "muse-image-1.0", "sam-3.1", "muse-voice-transcribe-1.0"]),
    "vllm": dict(upstream="http://vllm-chat.inference.svc.cluster.local:8000", auth="VLLM_API_KEY", models=["chat-12g"], serving_now=False)})
PROVENANCE_UNPROVEN = {"chat-12g": "gateway vllm model: no pod is serving it and its weights' origin is not recorded; allowed only after a model manifest proves Meta weights"}

def check_agent(agent):
    """agent: dict(id, model, tools). Returns list of violations."""
    if agent.get("model") in PROVENANCE_UNPROVEN: return [f"agent {agent.get('id')}: {PROVENANCE_UNPROVEN[agent['model']]}"]
    m = CATALOG.get(agent.get("model"))
    if m is None: return [f"agent {agent.get('id')}: model '{agent.get('model')}' is not a catalogued Meta model"]
    if m["provider"] not in ("meta-api", "meta-local"): return [f"agent {agent.get('id')}: provider {m['provider']} is not Meta"]
    return []

def scan_text(text, path="<text>"):
    """Non-Meta model/vendor identifiers. Returns (violations, verify) lists of (path, line, match)."""
    v, w = [], []
    for i, line in enumerate(text.splitlines(), 1):
        for m in NON_META.finditer(line): v.append((path, i, m.group(0)))
        for m in RUNTIME.finditer(line): w.append((path, i, m.group(0)))
    return v, w
def scan_dir(root, exts=(".py", ".json", ".yaml", ".yml", ".md", ".sh", ".toml", ".txt"), skip=("metapolicy.py",), skip_tests=True):
    """Test files are skipped by default because they hold non-Meta names on purpose, as refusal fixtures."""
    V, W = [], []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(exts) and f not in skip and not (skip_tests and f.startswith("test_")):
                p = os.path.join(dp, f)
                try: v, w = scan_text(open(p, encoding="utf-8", errors="ignore").read(), p)
                except OSError: continue
                V += v; W += w
    return V, W

def egress_policy(agent_ns="agents", gateway_ip="192.0.2.11", gateway_port=8443, gateway_ns="inference", datastore="192.0.2.60"):
    """Two NetworkPolicies (TEXT ONLY, not applied; the cluster has none today): agents may talk to DNS and the inference gateway and nothing else;
    only the gateway namespace may reach the internet (the Meta API host, enforced by a firewall alias because NetworkPolicy cannot match hostnames) and its datastore."""
    return (
     f"apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata: {{name: agents-gateway-only, namespace: {agent_ns}}}\nspec:\n  podSelector: {{}}\n  policyTypes: [Egress]\n  egress:\n"
     f"    - to: [{{namespaceSelector: {{matchLabels: {{kubernetes.io/metadata.name: kube-system}}}}}}]\n      ports: [{{port: 53, protocol: UDP}}, {{port: 53, protocol: TCP}}]\n"
     f"    - to: [{{ipBlock: {{cidr: {gateway_ip}/32}}}}]\n      ports: [{{port: {gateway_port}, protocol: TCP}}]\n---\n"
     f"apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata: {{name: gateway-egress, namespace: {gateway_ns}}}\nspec:\n  podSelector: {{}}\n  policyTypes: [Egress]\n  egress:\n"
     f"    - to: [{{ipBlock: {{cidr: {datastore}/32}}}}]\n      ports: [{{port: 5432, protocol: TCP}}]\n"
     f"    - to: [{{namespaceSelector: {{matchLabels: {{kubernetes.io/metadata.name: kube-system}}}}}}]\n      ports: [{{port: 53, protocol: UDP}}]\n"
     f"    - to: [{{podSelector: {{}}}}]\n"
     f"    - to: [{{ipBlock: {{cidr: 0.0.0.0/0, except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16]}}}}]\n      ports: [{{port: 443, protocol: TCP}}]\n"
     f"# UNTESTED. Pin the last rule to api.meta.ai with a firewall alias (OPNsense) before relying on it.\n")

def gateway_request(model, messages, virtual_key, provider="meta"):
    """Builds (does not send) a chat-completions request for the gateway. Header and model-name conventions are UNVERIFIED: confirm with GET /v1/models first."""
    if model in PROVENANCE_UNPROVEN or model not in CATALOG: raise ValueError(f"model '{model}' is not an allowed Meta model")
    return dict(url=GATEWAY["front"] + "/v1/chat/completions", headers={"Authorization": f"Bearer {virtual_key}", "Content-Type": "application/json"}, body=dict(model=f"{provider}/{model}", messages=messages))

def local_fit(model, free_ram_gib_by_node, headroom_gib=2.0):
    """Can the local model fit in free RAM on some node? Uses the model's stated envelope plus headroom."""
    need = CATALOG[model]["min_ram_gib"] + headroom_gib
    return {n: dict(free=f, needed=need, fits=f >= need, short_by=round(max(0.0, need - f), 2)) for n, f in free_ram_gib_by_node.items()}
