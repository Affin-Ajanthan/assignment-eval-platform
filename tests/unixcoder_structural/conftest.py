"""
Fixtures for the UniXcoder formatting/comment invariance suite.

The production encoder is loaded once per pytest run and cached on the pytest
config, so this suite and tests/unixcoder_basic share a single model load.
If it can't be loaded, the tests error with the load failure (no skips).
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture(scope="session")
def encoder(request):
    cached = getattr(request.config, "_unixcoder_encoder", None)
    if cached is not None:
        return cached
    from app.similarity.semantic import UniXcoderEncoder

    started = time.perf_counter()
    try:
        enc = UniXcoderEncoder(device="cpu")
    except Exception as exc:  # fail loudly: never a silent skip
        pytest.fail(f"UniXcoder could not be loaded: {type(exc).__name__}: {exc}", pytrace=False)
    enc.load_seconds = time.perf_counter() - started
    request.config._unixcoder_encoder = enc
    return enc
