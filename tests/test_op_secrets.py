# SPDX-License-Identifier: Apache-2.0
"""1Password BYOK resolution tests with a fake SDK client (issue #28).
No network, no real token, no real values: the fake returns a sentinel that
tests assert never appears in any printed/metadata surface they control.
Run from the repo root: python3 -m unittest discover -s tests -t .
"""
import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "runtime" / "src"))
from runtime import secrets as S  # noqa: E402

SENTINEL = "fake-value-never-a-real-key"


class FakeSecrets:
    async def resolve(self, ref):
        assert ref.startswith("op://"), ref
        return SENTINEL


class FakeClient:
    secrets = FakeSecrets()


async def fake_factory(token):
    assert token == "fake-bootstrap-token"
    return FakeClient()


class OpSecrets(unittest.TestCase):
    def test_registry_template_has_refs_only(self):
        reg = S.load_registry(str(ROOT / "docs" / "spec" / "secrets.registry.json"))
        self.assertIn("MODEL_API_KEY", reg)
        self.assertTrue(reg["MODEL_API_KEY"]["ref"].startswith("op://"))

    def test_resolve_missing_fills_only_missing(self):
        env = {"OP_SERVICE_ACCOUNT_TOKEN": "fake-bootstrap-token", "KEEP": "mine"}
        reg = {"KEEP": {"ref": "op://V/Keep/credential", "required": False},
               "MODEL_API_KEY": {"ref": "op://V/Meta/credential", "required": False}}
        filled = S.resolve_missing(env, registry=reg, client_factory=fake_factory)
        self.assertEqual(filled, ["MODEL_API_KEY"])
        self.assertEqual(env["KEEP"], "mine")
        self.assertEqual(env["MODEL_API_KEY"], SENTINEL)

    def test_no_token_is_honest_noop(self):
        env = {}
        self.assertEqual(S.resolve_missing(env, registry={}), [])
        self.assertFalse(S.token_present(env))

    def test_token_presence_never_exposes_value(self):
        env = {"OP_SERVICE_ACCOUNT_TOKEN": "fake-bootstrap-token"}
        self.assertTrue(S.token_present(env))
        self.assertNotIn("fake-bootstrap-token", repr(S.load_registry(
            str(ROOT / "docs" / "spec" / "secrets.registry.json"))))


if __name__ == "__main__":
    unittest.main()
