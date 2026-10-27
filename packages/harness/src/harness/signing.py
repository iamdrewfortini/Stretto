# SPDX-License-Identifier: Apache-2.0
"""Key custody: Ed25519 multi-signature. The optimizer host holds ONLY public keys, so it can verify the envelope but cannot re-sign it.
Valid iff >= min_agents distinct agent keys AND >= min_humans distinct human keys signed the exact envelope bytes."""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from harness.boundary import canon

def new_key():
    k = Ed25519PrivateKey.generate(); pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw); return k, pub
def sign_with(env, priv): return priv.sign(canon(env).encode()).hex()

def make_verifier(authorized, min_agents=2, min_humans=1):
    """authorized: {key_id: (role, public_key_bytes)}; returns verify(env, sigs) -> (ok, reason)."""
    def verify(env, sigs):
        msg, agents, humans = canon(env).encode(), set(), set()
        for kid, sig in sigs.items():
            if kid not in authorized: continue
            role, pub = authorized[kid]
            try: Ed25519PublicKey.from_public_bytes(pub).verify(bytes.fromhex(sig), msg)
            except (InvalidSignature, ValueError): continue
            (agents if role == "agent" else humans).add(kid)
        if len(agents) < min_agents: return False, f"need {min_agents} agent signatures, have {len(agents)}"
        if len(humans) < min_humans: return False, f"need {min_humans} human signature, have {len(humans)}"
        return True, None
    return verify
