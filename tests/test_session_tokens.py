"""Session tokens are stored as SHA-256 hashes, never as the token itself (app/auth.py): a copy of the database holds
nothing that logs anyone in, and sessions saved before the change are upgraded at startup without logging anyone out."""

import hashlib
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.auth import hash_stored_session_tokens, session_token_hash
from app.db import SessionLocal
from app.main import app as fastapi_app
from app.models import AuthSession, User
from tests.auth_helpers import admin_token, auth_headers, create_student

client = TestClient(fastapi_app)
H = auth_headers
STRONG = "Str0ng!pass"


def _rows(user_id):
    with SessionLocal() as db:
        return [s.token for s in db.query(AuthSession).filter(AuthSession.user_id == user_id)]


def test_only_the_hash_of_a_token_is_stored():
    admin = admin_token(client)
    student, token = create_student(client, admin, [])
    stored = _rows(student["id"])
    assert token not in stored
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert client.get("/auth/me", headers=H(token)).status_code == 200


def test_a_hash_taken_from_the_database_does_not_log_in():
    admin = admin_token(client)
    student, _token = create_student(client, admin, [])
    (stolen,) = _rows(student["id"])
    assert client.get("/auth/me", headers=H(stolen)).status_code == 401


def test_logout_ends_the_session():
    admin = admin_token(client)
    student, token = create_student(client, admin, [])
    assert client.post("/auth/logout", headers=H(token)).status_code == 200
    assert _rows(student["id"]) == []
    assert client.get("/auth/me", headers=H(token)).status_code == 401


def test_changing_the_password_keeps_this_session_and_ends_the_others():
    admin = admin_token(client)
    student, here = create_student(client, admin, [], password="abcd")
    elsewhere = client.post("/auth/login", json={"email": student["email"], "password": "abcd"}).json()["token"]
    r = client.post("/auth/change-password", headers=H(here),
                    json={"current_password": "abcd", "new_password": STRONG})
    assert r.status_code == 200, r.text
    assert client.get("/auth/me", headers=H(here)).status_code == 200  # the session used for the change stays
    assert client.get("/auth/me", headers=H(elsewhere)).status_code == 401  # every other one is logged out
    assert _rows(student["id"]) == [session_token_hash(here)]


def test_an_admin_password_reset_ends_every_session():
    admin = admin_token(client)
    student, token = create_student(client, admin, [])
    r = client.put(f"/admin/students/{student['id']}", headers=H(admin), json={"password": "reset-1"})
    assert r.status_code == 200, r.text
    assert client.get("/auth/me", headers=H(token)).status_code == 401
    assert _rows(student["id"]) == []


def test_sessions_saved_before_hashing_still_work_after_the_upgrade():
    admin = admin_token(client)
    student, _ = create_student(client, admin, [])
    old_token = secrets.token_urlsafe(32)  # what a login stored before this change: the token itself
    with SessionLocal() as db:
        db.add(AuthSession(token=old_token, user_id=student["id"],
                           expires_at=datetime.utcnow() + timedelta(days=1)))
        db.commit()
    assert old_token in _rows(student["id"])
    assert client.get("/auth/me", headers=H(old_token)).status_code == 401  # until upgraded, it is not found

    with SessionLocal() as db:
        assert hash_stored_session_tokens(db) >= 1
    rows = _rows(student["id"])
    assert old_token not in rows and session_token_hash(old_token) in rows
    assert client.get("/auth/me", headers=H(old_token)).status_code == 200  # the user is still logged in

    with SessionLocal() as db:  # running it again changes nothing
        assert hash_stored_session_tokens(db) == 0
    assert sorted(_rows(student["id"])) == sorted(rows)


def test_no_session_token_is_stored_in_plain_text():
    admin = admin_token(client)
    create_student(client, admin, [])
    with SessionLocal() as db:
        with_users = db.query(AuthSession).join(User, User.id == AuthSession.user_id).all()
        assert with_users
        assert all(len(s.token) == 64 and set(s.token) <= set("0123456789abcdef") for s in with_users)
