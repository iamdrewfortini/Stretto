"""Every UI module must at least parse. Catches a broken module before the app silently stays on its loading mark."""
import glob, os, shutil, subprocess, tempfile, unittest

STATIC = os.path.join(os.path.dirname(__file__), "..", "stretto", "static")
NODE = shutil.which("node") or next((p for p in ("/usr/local/bin/node", "/opt/homebrew/bin/node") if os.path.exists(p)), None)


@unittest.skipUnless(NODE, "node not installed")
class JsSyntax(unittest.TestCase):
    def test_every_module_parses(self):
        files = glob.glob(os.path.join(STATIC, "js", "**", "*.js"), recursive=True)
        self.assertGreater(len(files), 10)
        with tempfile.TemporaryDirectory() as d:
            for i, f in enumerate(files):
                m = os.path.join(d, f"m{i}.mjs")
                shutil.copy(f, m)
                r = subprocess.run([NODE, "--check", m], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{os.path.relpath(f, STATIC)}: {r.stderr[:300]}")


if __name__ == "__main__":
    unittest.main()