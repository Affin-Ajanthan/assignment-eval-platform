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
# timeout: SQLite allows one writer at a time; concurrent batch auto-evaluation
# workers wait up to 30 s for their turn instead of failing with "database is locked".
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
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


def make_index_non_unique(table: str, column: str) -> None:
    """Forward-only migration for a column that used to be unique: `create_all` never alters an existing table, so an
    old portal.db keeps its UNIQUE index (ix_<table>_<column>) after the model drops unique=True. Recreate it plain."""
    index = f"ix_{table}_{column}"
    with engine.begin() as conn:
        # fetchall(): the PRAGMA's cursor must be finished before the schema changes, or SQLite says "table is locked".
        indexes = conn.exec_driver_sql(f"PRAGMA index_list({table})").fetchall()
        if any(row[1] == index and row[2] for row in indexes):
            conn.exec_driver_sql(f"DROP INDEX {index}")
            conn.exec_driver_sql(f"CREATE INDEX {index} ON {table} ({column})")


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
