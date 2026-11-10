"""Logging in and out, the signed-in user, and changing one's own password.

Moved out of app/main.py (Auth). Included in app/main.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..auth import (
    create_session,
    get_user_changing_password,
    hash_password,
    invalidate_session,
    password_matches,
    password_problems,
)
from ..db import get_db
from ..models import AuthSession, Enrollment, InstructorAssignment, User
from ..schemas import LoginIn, LoginOut, PasswordChangeIn, UserOut
from .student_runs import RunLimitError as _RunLimitError, UnlockLimiter as _UnlockLimiter


router = APIRouter()


def _user_out(user: User, db: Session) -> UserOut:
    if user.role == "instructor":
        rows = db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == user.id).all()
        subjects = [row.subject for row in rows]
    elif user.role == "student":
        rows = db.query(Enrollment).filter(Enrollment.student_id == user.id).all()
        subjects = [row.subject for row in rows]
    else:
        subjects = []
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role, subjects=subjects,
                   batch=user.batch or "", register_number=user.register_number or "",
                   must_change_password=bool(user.must_change_password))


@router.post("/auth/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    # Password guessing is limited per account, as for subject and task passwords: after a few wrong passwords
    # the account takes no more tries, not even the right one, until the oldest wrong try ages out. The key is the
    # e-mail as typed, case and spaces ignored, so an unknown address is limited the same way (and gives nothing away).
    key = payload.email.strip().lower()
    try:
        login_limiter.check(key)
    except _RunLimitError as exc:
        raise HTTPException(exc.status, exc.detail)
    user = db.query(User).filter(User.email == payload.email).first()
    # password_matches hashes even when there is no such user, so a wrong password takes as long for an unknown
    # e-mail as for a real one: the response time doesn't reveal which e-mails have accounts.
    if not password_matches(user, payload.password):
        login_limiter.miss(key)
        raise HTTPException(401, "Incorrect email or password")
    login_limiter.clear(key)
    token = create_session(db, user)
    return LoginOut(token=token, user=_user_out(user, db))


@router.post("/auth/logout")
def logout(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    if authorization and authorization.lower().startswith("bearer "):
        invalidate_session(db, authorization.split(" ", 1)[1].strip())
    return {"status": "ok"}


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_user_changing_password), db: Session = Depends(get_db)):
    return _user_out(user, db)


@router.post("/auth/change-password", response_model=UserOut)
def change_password(
    payload: PasswordChangeIn,
    authorization: Optional[str] = Header(default=None),
    user: User = Depends(get_user_changing_password),
    db: Session = Depends(get_db),
):
    """The user sets a password of their own: the current one first, then a new one that passes password_problems.
    Clears must_change_password, and logs the account out everywhere else (this session stays)."""
    if not password_matches(user, payload.current_password):
        raise HTTPException(400, "Your current password is not right.")
    problems = password_problems(payload.new_password)
    if problems:
        raise HTTPException(400, "The new password needs " + ", ".join(problems) + ".")
    if payload.new_password == payload.current_password:
        raise HTTPException(400, "Choose a new password that is different from the current one.")
    user.password_hash, user.password_salt = hash_password(payload.new_password)
    user.must_change_password = False
    current = authorization.split(" ", 1)[1].strip() if authorization and " " in authorization else ""
    db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.token != current).delete(
        synchronize_session=False)
    db.commit()
    return _user_out(user, db)


# Wrong passwords at /auth/login: 10 in 15 minutes per account, then no more tries until the oldest ages out.
login_limiter = _UnlockLimiter(tries=10, window=15 * 60)
