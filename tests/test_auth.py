"""
Tests for accounts, roles and subject-wise access control: admin-only
account/subject management, login, and the scoping rules that keep an
instructor confined to their assigned subjects and a student confined
to their enrolled ones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    admin_token,
    auth_headers,
    create_instructor,
    create_student,
    create_subject,
    setup_subject_with_users,
)

client = TestClient(fastapi_app)


def test_default_admin_can_log_in():
    r = client.post("/auth/login", json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert "token" in body


def test_login_rejects_wrong_password():
    r = client.post("/auth/login", json={"email": DEFAULT_ADMIN_EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_login_rejects_unknown_email():
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert r.status_code == 401


def test_endpoints_require_a_token():
    assert client.get("/auth/me").status_code == 401
    assert client.get("/admin/subjects").status_code == 401
    assert client.get("/rubrics").status_code == 401


def test_non_admin_cannot_reach_admin_endpoints():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    for tok in (instructor_tok, student_tok):
        assert client.get("/admin/subjects", headers=auth_headers(tok)).status_code == 403
        assert client.post(
            "/admin/subjects", json={"name": "X", "code": "X1"}, headers=auth_headers(tok)
        ).status_code == 403


def test_admin_creates_subject_instructor_and_student():
    admin_tok = admin_token(client)
    subject = create_subject(client, admin_tok, "Algorithms", "CS301-unique")
    instructor, instructor_tok = create_instructor(client, admin_tok, [subject["id"]], full_name="Prof. Ada")
    student, student_tok = create_student(client, admin_tok, [subject["id"]], full_name="Grace")

    assert instructor["role"] == "instructor"
    assert instructor["subjects"][0]["code"] == "CS301-unique"
    assert student["role"] == "student"
    assert student["subjects"][0]["code"] == "CS301-unique"

    me_instructor = client.get("/auth/me", headers=auth_headers(instructor_tok)).json()
    assert me_instructor["full_name"] == "Prof. Ada"
    me_student = client.get("/auth/me", headers=auth_headers(student_tok)).json()
    assert me_student["full_name"] == "Grace"


def test_admin_cannot_create_duplicate_email():
    admin_tok = admin_token(client)
    subject = create_subject(client, admin_tok)
    create_instructor(client, admin_tok, [subject["id"]], email="dupe@example.com")
    r = client.post(
        "/admin/instructors",
        json={"email": "dupe@example.com", "full_name": "Someone Else", "password": "whatever1", "subject_ids": []},
        headers=auth_headers(admin_tok),
    )
    assert r.status_code == 400


def test_admin_can_reassign_instructor_subjects():
    admin_tok = admin_token(client)
    subject_a = create_subject(client, admin_tok)
    subject_b = create_subject(client, admin_tok)
    instructor, instructor_tok = create_instructor(client, admin_tok, [subject_a["id"]])
    assert len(instructor["subjects"]) == 1

    r = client.put(
        f"/admin/instructors/{instructor['id']}/subjects",
        json={"subject_ids": [subject_a["id"], subject_b["id"]]},
        headers=auth_headers(admin_tok),
    )
    assert r.status_code == 200
    assert {s["id"] for s in r.json()["subjects"]} == {subject_a["id"], subject_b["id"]}

    # The instructor's own session immediately reflects the new assignment.
    me = client.get("/auth/me", headers=auth_headers(instructor_tok)).json()
    assert {s["id"] for s in me["subjects"]} == {subject_a["id"], subject_b["id"]}


def test_instructor_cannot_create_rubric_outside_assigned_subject():
    admin_tok = admin_token(client)
    subject_mine = create_subject(client, admin_tok)
    subject_other = create_subject(client, admin_tok)
    _, instructor_tok = create_instructor(client, admin_tok, [subject_mine["id"]])

    r = client.post(
        "/rubrics",
        json={"name": "Not mine", "subject_id": subject_other["id"], "criteria": [{"name": "X", "max_points": 10}]},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 403


def test_student_cannot_submit_outside_enrolled_subject():
    admin_tok = admin_token(client)
    subject_mine = create_subject(client, admin_tok)
    subject_other = create_subject(client, admin_tok)
    _, student_tok = create_student(client, admin_tok, [subject_mine["id"]])

    r = client.post(
        "/submissions",
        data={"subject_id": subject_other["id"], "assignment_name": "HW1"},
        headers=auth_headers(student_tok),
    )
    assert r.status_code == 403


def test_student_cannot_reach_instructor_endpoints():
    subject, _instructor_tok, student_tok = setup_subject_with_users(client)
    assert client.get("/rubrics", headers=auth_headers(student_tok)).status_code == 403
    assert client.post(
        "/rubrics",
        json={"name": "X", "subject_id": subject["id"], "criteria": [{"name": "C", "max_points": 10}]},
        headers=auth_headers(student_tok),
    ).status_code == 403


def test_logout_invalidates_token():
    admin_tok = admin_token(client)
    subject = create_subject(client, admin_tok)
    _, student_tok = create_student(client, admin_tok, [subject["id"]])

    assert client.get("/auth/me", headers=auth_headers(student_tok)).status_code == 200
    r = client.post("/auth/logout", headers=auth_headers(student_tok))
    assert r.status_code == 200
    assert client.get("/auth/me", headers=auth_headers(student_tok)).status_code == 401
