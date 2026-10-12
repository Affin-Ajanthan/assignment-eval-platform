"""Winnowing fingerprints must not depend on Python's per-process hash seed."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (
    "from app.similarity.core import fingerprint_source\n"
    "src = 'def f(xs):\\n    total = 0\\n    for x in xs:\\n        total += x * 2\\n    return total\\n'\n"
    "print(sorted(fingerprint_source('a', 'a.py', src).hashes))\n"
)


def _hashes(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout


def test_fingerprints_identical_across_hash_seeds():
    first = _hashes("0")
    assert first.strip() not in ("", "[]")
    for seed in ("1", "12345", "random"):
        assert _hashes(seed) == first
