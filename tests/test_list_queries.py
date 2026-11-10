"""The people and assignment lists read the database a fixed number of times, however long they are (no query per
row), and their counts stay right. A list that is twice as long must not take more queries."""

import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import event

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal, engine
from app.main import app as fastapi_app
from app.models import Submission
from tests.auth_helpers import admin_token, auth_headers, create_instructor, create_student, create_subject

client = TestClient(fastapi_app)
H = auth_headers


@contextmanager
def counted():
    seen = {"n": 0}

    def count(*_args):
        seen["n"] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", count)


def _queries(path, token):
    client.get(path, headers=H(token))  # warm up
    with counted() as seen:
        r = client.get(path, headers=H(token))
    assert r.status_code == 200, r.text
    return seen["n"], r.json()


def _assignment(token, subject_id, name):
    now = datetime.now(timezone.utc)
    r = client.post("/assignments", headers=H(token), json={
        "subject_id": subject_id, "name": name, "description": "",
        "available_from": (now - timedelta(days=1)).isoformat(), "deadline": (now + timedelta(days=7)).isoformat(),
        "rubric_id": None, "submission_types": ["code"]})
    assert r.status_code == 200, r.text
    return r.json()


def _submissions(assignment, student_ids, graded=(), late=()):
    with SessionLocal() as db:
        for sid in student_ids:
            db.add(Submission(student_id=sid, subject_id=assignment["subject_id"], assignment_id=assignment["id"],
                              assignment_name=assignment["name"],
                              status="graded" if sid in graded else "submitted",
                              late_seconds=3600 if sid in late else None))
        db.commit()


def test_the_student_list_takes_the_same_queries_however_many_students():
    admin = admin_token(client)
    subjects = [create_subject(client, admin)["id"] for _ in range(2)]
    mine = {create_student(client, admin, subjects)[0]["id"] for _ in range(3)}
    few, body = _queries("/admin/students", admin)
    mine |= {create_student(client, admin, subjects)[0]["id"] for _ in range(12)}
    many, body = _queries("/admin/students", admin)
    assert many == few, f"{few} queries before, {many} after adding 12 students"
    listed = {s["id"]: s for s in body}
    assert all(sorted(x["id"] for x in listed[i]["subjects"]) == sorted(subjects) for i in mine)


def test_the_instructor_list_takes_the_same_queries_however_many_instructors():
    admin = admin_token(client)
    subject = create_subject(client, admin)["id"]
    create_instructor(client, admin, [subject])
    few, _ = _queries("/admin/instructors", admin)
    for _ in range(6):
        create_instructor(client, admin, [subject])
    many, body = _queries("/admin/instructors", admin)
    assert many == few
    assert all(subject in [s["id"] for s in i["subjects"]] for i in body[-6:])


def test_the_instructor_assignment_list_takes_the_same_queries_and_counts_right():
    admin = admin_token(client)
    subject = create_subject(client, admin)["id"]
    _inst, token = create_instructor(client, admin, [subject])
    students = [create_student(client, admin, [subject])[0]["id"] for _ in range(4)]
    first = _assignment(token, subject, "Counted 1")
    _submissions(first, students, graded=students[:2], late=students[:1])
    few, _ = _queries(f"/assignments?subject_id={subject}", token)
    for i in range(2, 7):
        _submissions(_assignment(token, subject, f"Counted {i}"), students[:i % 4 + 1])
    many, body = _queries(f"/assignments?subject_id={subject}", token)
    assert many == few, f"{few} queries for 1 assignment, {many} for 6"
    counted_first = next(a for a in body if a["id"] == first["id"])
    assert (counted_first["submission_count"], counted_first["graded_count"], counted_first["late_count"]) == (4, 2, 1)
    empty = _assignment(token, subject, "No submissions")
    one = client.get(f"/assignments/{empty['id']}", headers=H(token)).json()
    assert (one["submission_count"], one["graded_count"], one["late_count"]) == (0, 0, 0)


def test_the_student_assignment_list_shows_each_students_own_latest_submission():
    admin = admin_token(client)
    subject = create_subject(client, admin)["id"]
    _inst, token = create_instructor(client, admin, [subject])
    me, my_token = create_student(client, admin, [subject])
    other, _ = create_student(client, admin, [subject])
    mine_done = _assignment(token, subject, "Handed in")
    not_mine = _assignment(token, subject, "Only the other student")
    _submissions(mine_done, [me["id"]])
    _submissions(mine_done, [me["id"]], graded=[me["id"]])  # a later one: this is the one shown
    _submissions(not_mine, [other["id"]])
    body = {a["name"]: a for a in client.get(f"/assignments?subject_id={subject}", headers=H(my_token)).json()}
    assert body["Handed in"]["my_submission"] is not None
    assert body["Only the other student"]["my_submission"] is None
    with SessionLocal() as db:
        latest = (db.query(Submission).filter(Submission.student_id == me["id"],
                                              Submission.assignment_id == mine_done["id"])
                  .order_by(Submission.id.desc()).first())
    assert body["Handed in"]["my_submission"]["id"] == latest.id
