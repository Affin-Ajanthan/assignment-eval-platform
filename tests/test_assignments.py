"""
Assignments, rubric/criteria management, the submission window, student
mark visibility and role-based access -- all enforced by the API itself.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import BASE_DIR, SessionLocal
from app.main import _ensure_criterion_ids, app
from app.models import Rubric, Submission
from tests.auth_helpers import (
    admin_token,
    auth_headers,
    create_assignment,
    create_instructor,
    create_student,
    create_subject,
    new_student,
    setup_subject_with_users,
)

client = TestClient(app)
H = auth_headers


def _parse_utc(value: str) -> datetime:
    """The API's UTC timestamps end in "Z", which datetime.fromisoformat reads
    only from Python 3.11; this works on 3.10 too."""
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)

THREE_CRITERIA = [
    {"name": "Code Quality", "description": "Quality and structure of the submitted code", "max_points": 10},
    {"name": "Documentation", "description": "Quality of comments and documentation", "max_points": 10},
    {"name": "Functionality", "description": "Whether the required functionality works correctly", "max_points": 20},
]


def _rubric(tok, subject_id, name="Assignment 1 Rubric", criteria=THREE_CRITERIA):
    r = client.post("/rubrics", json={"name": name, "subject_id": subject_id, "criteria": criteria}, headers=H(tok))
    assert r.status_code == 200, r.text
    return r.json()


def _code(text="print('hi')\n", name="solution.py"):
    return {"code": (name, io.BytesIO(text.encode()), "text/x-python")}


def _submit(tok, assignment, files=None):
    return client.post("/submissions", data={"subject_id": assignment["subject_id"], "assignment_id": assignment["id"]},
                       files=files or _code(), headers=H(tok))


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _grade(tok, submission_id, rubric_id, scores, comments="internal note: off-by-one in loop", feedback=None):
    r = client.post(f"/submissions/{submission_id}/grade",
                    json={"rubric_id": rubric_id, "criterion_scores": scores, "comments": comments,
                          "feedback": feedback}, headers=H(tok))
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# One rubric -> many criteria
# --------------------------------------------------------------------------


def test_one_rubric_holds_three_criteria_and_adding_more_never_creates_another_rubric():
    subject, itok, _ = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    assert [c["name"] for c in rubric["criteria"]] == ["Code Quality", "Documentation", "Functionality"]
    assert [c["id"] for c in rubric["criteria"]] == [1, 2, 3]
    assert rubric["max_total"] == 40

    r = client.post(f"/rubrics/{rubric['id']}/criteria",
                    json={"name": "Testing", "description": "Unit tests", "max_points": 5}, headers=H(itok))
    assert r.status_code == 200
    assert r.json()["id"] == rubric["id"] and len(r.json()["criteria"]) == 4 and r.json()["max_total"] == 45

    listed = client.get(f"/rubrics?subject_id={subject['id']}", headers=H(itok)).json()
    assert len(listed) == 1  # still exactly one rubric
    assert [c["name"] for c in listed[0]["criteria"]] == ["Code Quality", "Documentation", "Functionality", "Testing"]


def test_duplicate_rubric_names_are_rejected():
    subject, itok, _ = setup_subject_with_users(client)
    _rubric(itok, subject["id"], name="Assignment 1 Rubric")
    r = client.post("/rubrics", json={"name": "  assignment 1   rubric ", "subject_id": subject["id"],
                                      "criteria": THREE_CRITERIA[:1]}, headers=H(itok))
    assert r.status_code == 409 and "add criteria to it instead" in r.json()["detail"]
    assert len(client.get(f"/rubrics?subject_id={subject['id']}", headers=H(itok)).json()) == 1


def test_edit_and_delete_criteria():
    subject, itok, _ = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    r = client.put(f"/rubrics/{rubric['id']}/criteria/2",
                   json={"name": "Docs & Comments", "max_points": 15}, headers=H(itok))
    assert r.status_code == 200
    docs = next(c for c in r.json()["criteria"] if c["id"] == 2)
    assert docs == {"id": 2, "name": "Docs & Comments", "description": "Quality of comments and documentation",
                    "max_points": 15}

    r = client.delete(f"/rubrics/{rubric['id']}/criteria/1", headers=H(itok))
    assert r.status_code == 200 and [c["id"] for c in r.json()["criteria"]] == [2, 3]
    assert r.json()["max_total"] == 35
    assert client.delete(f"/rubrics/{rubric['id']}/criteria/99", headers=H(itok)).status_code == 404


def test_criterion_validation():
    subject, itok, _ = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    dup = client.post(f"/rubrics/{rubric['id']}/criteria", json={"name": "code quality", "max_points": 3}, headers=H(itok))
    assert dup.status_code == 400 and "unique" in dup.json()["detail"]
    assert client.post(f"/rubrics/{rubric['id']}/criteria", json={"name": "  ", "max_points": 3},
                       headers=H(itok)).status_code == 400
    assert client.post(f"/rubrics/{rubric['id']}/criteria", json={"name": "Zero", "max_points": 0},
                       headers=H(itok)).status_code == 422
    assert client.post("/rubrics", json={"name": "Empty", "subject_id": subject["id"], "criteria": []},
                       headers=H(itok)).status_code == 422
    for cid in (1, 2):
        client.delete(f"/rubrics/{rubric['id']}/criteria/{cid}", headers=H(itok))
    last = client.delete(f"/rubrics/{rubric['id']}/criteria/3", headers=H(itok))
    assert last.status_code == 400 and "at least one criterion" in last.json()["detail"]


def test_rename_and_delete_rubric_detaches_assignments():
    subject, itok, _ = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    assignment = create_assignment(client, itok, subject["id"], "A1", rubric_id=rubric["id"])
    renamed = client.put(f"/rubrics/{rubric['id']}", json={"name": "A1 marking guide"}, headers=H(itok)).json()
    assert renamed["name"] == "A1 marking guide" and renamed["assignment_names"] == ["A1"]

    r = client.delete(f"/rubrics/{rubric['id']}", headers=H(itok))
    assert r.status_code == 200 and r.json()["assignments_detached"] == 1
    a = client.get(f"/assignments/{assignment['id']}", headers=H(itok)).json()
    assert a["rubric_id"] is None and a["name"] == "A1"


def test_rubric_with_grades_is_locked_and_cannot_be_deleted():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    assignment = create_assignment(client, itok, subject["id"], rubric_id=rubric["id"])
    sub = _submit(stok, assignment).json()
    _grade(itok, sub["id"], rubric["id"], {"Code Quality": 8, "Documentation": 6, "Functionality": 20})

    rid = rubric["id"]
    assert client.get(f"/rubrics/{rid}", headers=H(itok)).json()["locked"] is True
    for method, url, body in [
        ("delete", f"/rubrics/{rid}", None),
        ("put", f"/rubrics/{rid}", {"name": "New name"}),
        ("post", f"/rubrics/{rid}/criteria", {"name": "Extra", "max_points": 5}),
        ("put", f"/rubrics/{rid}/criteria/1", {"max_points": 50}),
        ("delete", f"/rubrics/{rid}/criteria/1", None),
    ]:
        r = client.request(method.upper(), url, json=body, headers=H(itok))
        assert r.status_code == 409, (method, url, r.text)
    # Descriptions can still be clarified.
    r = client.put(f"/rubrics/{rid}/criteria/1", json={"description": "Readable, well-structured code"}, headers=H(itok))
    assert r.status_code == 200 and r.json()["criteria"][0]["description"] == "Readable, well-structured code"


def test_criteria_without_ids_are_upgraded():
    subject, itok, _ = setup_subject_with_users(client)
    db = SessionLocal()
    legacy = Rubric(name="Legacy", subject_id=subject["id"],
                    criteria=[{"name": "A", "description": "", "max_points": 2.0},
                              {"name": "B", "description": "", "max_points": 3.0}])
    db.add(legacy)
    db.commit()
    rid = legacy.id
    db.close()
    _ensure_criterion_ids()
    got = client.get(f"/rubrics/{rid}", headers=H(itok)).json()
    assert [(c["id"], c["name"]) for c in got["criteria"]] == [(1, "A"), (2, "B")]


# --------------------------------------------------------------------------
# Assignment configuration
# --------------------------------------------------------------------------


def test_create_edit_and_list_assignment():
    subject, itok, _ = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    r = client.post("/assignments", json={
        "subject_id": subject["id"], "name": "  Assignment 1 ", "description": "Implement a Python calculator.",
        "available_from": "2026-10-07T09:00:00+05:30", "deadline": "2099-10-14T23:59:00+05:30",
        "rubric_id": rubric["id"],
    }, headers=H(itok))
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["name"] == "Assignment 1" and a["rubric_name"] == "Assignment 1 Rubric" and a["max_points"] == 40
    # Stored as UTC, returned with an explicit offset.
    assert _parse_utc(a["available_from"]) == datetime(2026, 10, 7, 3, 30, tzinfo=timezone.utc)
    assert a["status"] == "open"

    r = client.put(f"/assignments/{a['id']}", json={
        "name": "Assignment 1 (Calculator)", "description": "Sum and product of two numbers.",
        "deadline": "2099-10-20T23:59:00Z", "rubric_id": None,
    }, headers=H(itok))
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["name"] == "Assignment 1 (Calculator)" and updated["description"] == "Sum and product of two numbers."
    assert updated["rubric_id"] is None
    assert _parse_utc(updated["deadline"]) == datetime(2099, 10, 20, 23, 59, tzinfo=timezone.utc)
    listed = client.get(f"/assignments?subject_id={subject['id']}", headers=H(itok)).json()
    assert [x["name"] for x in listed] == ["Assignment 1 (Calculator)"]


def test_assignment_validation():
    subject, itok, _ = setup_subject_with_users(client)
    base = {"subject_id": subject["id"], "name": "A", "available_from": _iso(timedelta(0)), "deadline": _iso(timedelta(days=1))}

    def post(**changes):
        return client.post("/assignments", json={**base, **changes}, headers=H(itok))

    assert post(name="   ").status_code == 400
    r = post(deadline=_iso(timedelta(hours=-1)))
    assert r.status_code == 400 and "later than" in r.json()["detail"]
    assert post(deadline=base["available_from"]).status_code == 400  # equal is not "after"
    assert post(available_from="not-a-date").status_code == 422
    assert post(deadline="2026-02-30T10:00:00Z").status_code == 422
    other_subject, other_itok, _ = setup_subject_with_users(client)
    other_rubric = _rubric(other_itok, other_subject["id"])
    assert post(rubric_id=other_rubric["id"]).status_code == 400
    assert post().status_code == 200
    assert post(name="a").status_code == 409  # duplicate name in the subject
    a = client.get(f"/assignments?subject_id={subject['id']}", headers=H(itok)).json()[0]
    r = client.put(f"/assignments/{a['id']}", json={"deadline": _iso(timedelta(days=-30))}, headers=H(itok))
    assert r.status_code == 400  # edit validated against the stored start time too


def test_deleting_an_assignment_keeps_submissions_and_grades():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    assignment = create_assignment(client, itok, subject["id"], "Keep me", rubric_id=rubric["id"])
    sub = _submit(stok, assignment).json()
    _grade(itok, sub["id"], rubric["id"], {"Code Quality": 10, "Documentation": 10, "Functionality": 14})

    r = client.delete(f"/assignments/{assignment['id']}", headers=H(itok))
    assert r.status_code == 200 and r.json()["submissions_kept"] == 1
    kept = client.get(f"/submissions/{sub['id']}", headers=H(itok)).json()
    assert kept["assignment_name"] == "Keep me" and kept["assignment_id"] is None and kept["status"] == "graded"
    assert client.get("/submissions", headers=H(stok)).json()[0]["final_mark"] == 34
    assert client.get("/assignments", headers=H(stok)).json() == []  # gone from the student's list


def test_renaming_an_assignment_keeps_its_submissions_grouped():
    subject, itok, stok = setup_subject_with_users(client)
    assignment = create_assignment(client, itok, subject["id"], "Lab 1")
    sub = _submit(stok, assignment).json()
    client.put(f"/assignments/{assignment['id']}", json={"name": "Lab 1 - Sorting"}, headers=H(itok))
    assert client.get(f"/submissions/{sub['id']}", headers=H(itok)).json()["assignment_name"] == "Lab 1 - Sorting"


def test_legacy_free_text_submissions_are_linked_when_the_assignment_is_created():
    subject, itok, stok = setup_subject_with_users(client)
    student = client.get("/auth/me", headers=H(stok)).json()
    db = SessionLocal()
    legacy = Submission(student_id=student["id"], subject_id=subject["id"], assignment_name="quiz 1 ")
    db.add(legacy)
    db.commit()
    legacy_id = legacy.id
    db.close()
    a = create_assignment(client, itok, subject["id"], "Quiz 1")
    assert client.get(f"/submissions/{legacy_id}", headers=H(itok)).json()["assignment_id"] == a["id"]
    assert client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]["id"] == legacy_id


# --------------------------------------------------------------------------
# Student view + submission window
# --------------------------------------------------------------------------


def test_student_sees_open_and_past_assignments_but_not_upcoming_ones():
    subject, itok, stok = setup_subject_with_users(client)
    create_assignment(client, itok, subject["id"], "Open one", description="Implement a Python calculator.")
    create_assignment(client, itok, subject["id"], "Future", opens_in=timedelta(days=1), closes_in=timedelta(days=2))
    create_assignment(client, itok, subject["id"], "Past", opens_in=timedelta(days=-5), closes_in=timedelta(days=-1))

    listed = client.get("/assignments", headers=H(stok)).json()
    assert {a["name"]: a["status"] for a in listed} == {"Open one": "open", "Past": "closed"}
    open_one = next(a for a in listed if a["name"] == "Open one")
    assert open_one["description"] == "Implement a Python calculator."
    # Explicit UTC offset ("Z"), so browsers convert it to local time correctly.
    assert _parse_utc(open_one["deadline"]).utcoffset() == timedelta(0)
    assert open_one["my_submission"] is None
    # No rubric or grading internals in the student view.
    assert set(open_one) == {"id", "subject_id", "subject_name", "name", "description", "available_from",
                             "deadline", "status", "submission_types", "code_languages",
                                 "student_similarity_check", "student_ai_check", "marks_release_at",
                                 "sample_tests", "hidden_test_count", "assignment_type", "my_submission"}


def test_backend_enforces_the_submission_window():
    subject, itok, stok = setup_subject_with_users(client)
    future = create_assignment(client, itok, subject["id"], "Future", opens_in=timedelta(days=1),
                               closes_in=timedelta(days=2))
    past = create_assignment(client, itok, subject["id"], "Past", opens_in=timedelta(days=-5),
                             closes_in=timedelta(minutes=-1))
    open_ = create_assignment(client, itok, subject["id"], "Open")

    r = _submit(stok, future)
    assert r.status_code == 403 and "not open" in r.json()["detail"]
    r = _submit(stok, past)
    assert r.status_code == 403 and "deadline" in r.json()["detail"]
    # Naming the assignment instead of its id doesn't get around it.
    r = client.post("/submissions", data={"subject_id": subject["id"], "assignment_name": "past"},
                    files=_code(), headers=H(stok))
    assert r.status_code == 403
    assert client.get(f"/assignments/{future['id']}", headers=H(stok)).status_code == 404
    assert _submit(stok, open_).status_code == 200


def test_submission_rules():
    subject, itok, stok = setup_subject_with_users(client)
    a = create_assignment(client, itok, subject["id"], "A")
    assert _submit(stok, a).status_code == 200
    r = _submit(stok, a)
    assert r.status_code == 409 and "Edit submission" in r.json()["detail"]
    r = client.post("/submissions", data={"subject_id": subject["id"], "assignment_id": a["id"]}, headers=H(new_student(client, subject["id"])))
    assert r.status_code == 400  # no files
    r = client.post("/submissions", data={"subject_id": subject["id"], "assignment_name": "No such thing"},
                    files=_code(), headers=H(stok))
    assert r.status_code == 404
    r = client.post("/submissions", data={"subject_id": subject["id"]}, files=_code(), headers=H(stok))
    assert r.status_code == 400
    other_subject, other_itok, _ = setup_subject_with_users(client)
    other = create_assignment(client, other_itok, other_subject["id"])
    r = client.post("/submissions", data={"subject_id": subject["id"], "assignment_id": other["id"]},
                    files=_code(), headers=H(stok))
    assert r.status_code == 404


def test_student_can_edit_and_delete_own_submission_while_open():
    subject, itok, stok = setup_subject_with_users(client)
    a = create_assignment(client, itok, subject["id"], "Editable")
    sub = _submit(stok, a, _code("print('v1')\n")).json()
    old_code_dir = BASE_DIR / sub["code_path"]

    r = client.put(f"/submissions/{sub['id']}", files=_code("print('v2')\n"), headers=H(stok))
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["id"] == sub["id"] and edited["code_path"] != sub["code_path"]
    assert (BASE_DIR / edited["code_path"] / "solution.py").read_text() == "print('v2')\n"
    assert not old_code_dir.exists()  # replaced files are removed
    assert client.put(f"/submissions/{sub['id']}", headers=H(stok)).status_code == 400  # nothing to replace

    r = client.delete(f"/submissions/{sub['id']}", headers=H(stok))
    assert r.status_code == 200
    assert not (BASE_DIR / edited["code_path"]).exists()
    assert client.get("/assignments", headers=H(stok)).json()[0]["my_submission"] is None
    assert _submit(stok, a).status_code == 200  # can submit again while open


def test_no_edits_or_deletes_after_the_deadline_or_after_grading():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], "Closing", rubric_id=rubric["id"])
    sub = _submit(stok, a).json()
    client.put(f"/assignments/{a['id']}", json={"available_from": _iso(timedelta(days=-3)),
                                                "deadline": _iso(timedelta(minutes=-1))}, headers=H(itok))
    assert client.put(f"/submissions/{sub['id']}", files=_code(), headers=H(stok)).status_code == 403
    assert client.delete(f"/submissions/{sub['id']}", headers=H(stok)).status_code == 403
    mine = client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]
    assert mine["can_edit"] is False

    b = create_assignment(client, itok, subject["id"], "Graded", rubric_id=rubric["id"])
    sub_b = _submit(stok, b).json()
    _grade(itok, sub_b["id"], rubric["id"], {"Code Quality": 5, "Documentation": 5, "Functionality": 5})
    assert client.put(f"/submissions/{sub_b['id']}", files=_code(), headers=H(stok)).status_code == 409
    assert client.delete(f"/submissions/{sub_b['id']}", headers=H(stok)).status_code == 409


# --------------------------------------------------------------------------
# Marks: final total only
# --------------------------------------------------------------------------


def test_student_sees_marks_and_feedback_but_never_internal_details_after_grading():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], "Assignment 1", rubric_id=rubric["id"])
    sub = _submit(stok, a).json()

    before = client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]
    assert before["status"] == "submitted" and before["final_mark"] is None
    assert before["criterion_marks"] == [] and before["feedback"] is None

    _grade(itok, sub["id"], rubric["id"], {"Code Quality": 8, "Documentation": 6, "Functionality": 20},
           comments="INTERNAL-ONLY remark", feedback="Clear code; explain the loops.")
    after = client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]
    assert after["status"] == "graded" and (after["final_mark"], after["max_mark"]) == (34, 40)
    # Their own per-criterion marks, in the rubric's order, and the feedback written for them.
    assert after["criterion_marks"] == [
        {"name": "Code Quality", "score": 8, "max_points": 10},
        {"name": "Documentation", "score": 6, "max_points": 10},
        {"name": "Functionality", "score": 20, "max_points": 20},
    ]
    assert after["feedback"] == "Clear code; explain the loops."

    # Nothing internal reaches the student anywhere.
    student_views = json.dumps([
        client.get("/assignments", headers=H(stok)).json(),
        client.get(f"/assignments/{a['id']}", headers=H(stok)).json(),
        client.get("/submissions", headers=H(stok)).json(),
        client.get(f"/submissions/{sub['id']}", headers=H(stok)).json(),
    ])
    for secret in ("INTERNAL-ONLY", "criterion_scores", "comments", "Assignment 1 Rubric", "graded_by"):
        assert secret not in student_views, secret
    assert client.get(f"/submissions/{sub['id']}/grade", headers=H(stok)).status_code == 403
    assert client.get(f"/submissions/{sub['id']}/auto-evaluate", headers=H(stok)).status_code == 403

    # The instructor keeps the full detail, and a re-grade updates the student's mark.
    detail = client.get(f"/submissions/{sub['id']}/grade", headers=H(itok)).json()
    assert detail["criterion_scores"] == {"Code Quality": 8, "Documentation": 6, "Functionality": 20}
    _grade(itok, sub["id"], rubric["id"], {"Code Quality": 9, "Documentation": 6, "Functionality": 20})
    assert client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]["final_mark"] == 35


# --------------------------------------------------------------------------
# Role-based access
# --------------------------------------------------------------------------


def test_students_cannot_change_assignments_rubrics_criteria_or_marks():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], rubric_id=rubric["id"])
    sub = _submit(stok, a).json()
    rid = rubric["id"]
    attempts = [
        ("POST", "/assignments", {"subject_id": subject["id"], "name": "x", "available_from": _iso(timedelta(0)),
                                  "deadline": _iso(timedelta(days=1))}),
        ("PUT", f"/assignments/{a['id']}", {"name": "hacked"}),
        ("DELETE", f"/assignments/{a['id']}", None),
        ("POST", "/rubrics", {"name": "x", "subject_id": subject["id"], "criteria": THREE_CRITERIA}),
        ("PUT", f"/rubrics/{rid}", {"name": "hacked"}),
        ("DELETE", f"/rubrics/{rid}", None),
        ("POST", f"/rubrics/{rid}/criteria", {"name": "x", "max_points": 1}),
        ("PUT", f"/rubrics/{rid}/criteria/1", {"max_points": 1}),
        ("DELETE", f"/rubrics/{rid}/criteria/1", None),
        ("GET", f"/rubrics/{rid}", None),
        ("POST", f"/submissions/{sub['id']}/grade", {"rubric_id": rid, "criterion_scores": {"Code Quality": 10}}),
        ("POST", f"/submissions/{sub['id']}/auto-evaluate", {"rubric_id": rid}),
    ]
    for method, url, body in attempts:
        r = client.request(method, url, json=body, headers=H(stok))
        assert r.status_code == 403, (method, url, r.status_code)
    assert client.get(f"/assignments/{a['id']}", headers=H(itok)).json()["name"] == a["name"]
    assert client.get(f"/submissions/{sub['id']}", headers=H(itok)).json()["status"] == "submitted"


def test_students_cannot_see_or_touch_other_students_work_or_marks():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], rubric_id=rubric["id"])
    other_tok = new_student(client, subject["id"])
    others = _submit(other_tok, a).json()
    _grade(itok, others["id"], rubric["id"], {"Code Quality": 1, "Documentation": 1, "Functionality": 1})

    assert client.get(f"/submissions/{others['id']}", headers=H(stok)).status_code == 403
    assert client.get(f"/submissions/{others['id']}/grade", headers=H(stok)).status_code == 403
    assert client.put(f"/submissions/{others['id']}", files=_code(), headers=H(stok)).status_code == 404
    assert client.delete(f"/submissions/{others['id']}", headers=H(stok)).status_code == 404
    assert client.get("/submissions", headers=H(stok)).json() == []
    assert client.get("/assignments", headers=H(stok)).json()[0]["my_submission"] is None


def test_subject_scoping_for_assignments():
    subject, itok, stok = setup_subject_with_users(client)
    other_subject, other_itok, _ = setup_subject_with_users(client)
    theirs = create_assignment(client, other_itok, other_subject["id"])
    assert client.get(f"/assignments/{theirs['id']}", headers=H(stok)).status_code == 404
    assert client.get(f"/assignments?subject_id={other_subject['id']}", headers=H(stok)).status_code == 403
    assert client.get(f"/assignments/{theirs['id']}", headers=H(itok)).status_code == 403
    assert client.put(f"/assignments/{theirs['id']}", json={"name": "x"}, headers=H(itok)).status_code == 403
    assert client.delete(f"/assignments/{theirs['id']}", headers=H(itok)).status_code == 403
    # A student enrolled later in the subject sees its open assignments.
    _, late_tok = create_student(client, admin_token(client), [other_subject["id"]])
    assert [x["id"] for x in client.get("/assignments", headers=H(late_tok)).json()] == [theirs["id"]]


def test_student_sees_only_enrolled_subjects_with_open_and_past_assignments():
    """A student enrolled in two subjects sees open and past assignments from
    both, never upcoming ones, never a subject they are not enrolled in."""
    admin = admin_token(client)
    maths = create_subject(client, admin)
    physics = create_subject(client, admin)
    chemistry = create_subject(client, admin)  # the student is NOT enrolled here
    _, itok = create_instructor(client, admin, [maths["id"], physics["id"], chemistry["id"]])
    _, stok = create_student(client, admin, [maths["id"], physics["id"]])

    create_assignment(client, itok, maths["id"], "Maths open")
    create_assignment(client, itok, maths["id"], "Maths past",
                      opens_in=timedelta(days=-5), closes_in=timedelta(days=-1))
    create_assignment(client, itok, maths["id"], "Maths upcoming",
                      opens_in=timedelta(days=1), closes_in=timedelta(days=2))
    create_assignment(client, itok, physics["id"], "Physics open")
    create_assignment(client, itok, chemistry["id"], "Chemistry open")

    listed = client.get("/assignments", headers=H(stok)).json()
    assert {a["name"]: a["status"] for a in listed} == {
        "Maths open": "open", "Maths past": "closed", "Physics open": "open",
    }
    assert {a["subject_id"] for a in listed} == {maths["id"], physics["id"]}

    # Filtering by an enrolled subject returns only its visible assignments.
    maths_only = client.get(f"/assignments?subject_id={maths['id']}", headers=H(stok)).json()
    assert {a["name"] for a in maths_only} == {"Maths open", "Maths past"}

    # A subject the student is not enrolled in is refused outright.
    assert client.get(f"/assignments?subject_id={chemistry['id']}", headers=H(stok)).status_code == 403


def test_final_mark_only_grade_shows_no_criterion_marks_and_feedback_stays_with_its_student():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], "Final mark only", rubric_id=rubric["id"])
    mine = _submit(stok, a).json()
    other_tok = new_student(client, subject["id"])
    _submit(other_tok, a)

    r = client.post(f"/submissions/{mine['id']}/grade", headers=H(itok), json={
        "rubric_id": rubric["id"], "total_score": 30, "feedback": "PRIVATE-FEEDBACK for student one"})
    assert r.status_code == 200, r.text

    my_view = client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]
    assert my_view["final_mark"] == 30 and my_view["criterion_marks"] == []
    assert my_view["feedback"] == "PRIVATE-FEEDBACK for student one"
    # The other student's views never contain someone else's feedback.
    other_views = json.dumps([client.get("/assignments", headers=H(other_tok)).json(),
                              client.get("/submissions", headers=H(other_tok)).json()])
    assert "PRIVATE-FEEDBACK" not in other_views


def test_marks_and_feedback_are_hidden_from_students_until_the_release_date():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], "Released later", rubric_id=rubric["id"])
    sub = _submit(stok, a).json()
    r = client.put(f"/assignments/{a['id']}", headers=H(itok), json={"marks_release_at": _iso(timedelta(days=3))})
    assert r.status_code == 200 and r.json()["marks_released"] is False and r.json()["marks_release_at"]
    _grade(itok, sub["id"], rubric["id"], {"Code Quality": 8, "Documentation": 6, "Functionality": 20},
           feedback="HELD-BACK feedback")

    # Before the date: no mark, no criterion marks, no feedback -- and not even "graded".
    mine = client.get("/assignments", headers=H(stok)).json()[0]
    assert mine["marks_release_at"] is not None
    assert mine["my_submission"]["status"] == "submitted"
    assert (mine["my_submission"]["final_mark"], mine["my_submission"]["criterion_marks"]) == (None, [])
    listed = client.get("/submissions", headers=H(stok)).json()
    detail = client.get(f"/submissions/{sub['id']}", headers=H(stok)).json()
    assert [(s["status"], s["final_mark"]) for s in listed] == [("submitted", None)]
    assert (detail["status"], detail["final_mark"]) == ("submitted", None)
    assert client.get("/submissions?status=graded", headers=H(stok)).json() == []
    assert len(client.get("/submissions?status=submitted", headers=H(stok)).json()) == 1
    hidden_views = json.dumps([client.get("/assignments", headers=H(stok)).json(), listed, detail,
                               client.get(f"/assignments/{a['id']}", headers=H(stok)).json()])
    # Look for the mark as a mark: a bare "34" also matches timestamps like 10:34:59.
    assert "HELD-BACK" not in hidden_views and '"final_mark": 34' not in hidden_views

    # The instructor still sees everything.
    assert client.get(f"/submissions/{sub['id']}/grade", headers=H(itok)).json()["total_score"] == 34
    assert client.get(f"/submissions/{sub['id']}", headers=H(itok)).json()["final_mark"] == 34

    # Releasing (an explicit null, or a date in the past) shows everything at once.
    assert client.put(f"/assignments/{a['id']}", headers=H(itok),
                      json={"marks_release_at": None}).json()["marks_released"] is True
    released = client.get("/assignments", headers=H(stok)).json()[0]
    assert released["marks_release_at"] is None
    assert released["my_submission"]["status"] == "graded" and released["my_submission"]["final_mark"] == 34
    assert released["my_submission"]["feedback"] == "HELD-BACK feedback"
    assert client.get(f"/submissions/{sub['id']}", headers=H(stok)).json()["final_mark"] == 34


def test_a_release_date_in_the_past_shows_marks_and_other_edits_keep_the_date():
    subject, itok, stok = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    a = create_assignment(client, itok, subject["id"], "Released already", rubric_id=rubric["id"])
    sub = _submit(stok, a).json()
    client.put(f"/assignments/{a['id']}", headers=H(itok), json={"marks_release_at": _iso(timedelta(days=2))})
    # Editing something else must not clear the release date.
    edited = client.put(f"/assignments/{a['id']}", headers=H(itok), json={"description": "Updated"}).json()
    assert edited["marks_released"] is False and edited["marks_release_at"]

    client.put(f"/assignments/{a['id']}", headers=H(itok), json={"marks_release_at": _iso(timedelta(minutes=-1))})
    _grade(itok, sub["id"], rubric["id"], {"Code Quality": 5, "Documentation": 5, "Functionality": 10})
    assert client.get("/assignments", headers=H(stok)).json()[0]["my_submission"]["final_mark"] == 20


# --------------------------------------------------------------------------
# Test cases for submitted code
# --------------------------------------------------------------------------

SORT_TESTS = [
    {"name": "Sorts three numbers", "input": "3\n2 3 1\n", "expected_output": "1 2 3", "visible": True, "points": 2},
    {"input": "0\n\n", "expected_output": "SECRET-EMPTY-LIST", "match": "contains", "points": 3},
]


def test_test_cases_are_saved_numbered_and_named_for_the_instructor():
    subject, itok, _ = setup_subject_with_users(client)
    r = client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": "Sorting", "available_from": _iso(timedelta(hours=-1)),
        "deadline": _iso(timedelta(days=7)), "test_cases": SORT_TESTS})
    assert r.status_code == 200, r.text
    tests = r.json()["test_cases"]
    assert [(t["id"], t["name"], t["match"], t["visible"], t["points"]) for t in tests] == [
        (1, "Sorts three numbers", "exact", True, 2), (2, "Test 2", "contains", False, 3)]
    assert tests[0]["input"] == "3\n2 3 1\n" and tests[1]["expected_output"] == "SECRET-EMPTY-LIST"

    a_id = r.json()["id"]
    # Editing something else keeps the tests; sending a list replaces them; [] removes them.
    assert len(client.put(f"/assignments/{a_id}", headers=H(itok), json={"description": "x"}).json()["test_cases"]) == 2
    replaced = client.put(f"/assignments/{a_id}", headers=H(itok), json={"test_cases": SORT_TESTS[:1]}).json()
    assert [t["id"] for t in replaced["test_cases"]] == [1]
    # A code challenge can't be left without tests.
    emptied = client.put(f"/assignments/{a_id}", headers=H(itok), json={"test_cases": []})
    assert emptied.status_code == 400 and "at least one test case" in emptied.json()["detail"]


def test_test_cases_are_validated():
    subject, itok, _ = setup_subject_with_users(client)
    base = {"subject_id": subject["id"], "available_from": _iso(timedelta(hours=-1)), "deadline": _iso(timedelta(days=7))}

    def create(name, **extra):
        return client.post("/assignments", headers=H(itok), json={**base, "name": name, **extra})

    no_code = create("Report only", submission_types=["report"], test_cases=SORT_TESTS)
    assert no_code.status_code == 400 and "accepts code" in no_code.json()["detail"]
    assert create("Bad match", test_cases=[{"expected_output": "x", "match": "regex"}]).status_code == 422
    assert create("Zero points", test_cases=[{"expected_output": "x", "points": 0}]).status_code == 422
    assert create("No expected", test_cases=[{"input": "1"}]).status_code == 422
    assert create("Too many", test_cases=[{"expected_output": "x"}] * 51).status_code == 422

    # A code challenge stays code-only.
    a = create("With tests", test_cases=SORT_TESTS).json()
    r = client.put(f"/assignments/{a['id']}", headers=H(itok), json={"submission_types": ["report"]})
    assert r.status_code == 400 and "accepts code submissions only" in r.json()["detail"]


def test_students_never_receive_test_cases():
    subject, itok, stok = setup_subject_with_users(client)
    a = client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": "Hidden tests", "available_from": _iso(timedelta(hours=-1)),
        "deadline": _iso(timedelta(days=7)), "test_cases": SORT_TESTS}).json()
    student_views = json.dumps([client.get("/assignments", headers=H(stok)).json(),
                                client.get(f"/assignments/{a['id']}", headers=H(stok)).json()])
    assert "SECRET-EMPTY-LIST" not in student_views and "test_cases" not in student_views


def test_students_see_the_visible_tests_only_after_submitting_and_never_the_hidden_ones():
    subject, itok, stok = setup_subject_with_users(client)
    tests = SORT_TESTS + [{"input": "HIDDEN-INPUT", "expected_output": "HIDDEN-EXPECTED", "points": 4}]
    a = client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": "Samples", "available_from": _iso(timedelta(hours=-1)),
        "deadline": _iso(timedelta(days=7)), "test_cases": tests}).json()
    views = lambda: json.dumps([client.get("/assignments", headers=H(stok)).json(),  # noqa: E731
                                client.get(f"/assignments/{a['id']}", headers=H(stok)).json()])

    # Before submitting: no sample input or expected output reaches the student at all.
    before = client.get("/assignments", headers=H(stok)).json()[0]
    assert before["sample_tests"] == [] and before["hidden_test_count"] == 2
    assert before["my_submission"] is None
    for visible in ("Sorts three numbers", "2 3 1", "1 2 3"):
        assert visible not in views(), visible

    # After submitting: the visible test appears as a sample.
    assert _submit(stok, a).status_code == 200
    mine = client.get("/assignments", headers=H(stok)).json()[0]
    assert mine["sample_tests"] == [{"name": "Sorts three numbers", "input": "3\n2 3 1\n",
                                     "expected_output": "1 2 3", "match": "exact", "points": 2}]
    assert mine["hidden_test_count"] == 2
    assert client.get(f"/assignments/{a['id']}", headers=H(stok)).json()["sample_tests"] == mine["sample_tests"]

    # Hidden tests: nothing but the count, before and after.
    for secret in ("SECRET-EMPTY-LIST", "HIDDEN-INPUT", "HIDDEN-EXPECTED"):
        assert secret not in views(), secret

    # Deleting the submission takes the samples away again.
    assert client.delete(f"/submissions/{mine['my_submission']['id']}", headers=H(stok)).status_code == 200
    assert client.get("/assignments", headers=H(stok)).json()[0]["sample_tests"] == []

    # An assignment without tests shows none.
    client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": "Plain", "available_from": _iso(timedelta(hours=-1)),
        "deadline": _iso(timedelta(days=7))})
    plain = next(x for x in client.get("/assignments", headers=H(stok)).json() if x["name"] == "Plain")
    assert (plain["sample_tests"], plain["hidden_test_count"]) == ([], 0)


# --------------------------------------------------------------------------
# Assignment type: submission or code challenge
# --------------------------------------------------------------------------


def _new_assignment(itok, subject, name, **extra):
    return client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": name, "available_from": _iso(timedelta(hours=-1)),
        "deadline": _iso(timedelta(days=7)), **extra})


def test_a_code_challenge_accepts_code_only_and_needs_test_cases():
    subject, itok, _ = setup_subject_with_users(client)
    r = _new_assignment(itok, subject, "Challenge", assignment_type="code_challenge", test_cases=SORT_TESTS)
    assert r.status_code == 200, r.text
    assert (r.json()["assignment_type"], r.json()["submission_types"]) == ("code_challenge", ["code"])

    no_tests = _new_assignment(itok, subject, "Empty challenge", assignment_type="code_challenge")
    assert no_tests.status_code == 400 and "at least one test case" in no_tests.json()["detail"]
    more = _new_assignment(itok, subject, "Too wide", assignment_type="code_challenge", test_cases=SORT_TESTS,
                           submission_types=["code", "report"])
    assert more.status_code == 400 and "accepts code submissions only" in more.json()["detail"]
    # Sending ["code"] explicitly is fine.
    ok = _new_assignment(itok, subject, "Code listed", assignment_type="code_challenge", test_cases=SORT_TESTS,
                         submission_types=["code"])
    assert ok.status_code == 200 and ok.json()["submission_types"] == ["code"]


def test_a_submission_assignment_keeps_its_file_types_and_takes_no_test_cases():
    subject, itok, _ = setup_subject_with_users(client)
    plain = _new_assignment(itok, subject, "Plain", assignment_type="submission",
                            submission_types=["code", "report"])
    assert (plain.json()["assignment_type"], plain.json()["submission_types"]) == ("submission", ["code", "report"])
    assert _new_assignment(itok, subject, "Default").json()["assignment_type"] == "submission"  # no type, no tests

    with_tests = _new_assignment(itok, subject, "Wrong type", assignment_type="submission", test_cases=SORT_TESTS)
    assert with_tests.status_code == 400 and "belong to code challenges" in with_tests.json()["detail"]
    late = client.put(f"/assignments/{plain.json()['id']}", headers=H(itok), json={"test_cases": SORT_TESTS})
    assert late.status_code == 400 and "belong to code challenges" in late.json()["detail"]
    # The type itself can't be changed afterwards.
    changed = client.put(f"/assignments/{plain.json()['id']}", headers=H(itok), json={"assignment_type": "code_challenge"})
    assert changed.status_code == 200 and changed.json()["assignment_type"] == "submission"


def test_test_cases_without_a_type_make_a_code_challenge():
    subject, itok, _ = setup_subject_with_users(client)
    r = _new_assignment(itok, subject, "Inferred", test_cases=SORT_TESTS)
    assert r.status_code == 200 and r.json()["assignment_type"] == "code_challenge"
    assert r.json()["submission_types"] == ["code"]


def test_a_code_challenge_has_no_rubric_but_can_drop_an_old_one():
    subject, itok, _ = setup_subject_with_users(client)
    rubric = _rubric(itok, subject["id"])
    refused = _new_assignment(itok, subject, "Rubric on challenge", assignment_type="code_challenge",
                              test_cases=SORT_TESTS, rubric_id=rubric["id"])
    assert refused.status_code == 400 and "not by a rubric" in refused.json()["detail"]

    ok = _new_assignment(itok, subject, "Tests only", assignment_type="code_challenge", test_cases=SORT_TESTS)
    assert ok.status_code == 200 and ok.json()["rubric_id"] is None
    url = f"/assignments/{ok.json()['id']}"
    attach = client.put(url, headers=H(itok), json={"rubric_id": rubric["id"]})
    assert attach.status_code == 400 and "not by a rubric" in attach.json()["detail"]
    # Sending no rubric (null) is fine: that is what the form sends for a challenge.
    assert client.put(url, headers=H(itok), json={"rubric_id": None}).status_code == 200

    # A plain submission assignment still takes a rubric.
    plain = _new_assignment(itok, subject, "Plain with rubric", rubric_id=rubric["id"])
    assert plain.status_code == 200 and plain.json()["rubric_id"] == rubric["id"]


def test_students_are_told_which_assignments_are_code_challenges():
    subject, itok, stok = setup_subject_with_users(client)
    _new_assignment(itok, subject, "Challenge for the editor", test_cases=SORT_TESTS)
    _new_assignment(itok, subject, "Plain upload")
    kinds = {a["name"]: a["assignment_type"] for a in client.get("/assignments", headers=H(stok)).json()}
    assert kinds == {"Challenge for the editor": "code_challenge", "Plain upload": "submission"}
