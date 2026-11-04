"""Admin edit and delete of instructor and student accounts:
PUT/DELETE /admin/instructors/{id} and /admin/students/{id}, and the edit of a subject: PUT /admin/subjects/{id}."""

import io
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal
from app.main import BASE_DIR
from app.main import app as fastapi_app
from app.models import AutoEvaluation, Enrollment, Grade, InstructorAssignment, Submission, User
from tests.auth_helpers import (
    admin_token, auth_headers, create_instructor, create_student, create_subject, login, setup_subject_with_users,
    submit,
)

client = TestClient(fastapi_app)
H = auth_headers
CODE = {"code": ("solution.py", io.BytesIO(b"def add(a, b):\n    return a + b\n"), "text/x-python")}


def _login(email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


# ---- edit ----------------------------------------------------------------------

def test_admin_edits_name_email_password_and_subjects():
    admin = admin_token(client)
    s1, s2 = create_subject(client, admin), create_subject(client, admin)
    student, student_tok = create_student(client, admin, [s1["id"]], password="old-pass")

    r = client.put(f"/admin/students/{student['id']}", headers=H(admin), json={
        "full_name": "  Renamed Student ", "email": "renamed.student@example.com",
        "password": "new-pass", "subject_ids": [s2["id"]],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Renamed Student" and body["email"] == "renamed.student@example.com"
    assert [s["id"] for s in body["subjects"]] == [s2["id"]]

    # The new password works, the old one doesn't, and old sessions are logged out.
    assert _login("renamed.student@example.com", "new-pass").status_code == 200
    assert _login("renamed.student@example.com", "old-pass").status_code == 401
    assert _login(student["email"], "old-pass").status_code == 401
    assert client.get("/auth/me", headers=H(student_tok)).status_code == 401


def test_blank_password_and_missing_fields_are_kept():
    admin = admin_token(client)
    subject = create_subject(client, admin)
    inst, inst_tok = create_instructor(client, admin, [subject["id"]], password="keep-me")
    r = client.put(f"/admin/instructors/{inst['id']}", headers=H(admin),
                   json={"full_name": "Dr. Changed", "password": ""})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == inst["email"] and [s["id"] for s in r.json()["subjects"]] == [subject["id"]]
    assert _login(inst["email"], "keep-me").status_code == 200
    assert client.get("/auth/me", headers=H(inst_tok)).status_code == 200  # no password change: still logged in


def test_edit_validation():
    admin = admin_token(client)
    a, _ = create_student(client, admin, [])
    b, _ = create_student(client, admin, [])
    url = f"/admin/students/{a['id']}"
    assert client.put(url, headers=H(admin), json={"email": b["email"].upper()}).status_code == 400  # taken
    assert client.put(url, headers=H(admin), json={"email": "not-an-email"}).status_code == 400
    assert client.put(url, headers=H(admin), json={"full_name": "   "}).status_code == 400
    assert client.put(url, headers=H(admin), json={"password": "abc"}).status_code == 400
    assert client.put(url, headers=H(admin), json={"subject_ids": [999999]}).status_code == 400
    assert client.put(url, headers=H(admin), json={"email": a["email"]}).status_code == 200  # own email is fine


def test_admin_edits_a_subjects_name_and_code():
    admin = admin_token(client)
    a, b = create_subject(client, admin), create_subject(client, admin)
    _, inst_tok = create_instructor(client, admin, [a["id"]])
    url = f"/admin/subjects/{a['id']}"

    r = client.put(url, headers=H(admin), json={"name": "  Renamed   Subject ", "code": " NEW-1 "})
    assert r.status_code == 200, r.text
    assert (r.json()["id"], r.json()["name"], r.json()["code"]) == (a["id"], "Renamed Subject", "NEW-1")
    assert client.put(url, headers=H(admin), json={"name": "Only the name"}).json()["code"] == "NEW-1"  # kept
    # The people in the subject see the change, since they refer to it by id.
    mine = client.get("/auth/me", headers=H(inst_tok)).json()["subjects"]
    assert [(s["id"], s["name"], s["code"]) for s in mine] == [(a["id"], "Only the name", "NEW-1")]

    assert client.put(url, headers=H(admin), json={"code": b["code"]}).status_code == 400  # taken by another subject
    assert client.put(url, headers=H(admin), json={"name": "   "}).status_code == 400
    assert client.put(url, headers=H(admin), json={"code": " "}).status_code == 400
    assert client.put(url, headers=H(admin), json={"code": "NEW-1"}).status_code == 200  # its own code is fine
    assert client.put("/admin/subjects/999999", headers=H(admin), json={"name": "X"}).status_code == 404
    assert client.put(url, headers=H(inst_tok), json={"name": "Not allowed"}).status_code == 403


def _new_student(admin, **extra):
    body = {"email": f"s{uuid.uuid4().hex[:10]}@example.com", "full_name": "Ada Student", "password": "pass1234",
            "subject_ids": [], **extra}
    return client.post("/admin/students", headers=H(admin), json=body)


def test_a_student_has_a_batch_and_a_register_number():
    admin = admin_token(client)
    reg = f"TST/01/{uuid.uuid4().hex[:8].upper()}"

    r = _new_student(admin, batch="  01 ", register_number=f" {reg} ")
    assert r.status_code == 200, r.text
    student = r.json()
    assert (student["batch"], student["register_number"]) == ("01", reg)  # trimmed
    listed = next(s for s in client.get("/admin/students", headers=H(admin)).json() if s["id"] == student["id"])
    assert (listed["batch"], listed["register_number"]) == ("01", reg)
    me = client.get("/auth/me", headers=H(login(client, student["email"], "pass1234")))
    assert (me.json()["batch"], me.json()["register_number"]) == ("01", reg)

    # Both are optional: a student without them has empty strings, and two such students don't clash.
    plain, other = _new_student(admin).json(), _new_student(admin).json()
    assert (plain["batch"], plain["register_number"]) == ("", "") and other["register_number"] == ""
    assert _new_student(admin, batch="02").json()["register_number"] == ""  # a batch alone is fine


def test_a_register_number_is_tst_then_the_batch_then_the_students_own_number():
    admin = admin_token(client)
    last = uuid.uuid4().hex[:8].upper()

    def refused(**extra):
        r = _new_student(admin, **extra)
        assert r.status_code == 400, r.text
        return r.json()["detail"]

    assert "batch first" in refused(register_number=f"TST/01/{last}")                         # no batch to hold
    assert "must look like TST/01/001" in refused(batch="01", register_number=f"TST/02/{last}")  # another batch
    assert "must look like" in refused(batch="01", register_number=f"XYZ/01/{last}")           # not TST
    assert "must look like" in refused(batch="01", register_number="TST/01/")                  # no own number
    assert "must look like" in refused(batch="01", register_number=f"TST/01/{last}/9")         # a fourth part
    assert "must look like" in refused(batch="01", register_number="TST/01/12 3")              # a space
    assert "can't contain '/'" in refused(batch="01/02")                                       # it is a separator
    assert _new_student(admin, batch="01", register_number=f"TST/01/{last}").status_code == 200


def test_a_register_number_belongs_to_one_student_only():
    admin = admin_token(client)
    last = uuid.uuid4().hex[:8].upper()
    reg = f"TST/01/{last}"
    first = _new_student(admin, batch="01", register_number=reg).json()
    second = _new_student(admin, batch="01").json()

    taken = _new_student(admin, batch="01", register_number=f"TST/01/{last.lower()}")  # the case doesn't matter
    assert taken.status_code == 400 and "already belongs to another student" in taken.json()["detail"]
    url = f"/admin/students/{second['id']}"
    assert client.put(url, headers=H(admin), json={"register_number": reg}).status_code == 400
    assert client.put(f"/admin/students/{first['id']}", headers=H(admin),
                      json={"register_number": reg}).status_code == 200  # a student may keep their own

    # The same own number in another batch is another register number. Changing the batch means changing both.
    done = client.put(url, headers=H(admin), json={"batch": " 02 ", "register_number": f"TST/02/{last}"}).json()
    assert (done["batch"], done["register_number"]) == ("02", f"TST/02/{last}")
    kept = client.put(url, headers=H(admin), json={"full_name": "Renamed"}).json()  # fields left out are kept
    assert (kept["batch"], kept["register_number"]) == ("02", f"TST/02/{last}")
    only_batch = client.put(url, headers=H(admin), json={"batch": "03"})  # the number would still say 02
    assert only_batch.status_code == 400 and "must look like" in only_batch.json()["detail"]
    cleared = client.put(url, headers=H(admin), json={"batch": "", "register_number": ""}).json()
    assert (cleared["batch"], cleared["register_number"]) == ("", "")

    freed = client.put(f"/admin/students/{first['id']}", headers=H(admin), json={"register_number": ""}).json()
    assert freed["register_number"] == ""
    assert client.put(url, headers=H(admin),
                      json={"batch": "01", "register_number": reg}).status_code == 200  # a freed number is reusable


def test_an_instructor_has_no_batch_or_register_number():
    admin = admin_token(client)
    inst, _ = create_instructor(client, admin, [])
    r = client.put(f"/admin/instructors/{inst['id']}", headers=H(admin),
                   json={"batch": "2022", "register_number": "R1"})
    assert r.status_code == 200 and (r.json()["batch"], r.json()["register_number"]) == ("", "")


def test_role_must_match_the_path_and_only_admins_may_edit_or_delete():
    subject, inst_tok, student_tok = setup_subject_with_users(client)
    admin = admin_token(client)
    student, _ = create_student(client, admin, [subject["id"]])
    assert client.put(f"/admin/instructors/{student['id']}", headers=H(admin), json={}).status_code == 404
    assert client.delete(f"/admin/instructors/{student['id']}", headers=H(admin)).status_code == 404
    assert client.delete("/admin/students/999999", headers=H(admin)).status_code == 404
    for tok in (inst_tok, student_tok):
        assert client.put(f"/admin/students/{student['id']}", headers=H(tok), json={}).status_code == 403
        assert client.delete(f"/admin/students/{student['id']}", headers=H(tok)).status_code == 403
    with SessionLocal() as db:
        admin_user = db.query(User).filter(User.role == "admin").first()
    assert client.delete(f"/admin/students/{admin_user.id}", headers=H(admin)).status_code == 404


# ---- delete --------------------------------------------------------------------

def _graded_submission():
    """One subject, an instructor, a student with a graded submission."""
    subject, inst_tok, _ = setup_subject_with_users(client)
    admin = admin_token(client)
    student, student_tok = create_student(client, admin, [subject["id"]], password="pw1234")
    sub = submit(client, subject["id"], "Delete Me Assignment", CODE, student_tok=student_tok).json()
    rubric = client.post("/rubrics", headers=H(inst_tok), json={
        "name": "R", "subject_id": subject["id"],
        "criteria": [{"name": "Correctness", "description": "", "max_points": 10}]}).json()
    graded = client.post(f"/submissions/{sub['id']}/grade", headers=H(inst_tok),
                         json={"rubric_id": rubric["id"], "criterion_scores": {"Correctness": 7}})
    assert graded.status_code == 200, graded.text
    auto = client.post(f"/submissions/{sub['id']}/auto-evaluate", headers=H(inst_tok),
                       json={"rubric_id": rubric["id"], "use_rubric_model": False})
    assert auto.status_code == 200, auto.text
    return admin, inst_tok, student, sub


def test_deleting_a_student_removes_their_submissions_grades_and_files():
    admin, _, student, sub = _graded_submission()
    with SessionLocal() as db:
        code_dir = BASE_DIR / db.get(Submission, sub["id"]).code_path
    assert code_dir.exists()

    listed = {u["id"]: u for u in client.get("/admin/students", headers=H(admin)).json()}
    assert listed[student["id"]]["submission_count"] == 1

    r = client.delete(f"/admin/students/{student['id']}", headers=H(admin))
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "deleted", "submissions_deleted": 1}

    with SessionLocal() as db:
        assert db.get(User, student["id"]) is None
        assert db.get(Submission, sub["id"]) is None
        assert db.query(Grade).filter(Grade.submission_id == sub["id"]).count() == 0
        assert db.query(AutoEvaluation).filter(AutoEvaluation.submission_id == sub["id"]).count() == 0
        assert db.query(Enrollment).filter(Enrollment.student_id == student["id"]).count() == 0
    assert not code_dir.exists()
    assert _login(student["email"], "pw1234").status_code == 401
    assert student["id"] not in {u["id"] for u in client.get("/admin/students", headers=H(admin)).json()}


def test_deleting_an_instructor_keeps_the_grades_they_gave():
    admin, inst_tok, student, sub = _graded_submission()
    me = client.get("/auth/me", headers=H(inst_tok)).json()

    r = client.delete(f"/admin/instructors/{me['id']}", headers=H(admin))
    assert r.status_code == 200, r.text
    assert client.get("/auth/me", headers=H(inst_tok)).status_code == 401  # logged out

    with SessionLocal() as db:
        assert db.get(User, me["id"]) is None
        assert db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == me["id"]).count() == 0
        grade = db.query(Grade).filter(Grade.submission_id == sub["id"]).one()
        assert grade.graded_by_id is None and grade.graded_by == me["full_name"]
        assert db.get(Submission, sub["id"]) is not None  # the student's work is untouched
