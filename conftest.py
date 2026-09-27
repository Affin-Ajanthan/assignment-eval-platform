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
_portal_db = ROOT / "portal.db"
if _portal_db.exists():
    _portal_db.unlink()

# Bootstrap the default admin account directly, rather than relying on
# app.main's `@app.on_event("startup")` handler -- a bare
# `TestClient(app)` (the pattern every test module uses) does not run
# FastAPI's startup lifecycle unless used as a context manager, so the
# tests bootstrap explicitly here instead of depending on that.
import app.main  # noqa: E402  (import after sys.path setup above; also creates the tables)
from app.auth import bootstrap_admin  # noqa: E402
from app.db import SessionLocal  # noqa: E402

_db = SessionLocal()
try:
    bootstrap_admin(_db)
finally:
    _db.close()
