# SPDX-License-Identifier: Apache-2.0
"""Filesystem acceptance checks for pinned context; no models or code execution."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from cells.context import load_source_context, MAX_FILES, MAX_TOTAL_BYTES


class SourceContext(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def source(self, name="src/example.py", data=b"print('source only')\n"):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def test_reads_real_utf8_files_and_pins_raw_bytes(self):
        entry = self.source(data="# café\r\nvalue = 1\r\n".encode())
        result = load_source_context(self.root, [entry])
        self.assertEqual(result["files"], [{**entry, "content": "# café\r\nvalue = 1\r\n"}])
        canonical = json.dumps(result["files"], sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode()
        self.assertEqual(result["sha256"], hashlib.sha256(canonical).hexdigest())

    def test_manifest_hash_ignores_input_order_but_tracks_content(self):
        a, b = self.source("a.py", b"a=1\n"), self.source("b.py", b"b=1\n")
        original = load_source_context(self.root, [b, a])
        self.assertEqual(original, load_source_context(self.root, [a, b]))
        changed = self.source("a.py", b"a=2\n")
        self.assertNotEqual(original["sha256"], load_source_context(self.root, [changed, b])["sha256"])

    def test_changed_source_and_corrupt_hash_fail_closed(self):
        entry = self.source()
        (self.root / entry["path"]).write_text("changed")
        with self.assertRaises(ValueError):
            load_source_context(self.root, [entry])
        with self.assertRaises(ValueError):
            load_source_context(self.root, [{**entry, "sha256": "0" * 64}])

    def test_traversal_absolute_controls_and_non_normalized_paths_refused(self):
        entry = self.source()
        for name in ["../outside.py", "/etc/passwd", "src/../example.py", "src//example.py",
                     "./src/example.py", "src/./example.py", "src/example.py/", "src\\example.py",
                     "src/example\n.py", "src/\x00.py", ""]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_source_context(self.root, [{**entry, "path": name}])

    def test_file_and_parent_symlinks_refused_including_external_targets(self):
        entry = self.source()
        with tempfile.TemporaryDirectory() as outside:
            outside_path = Path(outside)
            (outside_path / "x.py").write_text("outside")
            (self.root / "file.py").symlink_to(self.root / entry["path"])
            (self.root / "linked").symlink_to(outside_path, target_is_directory=True)
            (self.root / "inside").symlink_to(self.root / "src", target_is_directory=True)
            for name in ["file.py", "linked/x.py", "inside/example.py"]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    load_source_context(self.root, [{**entry, "path": name}])

    def test_root_must_be_canonical_absolute_real_directory(self):
        entry = self.source()
        (self.root / "alias").symlink_to(self.root / "src", target_is_directory=True)
        roots = [Path("relative"), self.root / "missing", self.root / "src" / "..",
                 self.root / "alias", self.root / entry["path"]]
        for root in roots:
            with self.subTest(root=root), self.assertRaises(ValueError):
                load_source_context(root, [entry])
        with tempfile.TemporaryDirectory() as parent:
            alias = Path(parent) / "alias"
            alias.symlink_to(self.root, target_is_directory=True)
            with self.assertRaises(ValueError):
                load_source_context(alias / "src", [{**entry, "path": "example.py"}])

    def test_missing_directory_empty_non_utf8_and_fifo_rejected(self):
        entry = self.source()
        for name, data in [("empty.py", b""), ("binary.py", b"\xff\xfe")]:
            invalid = self.source(name, data)
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_source_context(self.root, [invalid])
        for name in ["missing.py", "src"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_source_context(self.root, [{**entry, "path": name}])
        fifo = self.root / "pipe.py"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            load_source_context(self.root, [{**entry, "path": "pipe.py"}])

    def test_size_bounds_per_file_and_aggregate(self):
        a, b = self.source("a.py", b"1234"), self.source("b.py", b"5678")
        self.assertEqual(len(load_source_context(self.root, [a], max_total_bytes=4)["files"]), 1)
        with self.assertRaises(ValueError):
            load_source_context(self.root, [a], max_total_bytes=3)
        with self.assertRaises(ValueError):
            load_source_context(self.root, [a, b], max_total_bytes=7)
        huge = self.root / "huge.py"
        with huge.open("wb") as stream:
            stream.seek(MAX_TOTAL_BYTES)
            stream.write(b"x")
        with self.assertRaises(ValueError):
            load_source_context(self.root, [{"path": "huge.py", "sha256": "0" * 64}])

    def test_hard_caps_cannot_be_raised_or_disabled(self):
        entry = self.source()
        for option, values in [("max_files", [0, -1, True, 1.5, MAX_FILES + 1]),
                               ("max_total_bytes", [0, -1, True, 1.5, MAX_TOTAL_BYTES + 1])]:
            for value in values:
                with self.subTest(option=option, value=value), self.assertRaises(ValueError):
                    load_source_context(self.root, [entry], **{option: value})
        with self.assertRaises(ValueError):
            load_source_context(self.root, [entry], max_files=0)
        other = self.source("other.py")
        with self.assertRaises(ValueError):
            load_source_context(self.root, [entry, other], max_files=1)

    def test_invalid_entries_duplicates_and_hash_shapes_refused(self):
        entry = self.source()
        invalid = [[], None, (entry,), [entry, entry], [{}], [{**entry, "extra": 1}],
                   [{"path": entry["path"], "sha256": "A" * 64}],
                   [{"path": entry["path"], "sha256": "x"}],
                   [{"path": 123, "sha256": "0" * 64}], [None], ["path"]]
        for entries in invalid:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                load_source_context(self.root, entries)


if __name__ == "__main__":
    unittest.main()
