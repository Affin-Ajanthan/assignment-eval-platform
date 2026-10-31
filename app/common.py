"""Small helpers shared by app/main.py and the routers: UTC time handling,
assignment lookups and the code file types the checks read. Imports nothing
from app.main, so any module can use it."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import HTTPException
from pydantic import AfterValidator
from sqlalchemy.orm import Session

from .auth import instructor_subject_ids
from .models import Assignment, Subject, User
from .notebook import NOTEBOOK_SUFFIX

# Source files the similarity check and code analysis read. Includes C# and
# C/C++ headers, which unixcoder-base-nine was trained on.
CODE_EXTENSIONS = {".py", ".java", ".js", ".c", ".cpp", ".cc", ".cxx", ".hh", ".hxx", ".h", ".hpp", ".cs", ".go",
                   ".rb", ".php"}
# Files the code checks read: source files plus Jupyter notebooks, whose code
# cells are read as Python (app/notebook.py).
ANALYZED_EXTENSIONS = CODE_EXTENSIONS | {NOTEBOOK_SUFFIX}


def _assume_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# Timestamps are stored as naive UTC (SQLite drops the offset). Responses
# mark them as UTC so browsers convert them to local time instead of
# mistaking them for local time.
UTCDateTime = Annotated[datetime, AfterValidator(_assume_utc)]


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def norm_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def on_flag(flag: Optional[bool]) -> bool:
    """Self-check switches: NULL (rows made before the column existed) means on."""
    return flag is None or bool(flag)


def instructor_assignment(db: Session, instructor: User, assignment_id: int) -> Assignment:
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    return assignment


def instructor_subject(db: Session, instructor: User, subject_id: int) -> Subject:
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    return subject
