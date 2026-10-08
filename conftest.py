import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Start every test session from a clean database. User emails and
# subject codes are unique-constrained, so leftover data from a
# previous run (or from manually poking at the API, e.g. during a
# live UI walkthrough) would otherwise make account-creation tests
# fail with "already exists" errors that have nothing to do with the
# code under test.
# Keep the default UniXcoder service off for the test session so the
# ordinary API tests never download or load a ~500 MB model. Tests that
# exercise semantic similarity inject their own service (a fake encoder,
# or the real model in tests marked `slow`).
os.environ["SEMANTIC_SIMILARITY"] = "0"
# Same for the sentence-embedding model behind cross-modal consistency.
os.environ["CROSS_MODAL_SEMANTIC"] = "0"
# Keep grading deterministic and offline: never call a local Ollama model
# or the Claude API from the ordinary tests.
os.environ["GRADER_BACKEND"] = "heuristic"
# And the Fast-DetectGPT scoring model (reports fall back to the style heuristic).
os.environ["AI_TEXT_DETECTION"] = "0"

_portal_db = ROOT / "portal.db"
if _portal_db.exists():
    _portal_db.unlink()

# Bootstrap the default admin account directly, rather than relying on
# app.main's `@app.on_event("startup")` handler -- a bare
# `TestClient(app)` (the pattern every test module uses) does not run
# FastAPI's startup lifecycle unless used as a context manager, so the
# tests bootstrap explicitly here instead of depending on that.
import app.auth  # noqa: E402

# Password hashing is deliberately slow (260k PBKDF2 rounds); tests create
# hundreds of throwaway accounts, so use a cheap setting for this session only.
app.auth.PBKDF2_ITERATIONS = 1_000

import app.main  # noqa: E402  (import after sys.path setup above; also creates the tables)
from app.auth import bootstrap_admin  # noqa: E402
from app.db import SessionLocal  # noqa: E402

_db = SessionLocal()
try:
    bootstrap_admin(_db)
finally:
    _db.close()
