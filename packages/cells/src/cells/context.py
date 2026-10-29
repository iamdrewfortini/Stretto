# SPDX-License-Identifier: Apache-2.0
"""Read bounded, explicitly selected source files against pinned SHA256 values.

The returned context is data only. This loader does not import or execute it.
Root and every traversed directory/file are opened without following symlinks.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat


MAX_FILES = 32
MAX_TOTAL_BYTES = 262144
MAX_PATH_CHARS = 4096
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _manifest(entries, max_files):
    if not isinstance(entries, list) or not entries or len(entries) > max_files:
        raise ValueError("context requires a nonempty bounded source manifest")
    selected = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("source entries require exactly path and sha256")
        path, digest = entry["path"], entry["sha256"]
        if (not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS
                or path.startswith("/") or "\\" in path
                or any(part in ("", ".", "..") for part in path.split("/"))
                or any(ord(c) < 32 or ord(c) == 127 for c in path)):
            raise ValueError("source paths must be normalized relative POSIX paths")
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError("source hashes require lowercase SHA256")
        if path in selected:
            raise ValueError("duplicate source path")
        selected[path] = digest
    return sorted(selected.items())


def _directory(parent_fd, name):
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)


def _root_fd(root):
    try:
        root = Path(root)
        if not root.is_absolute() or root != root.resolve(strict=True):
            raise ValueError("source root must be an absolute canonical directory")
    except (OSError, TypeError, RuntimeError):
        raise ValueError("source root must be an absolute canonical directory") from None
    # Opening each root component relative to the previous descriptor also
    # rejects symlink replacement races in ancestors of the selected root.
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in root.parts[1:]:
            next_fd = _directory(fd, name)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _read(root_fd, relative, remaining):
    parent_fd = os.dup(root_fd)
    file_fd = None
    try:
        parts = relative.split("/")
        for name in parts[:-1]:
            next_fd = _directory(parent_fd, name)
            os.close(parent_fd)
            parent_fd = next_fd
        # O_NONBLOCK ensures a named pipe cannot block before fstat rejects it.
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=parent_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("source entry is not a regular file")
        if metadata.st_size > remaining:
            raise ValueError("source context exceeds byte limit")
        chunks, count = [], 0
        while True:
            chunk = os.read(file_fd, min(65536, remaining + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > remaining:
                raise ValueError("source context exceeds byte limit")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def load_source_context(root, entries, max_files=MAX_FILES, max_total_bytes=MAX_TOTAL_BYTES):
    """Return files[{path,sha256,content}] and their deterministic manifest hash.

    Root must be a canonical absolute directory. Entries select nonempty UTF-8
    regular files using exact raw-byte SHA256 pins. Optional limits can tighten,
    never raise, the fixed hard caps. The manifest digest is SHA256 of canonical
    UTF-8 JSON of the path-sorted returned files list (sorted object keys,
    separators=(',', ':'), ensure_ascii=False).
    """
    if type(max_files) is not int or not 1 <= max_files <= MAX_FILES:
        raise ValueError("context file limit exceeds hard bounds")
    if type(max_total_bytes) is not int or not 1 <= max_total_bytes <= MAX_TOTAL_BYTES:
        raise ValueError("context byte limit exceeds hard bounds")
    selected = _manifest(entries, max_files)
    files, total = [], 0
    root_descriptor = None
    try:
        root_descriptor = _root_fd(root)
        for path, wanted in selected:
            raw = _read(root_descriptor, path, max_total_bytes - total)
            if not raw:
                raise ValueError("source files must be nonempty")
            actual = hashlib.sha256(raw).hexdigest()
            if actual != wanted:
                raise ValueError("source hash does not match pinned manifest")
            try:
                content = raw.decode("utf-8", errors="strict")
            except UnicodeError:
                raise ValueError("source files require UTF-8 text") from None
            total += len(raw)
            files.append({"path": path, "sha256": actual, "content": content})
    except OSError:
        raise ValueError("source path is inaccessible or traverses a symlink") from None
    finally:
        if root_descriptor is not None:
            os.close(root_descriptor)
    serialized = json.dumps(files, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"files": files, "sha256": hashlib.sha256(serialized).hexdigest()}
