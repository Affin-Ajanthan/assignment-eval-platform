"""
Database wiring shared by app.models, app.auth and app.main: the
SQLAlchemy engine/session factory and the declarative Base every model
inherits from, plus the runtime data directories (uploads/, portal.db)
that live alongside the source rather than inside the Python package.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PROJECT_DIR = Path(__file__).resolve().parent.parent
# Where portal.db and uploads/ live; stored submission paths are relative to
# it. The project folder unless PORTAL_DATA_DIR says otherwise -- the test
# suite (conftest.py) points it at a temporary folder so a test run can never
# touch the real database or uploaded files.
BASE_DIR = Path(os.environ.get("PORTAL_DATA_DIR") or PROJECT_DIR).resolve()
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# PORTAL_DB_PATH lets the tests use a throwaway database; normally it is unset.
DB_FILE = Path(os.environ.get("PORTAL_DB_PATH") or BASE_DIR / "portal.db")
DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def add_missing_columns(table: str, columns: dict[str, str]) -> None:
    """Minimal forward-only migration: `create_all` creates new tables
    but never alters existing ones, so columns added to a model later
    are added here (as nullable) on an existing portal.db."""
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if not existing:
            return
        for name, sql_type in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
