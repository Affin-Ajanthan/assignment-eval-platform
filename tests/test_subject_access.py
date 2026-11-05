"""How a student gets into a subject: every subject is listed to every student (GET /student/subjects), but only a
student who joined can see its assignments. The student joins with the subject's password
(POST /student/subjects/{id}/join) once the instructor has set the password and allowed registration
(PUT /instructor/subjects/{id}/access)."""

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


def _listed(student):
    """Every subject the student is shown: id -> the entry."""
    rows = client.get("/student/subjects", headers=H(student)).json()
    return {s["id"]: s for s in rows}


def test_a_new_subject_is_listed_to_students_but_cannot_be_joined_until_allowed():
    _, subject, instructor, student = _setup()
    r = client.get(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor))
    assert r.status_code == 200 and r.json() == {"open": False, "password": ""}

    shown = _listed(student)[subject["id"]]  # shown at once, but not joined and registration is not open
    assert (shown["joined"], shown["registration_open"]) == (False, False)
    refused = _join(student, subject, "anything")
    assert refused.status_code == 403 and "not open yet" in refused.json()["detail"]
    assert _my_subject_ids(student) == []


def test_a_listed_subject_is_joined_with_its_password_once_allowed():
    _, subject, instructor, student = _setup()
    r = _open(instructor, subject, "  Secret 1 ")
    assert r.status_code == 200 and r.json() == {"open": True, "password": "Secret 1"}  # trimmed, readable back

    rows = _listed(student)
    assert rows[subject["id"]]["registration_open"] is True and rows[subject["id"]]["joined"] is False
    assert {"id", "name", "code", "batch", "instructors", "joined", "registration_open"} <= set(rows[subject["id"]])
    assert "password" not in rows[subject["id"]]  # a student never sees it
    assert rows[subject["id"]]["instructors"] == ["Test Instructor"]

    assert _join(student, subject, "wrong").status_code == 403
    assert _my_subject_ids(student) == []
    assert _join(student, subject, "Secret 1").status_code == 200
    assert _my_subject_ids(student) == [subject["id"]]
    assert _listed(student)[subject["id"]]["joined"] is True  # still listed, now as one of theirs
    assert _join(student, subject, "wrong").status_code == 200  # already in: nothing to check, nothing doubled
    assert _my_subject_ids(student) == [subject["id"]]


def test_a_joined_student_can_use_the_subject():
    """Joining is a normal enrolment: only then can the student open the subject and see its assignments."""
    from tests.auth_helpers import create_assignment

    _, subject, instructor, student = _setup()
    assignment = create_assignment(client, instructor, subject["id"])
    assert client.get("/assignments", headers=H(student)).json() == []
    # Listed, but its assignments stay closed to a student who has not joined.
    assert client.get(f"/assignments?subject_id={subject['id']}", headers=H(student)).status_code == 403
    assert client.get(f"/assignments/{assignment['id']}", headers=H(student)).status_code in (403, 404)
    _open(instructor, subject)
    assert _join(student, subject, "join-me").status_code == 200
    assert [a["id"] for a in client.get("/assignments", headers=H(student)).json()] == [assignment["id"]]
    assert [a["id"] for a in client.get(f"/assignments?subject_id={subject['id']}", headers=H(student)).json()] == [
        assignment["id"]
    ]


def test_allowing_needs_a_password_and_switching_off_keeps_it():
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


def test_a_password_alone_does_not_open_registration():
    """A password with registration switched off: still listed, still not joinable."""
    _, subject, instructor, student = _setup()
    client.put(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor),
               json={"open": False, "password": "ready"})
    assert _listed(student)[subject["id"]]["registration_open"] is False
    assert _join(student, subject, "ready").status_code == 403


def test_switching_registration_off_stops_new_students_but_keeps_the_ones_in():
    admin, subject, instructor, student = _setup()
    _open(instructor, subject)
    assert _join(student, subject, "join-me").status_code == 200
    client.put(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor), json={"open": False})

    _, late = create_student(client, admin, [])
    assert _listed(late)[subject["id"]]["registration_open"] is False  # still listed
    assert _join(late, subject, "join-me").status_code == 403
    assert _my_subject_ids(late) == []
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
    assert client.get("/student/subjects", headers=H(instructor)).status_code == 403
    assert client.post("/student/subjects/999999/join", headers=H(student), json={"password": "x"}).status_code == 404
