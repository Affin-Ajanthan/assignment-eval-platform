"""The comparisons both the instructor's checks and the student self-checks run
(app/similarity_runs.py): the assignment's settings are found by the
submissions' own assignment_id, and the report check is one shared function,
so the instructor and a student always compare the same reports the same way."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal
from app.main import app as fastapi_app
from app.models import Submission
from app.similarity_runs import find_assignment, report_similarity_run
from tests.auth_helpers import auth_headers, create_assignment, new_student, setup_subject_with_users, submit
from tests.helpers import make_pdf

client = TestClient(fastapi_app)

TEMPLATE = ("Assignment brief: design a library lending system that records books, members and loans, "
            "calculates fines for late returns and saves everything to CSV files between runs. Explain your "
            "design, describe how you tested it and reflect on what you would change next time.")
OWN = {
    "a": ("I modelled every loan as a small class holding the book, the member and the due date, and all "
          "changes go through one method so the fine is always recalculated after a return or renewal. "
          "Testing showed that dates typed with slashes were rejected, so the parser now accepts both forms."),
    "b": ("My program keeps books and members in two dictionaries that are written to separate CSV files "
          "when the menu exits. Borrowing checks the member limit first and the availability second, and the "
          "overdue report is sorted by days late so the librarian sees the worst cases at the top."),
    "c": ("The design uses a single SQLite-like table in memory, rebuilt from the CSV file on start. Each "
          "command in the menu is a function that validates its input before touching the data, and I wrote "
          "unit tests for the fine calculation including leap years and books returned on the due date."),
}


def _pdf(tmp_path, name, text):
    return (f"{name}.pdf", io.BytesIO(make_pdf(tmp_path / f"{name}.pdf", [text]).read_bytes()), "application/pdf")


def _class_with_template(tmp_path, name):
    """Three reports that share only the assignment brief, which is uploaded as the template."""
    subject, tok, _ = setup_subject_with_users(client)
    assignment = create_assignment(client, tok, subject["id"], name)
    r = client.post(f"/assignments/{assignment['id']}/report-template", headers=auth_headers(tok),
                    files={"file": _pdf(tmp_path, "template", TEMPLATE)})
    assert r.status_code == 200, r.text
    ids = {}
    for who, text in OWN.items():
        student = new_student(client, subject["id"])
        r = submit(client, subject["id"], name, {"report": _pdf(tmp_path, who, TEMPLATE + " " + text)}, student)
        assert r.status_code == 200, r.text
        ids[who] = (student, r.json()["id"])
    return subject, tok, assignment, ids


def test_the_assignment_is_found_by_the_submissions_id_and_by_name_only_for_old_submissions(tmp_path):
    subject, tok, assignment, ids = _class_with_template(tmp_path, "Find By Id")
    db = SessionLocal()
    try:
        subs = db.query(Submission).filter(Submission.id.in_([sid for _, sid in ids.values()])).all()
        assert all(s.assignment_id == assignment["id"] for s in subs)
        assert find_assignment(db, subject["id"], "Find By Id", subs).id == assignment["id"]
        # a name that no longer matches doesn't matter when the submissions carry the id
        assert find_assignment(db, subject["id"], "Some Old Name", subs).id == assignment["id"]
        # submissions from before assignments existed have no id: found by (normalized) name
        legacy = [SimpleNamespace(assignment_id=None)]
        assert find_assignment(db, subject["id"], "  find by ID ", legacy).id == assignment["id"]
        assert find_assignment(db, subject["id"], "Nothing Like It", legacy) is None
        # an id from another subject is never used
        assert find_assignment(db, subject["id"] + 10_000, "Find By Id", subs) is None
    finally:
        db.close()


def test_instructor_and_student_compare_the_same_reports_the_same_way(tmp_path):
    subject, tok, assignment, ids = _class_with_template(tmp_path, "Same Report Run")
    instructor = client.post(f"/subjects/{subject['id']}/assignments/Same Report Run/check-report-similarity",
                             headers=auth_headers(tok))
    assert instructor.status_code == 200, instructor.text
    body = instructor.json()
    assert body["compared"] == 3 and body["template_filename"] == "template.pdf"
    assert all(n > 0 for n in body["template_words_removed"].values())  # the brief was cut out of every report

    db = SessionLocal()
    try:
        subs = db.query(Submission).filter(Submission.assignment_id == assignment["id"]).all()
        run = report_similarity_run(db, subject["id"], "Same Report Run", subs)
    finally:
        db.close()
    shared = {(p.submission_a, p.submission_b): (p.jaccard, p.containment) for p in run.comparison.pairs}
    shown = {(str(p["submission_a_id"]), str(p["submission_b_id"])): (p["jaccard"], p["containment"])
             for p in body["pairs"]}
    assert shown == shared                                                 # the instructor shows the shared run

    # the student's self-check: same reports, the template cut out too, so the shared brief is no match
    student, sid = ids["a"]
    assert client.post(f"/submissions/{sid}/self-checks", json={"kind": "report_similarity"},
                       headers=auth_headers(student)).status_code == 202
    latest = client.get(f"/submissions/{sid}/self-checks", headers=auth_headers(student)).json()["latest"]
    result = latest["report_similarity"]["result"]
    assert result["compared"] == 2 and result["band"] == "low", result


def test_a_student_whose_own_report_cannot_be_read_is_told_why(tmp_path):
    subject, tok, assignment, ids = _class_with_template(tmp_path, "Unreadable Own")
    student = new_student(client, subject["id"])
    r = submit(client, subject["id"], "Unreadable Own",
               {"report": _pdf(tmp_path, "short", "Too short to compare.")}, student)
    sid = r.json()["id"]
    client.post(f"/submissions/{sid}/self-checks", json={"kind": "report_similarity"}, headers=auth_headers(student))
    result = client.get(f"/submissions/{sid}/self-checks", headers=auth_headers(student)).json()["latest"][
        "report_similarity"]["result"]
    assert result["compared"] == 0 and "Too little text" in result["note"]
