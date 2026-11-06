"""How a student gets into a subject: every subject is listed to every student (GET /student/subjects), but only a
student who joined can see its assignments. The student joins with the subject's password
(POST /student/subjects/{id}/join) once the instructor has set the password and allowed registration
(PUT /instructor/subjects/{id}/access)."""

import sys
from datetime import datetime, timedelta, timezone
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
    assert r.status_code == 200 and r.json() == {"open": False, "password": "", "ends_at": None, "expired": False}

    shown = _listed(student)[subject["id"]]  # shown at once, but not joined and registration is not open
    assert (shown["joined"], shown["registration_open"]) == (False, False)
    refused = _join(student, subject, "anything")
    assert refused.status_code == 403 and "not open yet" in refused.json()["detail"]
    assert _my_subject_ids(student) == []


def test_a_listed_subject_is_joined_with_its_password_once_allowed():
    _, subject, instructor, student = _setup()
    r = _open(instructor, subject, "  Secret 1 ")
    assert r.status_code == 200
    assert r.json() == {"open": True, "password": "Secret 1", "ends_at": None, "expired": False}  # trimmed, readable back

    rows = _listed(student)
    assert rows[subject["id"]]["registration_open"] is True and rows[subject["id"]]["joined"] is False
    assert {"id", "name", "code", "batch", "teachers", "joined", "registration_open"} <= set(rows[subject["id"]])
    assert "password" not in rows[subject["id"]]  # a student never sees it
    # The teachers' names are shown to everyone, their e-mail only once the student has joined.
    assert rows[subject["id"]]["teachers"] == [{"name": "Test Instructor", "email": ""}]

    assert _join(student, subject, "wrong").status_code == 403
    assert _my_subject_ids(student) == []
    assert _join(student, subject, "Secret 1").status_code == 200
    assert _my_subject_ids(student) == [subject["id"]]
    after = _listed(student)[subject["id"]]  # still listed, now as one of theirs
    assert after["joined"] is True
    assert [t["name"] for t in after["teachers"]] == ["Test Instructor"] and "@" in after["teachers"][0]["email"]
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
    assert r.json() == {"open": True, "password": "pw1", "ends_at": None, "expired": False}
    r = client.put(url, headers=H(instructor), json={"open": False})
    assert r.json() == {"open": False, "password": "pw1", "ends_at": None, "expired": False}
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


def _in(hours):
    """An ISO time `hours` from now (UTC), as the instructor's page sends it."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _pretend_now_is(monkeypatch, hours_from_now):
    """Makes the join/access code see a later clock, so an end date can pass without waiting."""
    later = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours_from_now)
    monkeypatch.setattr("app.routers.subject_access.utcnow_naive", lambda: later)


def test_an_end_date_must_be_in_the_future_and_is_shown_while_open():
    _, subject, instructor, student = _setup()
    url = f"/instructor/subjects/{subject['id']}/access"
    past = client.put(url, headers=H(instructor), json={"open": True, "password": "pw", "ends_at": _in(-1)})
    assert past.status_code == 400 and "future" in past.json()["detail"]

    ok = client.put(url, headers=H(instructor), json={"open": True, "password": "pw", "ends_at": _in(3)})
    assert ok.status_code == 200 and ok.json()["open"] is True and ok.json()["ends_at"] is not None
    assert ok.json()["expired"] is False
    shown = _listed(student)[subject["id"]]  # the student sees when it closes
    assert shown["registration_open"] is True and shown["registration_ends_at"] is not None

    cleared = client.put(url, headers=H(instructor), json={"open": True, "ends_at": None})  # no end date any more
    assert cleared.json()["ends_at"] is None
    assert _listed(student)[subject["id"]]["registration_ends_at"] is None


def test_registration_closes_at_the_end_date_and_keeps_the_students_in(monkeypatch):
    admin, subject, instructor, early = _setup()
    _, late = create_student(client, admin, [])
    _open(instructor, subject, "join-me", ends_at=_in(1))
    assert _join(early, subject, "join-me").status_code == 200

    _pretend_now_is(monkeypatch, 2)  # the end date has passed
    refused = _join(late, subject, "join-me")
    assert refused.status_code == 403 and "closed" in refused.json()["detail"]
    assert _my_subject_ids(late) == []
    assert _listed(late)[subject["id"]]["registration_open"] is False
    assert _listed(late)[subject["id"]]["registration_ends_at"] is None  # nothing to join before, so no date shown
    state = client.get(f"/instructor/subjects/{subject['id']}/access", headers=H(instructor)).json()
    assert (state["open"], state["expired"]) == (False, True) and state["password"] == "join-me"
    assert _my_subject_ids(early) == [subject["id"]]  # the one who joined in time stays in


def test_registration_opens_again_with_the_same_password(monkeypatch):
    admin, subject, instructor, early = _setup()
    _, late = create_student(client, admin, [])
    url = f"/instructor/subjects/{subject['id']}/access"
    _open(instructor, subject, "join-me", ends_at=_in(1))
    _pretend_now_is(monkeypatch, 2)

    # Switching it on again without a later date is refused: the saved one is still in the past.
    assert client.put(url, headers=H(instructor), json={"open": True}).status_code == 400
    assert _join(late, subject, "join-me").status_code == 403

    again = client.put(url, headers=H(instructor), json={"open": True, "ends_at": _in(5)})  # a later date
    assert again.status_code == 200 and again.json()["open"] is True and again.json()["password"] == "join-me"
    assert _join(late, subject, "join-me").status_code == 200  # the same password works again
    assert _my_subject_ids(late) == [subject["id"]]


def test_registration_opens_again_with_a_new_password_and_the_old_one_stops_working(monkeypatch):
    admin, subject, instructor, early = _setup()
    _, late = create_student(client, admin, [])
    url = f"/instructor/subjects/{subject['id']}/access"
    _open(instructor, subject, "old-pass", ends_at=_in(1))
    assert _join(early, subject, "old-pass").status_code == 200
    _pretend_now_is(monkeypatch, 2)

    again = client.put(url, headers=H(instructor), json={"open": True, "password": "new-pass", "ends_at": _in(5)})
    assert again.status_code == 200 and again.json()["password"] == "new-pass"
    assert _join(late, subject, "old-pass").status_code == 403  # the old password is dead
    assert _my_subject_ids(late) == []
    assert _join(late, subject, "new-pass").status_code == 200
    assert _my_subject_ids(early) == [subject["id"]]  # changing the password removed nobody


def test_changing_the_password_never_removes_a_student_who_joined():
    admin, subject, instructor, student = _setup()
    _open(instructor, subject, "first")
    assert _join(student, subject, "first").status_code == 200
    _open(instructor, subject, "second")
    assert _my_subject_ids(student) == [subject["id"]]
    assert _listed(student)[subject["id"]]["joined"] is True
    assert _join(student, subject, "first").status_code == 200  # already in: nothing to check
    _, other = create_student(client, admin, [])
    assert _join(other, subject, "first").status_code == 403  # the old password no longer lets anyone in
    assert _join(other, subject, "second").status_code == 200


def test_the_admin_can_add_a_student_to_a_subject_without_the_password():
    from tests.auth_helpers import create_assignment

    admin, subject, instructor, _student = _setup()
    assignment = create_assignment(client, instructor, subject["id"])
    user, student = create_student(client, admin, [])
    assert _my_subject_ids(student) == []  # registration was never opened: only the admin can add them

    r = client.put(f"/admin/students/{user['id']}", headers=H(admin), json={"subject_ids": [subject["id"]]})
    assert r.status_code == 200 and [s["id"] for s in r.json()["subjects"]] == [subject["id"]]
    assert _my_subject_ids(student) == [subject["id"]]
    assert _listed(student)[subject["id"]]["joined"] is True
    assert [a["id"] for a in client.get("/assignments", headers=H(student)).json()] == [assignment["id"]]

    # Saving the student again with the same list keeps them in; with an empty list it takes them out.
    client.put(f"/admin/students/{user['id']}", headers=H(admin), json={"subject_ids": [subject["id"]]})
    assert _my_subject_ids(student) == [subject["id"]]
    client.put(f"/admin/students/{user['id']}", headers=H(admin), json={"subject_ids": []})
    assert _my_subject_ids(student) == []


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
