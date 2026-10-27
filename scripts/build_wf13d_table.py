# SPDX-License-Identifier: Apache-2.0
"""Builds packages/wf13d/data/wf13d.tbl (4 bytes x 2^18 addresses = 1,048,576 bytes) and its sha256. The binary is for non-Python consumers; layout is documented in wf13d/table.py."""
import hashlib, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "packages", "wf13d", "src"))
from wf13d.table import build
blob = build(); d = os.path.join(ROOT, "packages", "wf13d", "src", "wf13d", "data"); os.makedirs(d, exist_ok=True)
open(os.path.join(d, "wf13d.tbl"), "wb").write(blob); open(os.path.join(d, "wf13d.tbl.sha256"), "w").write(hashlib.sha256(blob).hexdigest() + "\n")
print(len(blob), "bytes", hashlib.sha256(blob).hexdigest())
