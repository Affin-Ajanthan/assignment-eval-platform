"""
Regression test: UniXcoder and MiniLM are preloaded in parallel background
threads at startup. Without the shared load lock (app/model_loading.py)
the concurrent first import of ``transformers`` made the UniXcoder load
fail with "ImportError: cannot import name 'AutoModel' from 'transformers'",
and the similarity check then reported semantic analysis as unavailable
until the server restarted.

Runs in a fresh Python process because the race only exists before
``transformers`` has been imported, which this test session already did.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_SCRIPT = """
import threading
from app.similarity.semantic import SemanticSimilarityService
from app.evaluator.semantic_consistency import SentenceEmbeddingService

services = [SemanticSimilarityService(enabled=True), SentenceEmbeddingService(enabled=True)]
threads = [s.preload_in_background() for s in services]
for t in threads:
    t.join()
for s in services:
    print(f"{type(s).__name__}|{s.status}|{s.error or ''}")
"""


@pytest.mark.slow
def test_parallel_model_preloads_do_not_break_each_other():
    proc = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=600)
    rows = [line.split("|", 2) for line in proc.stdout.splitlines() if line.count("|") >= 2]
    assert len(rows) == 2, proc.stdout + proc.stderr
    for name, status, error in rows:
        assert "cannot import name" not in error, f"{name}: {error}"
        if status == "unavailable":
            pytest.skip(f"{name} model unavailable for another reason (e.g. offline): {error}")
        assert status == "ready", f"{name}: {status} {error}"
