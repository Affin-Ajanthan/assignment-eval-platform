"""
Local demo accounts, created at backend startup when they are missing.

The accounts themselves (emails, names, password, subject) are not in this
repository. They are read from local_demo_data.json at the project root,
which is git-ignored. Copy local_demo_data.example.json to start.
If the file is missing, nothing is created.

The admin (admin@school.local) is created by app.auth.bootstrap_admin.
Set DEMO_DATA=off to skip this entirely.
DEMO_DATA_FILE can point at a different JSON file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy.orm import Session

from .auth import hash_password
from .db import BASE_DIR
from .models import Enrollment, InstructorAssignment, Subject, User

DEFAULT_FILE = BASE_DIR / "local_demo_data.json"


def demo_data_enabled() -> bool:
    return os.environ.get("DEMO_DATA", "on").strip().lower() not in {"off", "0", "false", "no"}


def demo_data_file() -> Path:
    return Path(os.environ.get("DEMO_DATA_FILE") or DEFAULT_FILE)


def _get_or_create_user(db: Session, password: str, email: str, full_name: str, role: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        password_hash, salt = hash_password(password)
        user = User(email=email, full_name=full_name, role=role,
                    password_hash=password_hash, password_salt=salt)
        db.add(user)
        db.flush()
    return user


def seed_demo_data(db: Session, path: Path | None = None) -> None:
    """Create the demo subject, instructor and students described in the JSON file
    if they are missing. Existing rows are left alone, so running it again changes nothing."""
    path = path or demo_data_file()
    if not path.is_file():
        print(f"[demo] no {path.name} found; demo accounts not created")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    password = data["password"]

    subject_data = data["subject"]
    subject = db.query(Subject).filter(Subject.code == subject_data["code"]).first()
    if subject is None:
        subject = Subject(name=subject_data["name"], code=subject_data["code"])
        db.add(subject)
        db.flush()

    instructor_data = data["instructor"]
    instructor = _get_or_create_user(db, password, instructor_data["email"], instructor_data["name"], "instructor")
    if not db.query(InstructorAssignment).filter_by(instructor_id=instructor.id, subject_id=subject.id).first():
        db.add(InstructorAssignment(instructor_id=instructor.id, subject_id=subject.id))

    for student_data in data["students"]:
        student = _get_or_create_user(db, password, student_data["email"], student_data["name"], "student")
        if not db.query(Enrollment).filter_by(student_id=student.id, subject_id=subject.id).first():
            db.add(Enrollment(student_id=student.id, subject_id=subject.id))

    db.commit()
    print(f"[demo] demo accounts ready from {path.name}: subject '{subject.name}', "
          f"instructor {instructor.email}, {len(data['students'])} students")
