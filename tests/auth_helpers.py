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

from datetime import datetime, timedelta, timezone

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


_subject_instructor_tokens: dict[int, str] = {}


def setup_subject_with_users(client, name=None, code=None):
    """Convenience: one subject + one instructor assigned to it + one
    student enrolled in it. Returns (subject, instructor_token, student_token)."""
    admin_tok = admin_token(client)
    subject = create_subject(client, admin_tok, name, code)
    _, instructor_tok = create_instructor(client, admin_tok, [subject["id"]])
    _, student_tok = create_student(client, admin_tok, [subject["id"]])
    _subject_instructor_tokens[subject["id"]] = instructor_tok
    return subject, instructor_tok, student_tok


def create_assignment(client, instructor_tok, subject_id, name=None, *, opens_in=timedelta(hours=-1),
                      closes_in=timedelta(days=7), rubric_id=None, description=""):
    """An assignment whose window is relative to now (open by default)."""
    now = datetime.now(timezone.utc)
    r = client.post(
        "/assignments",
        json={
            "subject_id": subject_id,
            "name": name or _unique("Assignment "),
            "description": description,
            "available_from": (now + opens_in).isoformat(),
            "deadline": (now + closes_in).isoformat(),
            "rubric_id": rubric_id,
        },
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 200, r.text
    return r.json()


def ensure_assignment(client, subject_id, name):
    """The subject's assignment called `name`, created (open now) if it
    doesn't exist yet. The subject must come from setup_subject_with_users."""
    instructor_tok = _subject_instructor_tokens[subject_id]
    listed = client.get(f"/assignments?subject_id={subject_id}", headers=auth_headers(instructor_tok)).json()
    for a in listed:
        if a["name"].casefold() == name.casefold():
            return a
    return create_assignment(client, instructor_tok, subject_id, name)


def new_student(client, subject_id):
    """Token for a fresh student enrolled in the subject (one student can
    submit an assignment only once, so multi-submission tests need several)."""
    _, tok = create_student(client, admin_token(client), [subject_id])
    return tok


def submit(client, subject_id, assignment_name, files, student_tok=None):
    """Submit `files` to the named assignment (created open if needed), as
    `student_tok` or as a fresh student. Returns the raw response."""
    assignment = ensure_assignment(client, subject_id, assignment_name)
    return client.post(
        "/submissions",
        data={"subject_id": subject_id, "assignment_id": assignment["id"]},
        files=files,
        headers=auth_headers(student_tok or new_student(client, subject_id)),
    )
