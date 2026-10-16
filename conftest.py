import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
# Test modules import their shared helpers by plain name (`from helpers
# import ...`, `from semantic_samples import ...`).
sys.path.insert(1, str(ROOT / "tests"))

# Every test session gets its own empty database and uploads folder in a
# temporary directory (removed at the end). The app reads PORTAL_DATA_DIR
# when app.db is first imported, which is below this line, so the real
# portal.db and uploads/ in the project folder are never opened, changed or
# deleted by tests. (User emails and subject codes are unique-constrained,
# which is why each session starts empty.)
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="portal-tests-")
os.environ["PORTAL_DATA_DIR"] = _TEST_DATA_DIR


def _remove_test_data_dir():
    # On Windows the SQLite file can't be deleted while a connection is open.
    if "app.db" in sys.modules:
        sys.modules["app.db"].engine.dispose()
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


atexit.register(_remove_test_data_dir)
# Keep the default UniXcoder service off for the test session so the
# ordinary API tests never download or load a ~500 MB model. Tests that
# exercise semantic similarity inject their own service (a fake encoder,
# or the real model in tests marked `slow`).
os.environ["SEMANTIC_SIMILARITY"] = "0"
# Same for the sentence-embedding model behind cross-modal consistency.
os.environ["CROSS_MODAL_SEMANTIC"] = "0"
# Keep grading deterministic and offline: never call a local Ollama model
# from the ordinary tests.
os.environ["GRADER_BACKEND"] = "heuristic"
# ...and never call the local vision model for frame descriptions.
os.environ["VIDEO_VISION"] = "off"
# And the Fast-DetectGPT scoring model (reports fall back to the style heuristic).
os.environ["AI_TEXT_DETECTION"] = "0"
# The local demo accounts are for manual use, not for the test database.
os.environ["DEMO_DATA"] = "off"

# app/db.py also reads PORTAL_DB_PATH for the database file: point it into
# this session's temporary folder too, so database and uploads stay together
# and are removed at the end. Never the real portal.db.
os.environ["PORTAL_DB_PATH"] = str(Path(_TEST_DATA_DIR) / "portal.db")

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


def pytest_unconfigure(config):
    """Remove this session's temporary database and uploads at the end."""
    _remove_test_data_dir()
