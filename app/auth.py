"""
Authentication and authorization.

Every account -- admin, instructor, student -- is created by an admin
(see the /admin/* endpoints in app/main.py); there is no self-signup.
A default admin account is bootstrapped on first run (see
`bootstrap_admin`) so there's always a way to log in on a fresh
database.

Sessions are opaque bearer tokens stored in the `auth_sessions` table.
The frontend stores the token (in localStorage) after login and sends
it back as `Authorization: Bearer <token>` on every request.

Password hashing uses PBKDF2-HMAC-SHA256 from the standard library --
deliberately no extra dependency (bcrypt/passlib) for a project this
size; the iteration count is high enough to be a reasonable default
in 2026.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, Enrollment, InstructorAssignment, User

PBKDF2_ITERATIONS = 260_000
SESSION_LIFETIME = timedelta(days=7)

DEFAULT_ADMIN_EMAIL = "admin@school.local"
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "admin123")


def _naive_utcnow() -> datetime:
    # Session expiry is compared against values SQLite hands back as
    # naive datetimes, so this stays naive-UTC throughout rather than
    # mixing in timezone-aware values (unlike the tz-aware `created_at`
    # timestamps elsewhere, which are only ever displayed, not compared).
    return datetime.utcnow()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex)."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, user_id=user.id, expires_at=_naive_utcnow() + SESSION_LIFETIME))
    db.commit()
    return token


def invalidate_session(db: Session, token: str) -> None:
    session = db.get(AuthSession, token)
    if session:
        db.delete(session)
        db.commit()


def bootstrap_admin(db: Session) -> None:
    """Create a default admin account if no admin exists yet, so
    there's always a way to log in on a fresh database."""
    existing = db.query(User).filter(User.role == "admin").first()
    if existing:
        return
    password_hash, salt = hash_password(DEFAULT_ADMIN_PASSWORD)
    admin = User(
        email=DEFAULT_ADMIN_EMAIL,
        full_name="Administrator",
        role="admin",
        password_hash=password_hash,
        password_salt=salt,
    )
    db.add(admin)
    db.commit()
    print(
        f"[bootstrap] Created default admin account -- email: {DEFAULT_ADMIN_EMAIL}  "
        f"password: {DEFAULT_ADMIN_PASSWORD}\n"
        f"[bootstrap] Log in and create real accounts; change this password if you keep it."
    )


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    session = db.get(AuthSession, token)
    if not session or session.expires_at < _naive_utcnow():
        raise HTTPException(401, "Session expired or invalid -- please log in again")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "User no longer exists")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def require_instructor(user: User = Depends(get_current_user)) -> User:
    if user.role != "instructor":
        raise HTTPException(403, "Instructor access required")
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != "student":
        raise HTTPException(403, "Student access required")
    return user


def instructor_subject_ids(db: Session, instructor: User) -> set[int]:
    return {
        row.subject_id
        for row in db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == instructor.id)
    }


def student_subject_ids(db: Session, student: User) -> set[int]:
    return {
        row.subject_id
        for row in db.query(Enrollment).filter(Enrollment.student_id == student.id)
    }
