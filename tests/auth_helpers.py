"""Shared helpers for setting up an authenticated admin/instructor/
student flow in tests: create a subject, create an instructor assigned
to it, create a student enrolled in it, and hand back tokens for
making authenticated requests as either of them.

Every account in the app is created by an admin (see app/main.py's
/admin/* endpoints) -- there is no self-registration -- so any test
that needs an instructor or student account has to go through this
same admin-driven setup, which is exactly what these helpers do.
"""

from __future__ import annotations

DEFAULT_ADMIN_EMAIL = "admin@school.local"
DEFAULT_ADMIN_PASSWORD = "admin123"

_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']}"


def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def admin_token(client):
    return login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)


def create_subject(client, admin_tok, name=None, code=None):
    name = name or _unique("Subject ")
    code = code or _unique("SUBJ")
    r = client.post("/admin/subjects", json={"name": name, "code": code}, headers=auth_headers(admin_tok))
    assert r.status_code == 200, r.text
    return r.json()


def create_instructor(client, admin_tok, subject_ids, email=None, full_name="Test Instructor", password="instructor123"):
    email = email or _unique("instructor") + "@example.com"
    r = client.post(
        "/admin/instructors",
        json={"email": email, "full_name": full_name, "password": password, "subject_ids": subject_ids},
        headers=auth_headers(admin_tok),
    )
    assert r.status_code == 200, r.text
    user = r.json()
    return user, login(client, email, password)


def create_student(client, admin_tok, subject_ids, email=None, full_name="Test Student", password="student123"):
    email = email or _unique("student") + "@example.com"
    r = client.post(
        "/admin/students",
        json={"email": email, "full_name": full_name, "password": password, "subject_ids": subject_ids},
        headers=auth_headers(admin_tok),
    )
    assert r.status_code == 200, r.text
    user = r.json()
    return user, login(client, email, password)


def setup_subject_with_users(client, name=None, code=None):
    """Convenience: one subject + one instructor assigned to it + one
    student enrolled in it. Returns (subject, instructor_token, student_token)."""
    admin_tok = admin_token(client)
    subject = create_subject(client, admin_tok, name, code)
    _, instructor_tok = create_instructor(client, admin_tok, [subject["id"]])
    _, student_tok = create_student(client, admin_tok, [subject["id"]])
    return subject, instructor_tok, student_tok
