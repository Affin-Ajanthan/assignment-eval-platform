"""How a student gets into a subject: the instructor opens it with a password (PUT /instructor/subjects/{id}/access),
the student sees the open subjects (GET /student/open-subjects) and joins one with the password
(POST /student/subjects/{id}/join)."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app as fastapi_app
from tests.auth_helpers import admin_token, auth_headers, create_instructor, create_student, create_subject

client = TestClient(fastapi_app)
H = auth_headers


def _setup():
    """An admin, a subject given to an instructor only, and a student with no subjects."""
    admin = admin_token(client)
    subject = create_subject(client, admin)
    _, instructor = create_instructor(client, admin, [subject["id"]])
    _, student = create_student(client, admin, [])
    return admin, subject, instructor, student


def _open(instructor, subject, password="join-me", **extra):
    return client.put(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor),
                      json={"open": True, "password": password, **extra})


def _join(student, subject, password):
    return client.post(f"/student/subjects/{subject['id']}/join", headers=H(student), json={"password": password})


def _my_subject_ids(student):
    return [s["id"] for s in client.get("/auth/me", headers=H(student)).json()["subjects"]]


def _open_ids(student):
    return [s["id"] for s in client.get("/student/open-subjects", headers=H(student)).json()]


def test_a_subject_is_closed_until_the_instructor_opens_it():
    _, subject, instructor, student = _setup()
    r = client.get(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor))
    assert r.status_code == 200 and r.json() == {"open": False, "password": ""}
    assert subject["id"] not in _open_ids(student)
    assert _join(student, subject, "anything").status_code == 404
    assert _my_subject_ids(student) == []


def test_an_open_subject_is_joined_with_its_password():
    _, subject, instructor, student = _setup()
    r = _open(instructor, subject, "  Secret 1 ")
    assert r.status_code == 200 and r.json() == {"open": True, "password": "Secret 1"}  # trimmed, readable back

    listed = {s["id"]: s for s in client.get("/student/open-subjects", headers=H(student)).json()}
    assert subject["id"] in listed
    assert {"id", "name", "code", "batch", "instructors"} <= set(listed[subject["id"]])
    assert "password" not in listed[subject["id"]]  # a student never sees it
    assert listed[subject["id"]]["instructors"] == ["Test Instructor"]

    assert _join(student, subject, "wrong").status_code == 403
    assert _my_subject_ids(student) == []
    assert _join(student, subject, "Secret 1").status_code == 200
    assert _my_subject_ids(student) == [subject["id"]]
    assert subject["id"] not in _open_ids(student)  # joined: no longer offered
    assert _join(student, subject, "wrong").status_code == 200  # already in: nothing to check, nothing doubled
    assert _my_subject_ids(student) == [subject["id"]]


def test_a_joined_student_can_use_the_subject():
    """Joining is a normal enrolment: the student now sees the subject's assignments."""
    from tests.auth_helpers import create_assignment

    _, subject, instructor, student = _setup()
    assignment = create_assignment(client, instructor, subject["id"])
    assert client.get("/assignments", headers=H(student)).json() == []
    _open(instructor, subject)
    assert _join(student, subject, "join-me").status_code == 200
    assert [a["id"] for a in client.get("/assignments", headers=H(student)).json()] == [assignment["id"]]


def test_opening_needs_a_password_and_closing_keeps_it():
    _, subject, instructor, _student = _setup()
    url = f"/instructor/subjects/{subject['id']}/access"
    assert client.put(url, headers=H(instructor), json={"open": True}).status_code == 400  # no password yet
    assert client.put(url, headers=H(instructor), json={"open": True, "password": "  "}).status_code == 400

    assert _open(instructor, subject, "pw1").status_code == 200
    r = client.put(url, headers=H(instructor), json={"open": True})  # password left out: kept
    assert r.json() == {"open": True, "password": "pw1"}
    r = client.put(url, headers=H(instructor), json={"open": False})
    assert r.json() == {"open": False, "password": "pw1"}
    assert client.put(url, headers=H(instructor), json={"open": True, "password": ""}).status_code == 400  # removed


def test_closing_stops_new_students_but_keeps_the_ones_in():
    admin, subject, instructor, student = _setup()
    _open(instructor, subject)
    assert _join(student, subject, "join-me").status_code == 200
    client.put(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor), json={"open": False})

    _, late = create_student(client, admin, [])
    assert subject["id"] not in _open_ids(late)
    assert _join(late, subject, "join-me").status_code == 404
    assert _my_subject_ids(student) == [subject["id"]]  # still in


def test_too_many_wrong_passwords_make_a_student_wait():
    _, subject, instructor, student = _setup()
    _open(instructor, subject)
    codes = [_join(student, subject, f"guess{i}").status_code for i in range(8)]
    assert codes == [403] * 8
    assert _join(student, subject, "guess9").status_code == 429
    assert _join(student, subject, "join-me").status_code == 429  # even the right one, until the wait is over
    assert _my_subject_ids(student) == []


def test_only_the_subjects_own_instructor_sets_the_access():
    admin, subject, instructor, student = _setup()
    other_subject = create_subject(client, admin)
    _, other_instructor = create_instructor(client, admin, [other_subject["id"]])
    url = f"/instructor/subjects/{subject['id']}/access"

    assert client.put(url, headers=H(other_instructor), json={"open": True, "password": "x"}).status_code == 403
    assert client.get(url, headers=H(other_instructor)).status_code == 403
    assert client.put(url, headers=H(student), json={"open": True, "password": "x"}).status_code == 403
    assert client.get(url, headers=H(admin)).status_code == 403
    assert client.get(url).status_code in (401, 403)


def test_only_students_join():
    admin, subject, instructor, student = _setup()
    _open(instructor, subject)
    url = f"/student/subjects/{subject['id']}/join"
    assert client.post(url, headers=H(instructor), json={"password": "join-me"}).status_code == 403
    assert client.get("/student/open-subjects", headers=H(instructor)).status_code == 403
    assert client.post("/student/subjects/999999/join", headers=H(student), json={"password": "x"}).status_code == 404
