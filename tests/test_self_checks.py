"""Student self-checks before the deadline: code similarity, report
similarity and AI content. On by default, switchable per assignment by the
instructor, enforced by the API, rate limited, and never revealing another
student's identity or work."""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import self_checks
from app.routers import self_checks as self_check_api
from app.db import SessionLocal
from app.main import app as fastapi_app
from app.models import SelfCheck, SimilarityFlag, Submission
from app.similarity.core import matched_line_ranges
from tests.auth_helpers import auth_headers, create_assignment, new_student, setup_subject_with_users, submit
from tests.helpers import make_docx, make_pdf

client = TestClient(fastapi_app)

COPIED_CODE = b'''
def average(marks):
    total = 0
    for m in marks:
        total = total + m
    return total / len(marks)


def grade(avg):
    if avg >= 75:
        return "A"
    if avg >= 50:
        return "B"
    return "F"


print("Student average:", average([70, 80, 90]))
'''

OWN_CODE = b'''
class Library:
    def __init__(self):
        self.books = {}

    def lend(self, isbn, member):
        book = self.books.get(isbn)
        if book is None:
            raise KeyError("no such book")
        book["on_loan_to"] = member
'''

REPORT = ("This report describes a student performance system that stores the marks of each student, "
          "calculates the average and the grade, sorts the students by average and saves every record "
          "to a text file so that nothing is lost when the program closes. The design uses one class per "
          "student and a list that keeps all of them in memory while the menu runs. Testing covered "
          "valid marks, invalid marks above one hundred, empty files and sorting ties between students.")
OTHER_REPORT = ("A weather station project collects rainfall, humidity and temperature readings every hour "
                "from three sensors on the roof of the science building. The readings are cleaned, averaged "
                "per day and drawn on a dashboard with a line chart per sensor. A small alarm warns the "
                "caretaker when the humidity stays above ninety percent for more than six hours in a row, "
                "and a weekly summary is emailed to the geography department every Monday morning.")


def _pdf(tmp_path, name, text):
    return (f"{name}.pdf", io.BytesIO(make_pdf(tmp_path / f"{name}.pdf", [text]).read_bytes()), "application/pdf")


def _code(name, data):
    return (name, io.BytesIO(data), "text/x-python")


def _setup(tmp_path, name="Self Check Assignment"):
    """Subject with 3 students: A and B share the same code and report, C is different."""
    subject, instructor_tok, _ = setup_subject_with_users(client)
    assignment = create_assignment(client, instructor_tok, subject["id"], name)
    students = {}
    for who, code, report in (("a", COPIED_CODE, REPORT), ("b", COPIED_CODE, REPORT), ("c", OWN_CODE, OTHER_REPORT)):
        tok = new_student(client, subject["id"])
        r = submit(client, subject["id"], name, {"code": _code("solution.py", code),
                                                 "report": _pdf(tmp_path, f"report_{who}", report)}, tok)
        assert r.status_code == 200, r.text
        students[who] = (tok, r.json()["id"])
    return subject, instructor_tok, assignment, students


def _run(tok, sid, kind):
    return client.post(f"/submissions/{sid}/self-checks", json={"kind": kind}, headers=auth_headers(tok))


def _latest(tok, sid, kind):
    r = client.get(f"/submissions/{sid}/self-checks", headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    return r.json()["latest"][kind]


def test_both_self_checks_are_on_by_default(tmp_path):
    subject, tok, assignment, students = _setup(tmp_path)
    assert assignment["student_similarity_check"] is True and assignment["student_ai_check"] is True
    student_tok, _ = students["a"]
    seen = client.get(f"/assignments/{assignment['id']}", headers=auth_headers(student_tok)).json()
    assert seen["student_similarity_check"] is True and seen["student_ai_check"] is True


def test_code_similarity_shows_a_band_and_own_lines_but_nothing_about_the_other_student(tmp_path):
    subject, _, _, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    started = _run(tok_a, sid_a, "code_similarity")
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "running"

    check = _latest(tok_a, sid_a, "code_similarity")
    assert check["status"] == "done"
    result = check["result"]
    assert result["band"] == "high"
    assert result["compared"] == 2 and result["similar_submissions"] == 1
    assert result["highlights"], "the student's own matching lines are shown"
    assert all(h["file"] == "solution.py" for h in result["highlights"])
    assert any("def average(marks):" in h["text"] for h in result["highlights"])

    # Nothing identifies or exposes the other submissions.
    raw = json.dumps(check)
    for forbidden in ("pairs", "other_submission_id", "jaccard", "containment", "semantic_similarity"):
        assert forbidden not in raw
    sid_b = students["b"][1]
    db = SessionLocal()
    try:
        other = db.get(Submission, sid_b)
        assert other.student_email not in raw and other.student_name not in raw
    finally:
        db.close()


def test_unrelated_code_is_low(tmp_path):
    _, _, _, students = _setup(tmp_path)
    tok_c, sid_c = students["c"]
    assert _run(tok_c, sid_c, "code_similarity").status_code == 202
    result = _latest(tok_c, sid_c, "code_similarity")["result"]
    assert result["band"] == "low" and result["similar_submissions"] == 0 and result["highlights"] == []


def test_self_check_never_changes_the_instructors_flags(tmp_path):
    subject, _, assignment, students = _setup(tmp_path, name="Flags Untouched")
    tok_a, sid_a = students["a"]
    assert _run(tok_a, sid_a, "code_similarity").status_code == 202
    db = SessionLocal()
    try:
        flags = db.query(SimilarityFlag).filter(SimilarityFlag.subject_id == subject["id"]).count()
    finally:
        db.close()
    assert flags == 0
    # the full detail is kept internally for the instructor
    db = SessionLocal()
    try:
        stored = db.query(SelfCheck).filter(SelfCheck.submission_id == sid_a).one()
        assert stored.result["pairs"] and "jaccard" in stored.result["pairs"][0]
    finally:
        db.close()


def test_report_similarity_shows_own_matching_passages(tmp_path):
    _, _, _, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    assert _run(tok_a, sid_a, "report_similarity").status_code == 202
    result = _latest(tok_a, sid_a, "report_similarity")["result"]
    assert result["band"] == "high" and result["similar_submissions"] == 1
    assert any("student performance system" in p for p in result["passages"])
    assert "pairs" not in result

    tok_c, sid_c = students["c"]
    assert _run(tok_c, sid_c, "report_similarity").status_code == 202
    assert _latest(tok_c, sid_c, "report_similarity")["result"]["band"] == "low"


def test_ai_content_returns_bands_for_report_and_code(tmp_path):
    _, _, _, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    assert _run(tok_a, sid_a, "ai_content").status_code == 202
    result = _latest(tok_a, sid_a, "ai_content")["result"]
    assert set(result) == {"report", "code"}
    assert result["report"] in ("low", "moderate", "high") and result["code"] in ("low", "moderate", "high")


def test_instructor_switches_are_enforced_by_the_api_and_never_lock(tmp_path):
    _, instructor_tok, assignment, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    r = client.put(f"/assignments/{assignment['id']}", json={"student_similarity_check": False},
                   headers=auth_headers(instructor_tok))
    assert r.status_code == 200 and r.json()["student_similarity_check"] is False  # even with submissions
    for kind in ("code_similarity", "report_similarity"):
        refused = _run(tok_a, sid_a, kind)
        assert refused.status_code == 403 and "turned off similarity" in refused.json()["detail"]
    assert _run(tok_a, sid_a, "ai_content").status_code == 202  # independent switch

    client.put(f"/assignments/{assignment['id']}", json={"student_ai_check": False, "student_similarity_check": True},
               headers=auth_headers(instructor_tok))
    assert _run(tok_a, sid_a, "ai_content").status_code == 403
    assert _run(tok_a, sid_a, "code_similarity").status_code == 202
    status = client.get(f"/submissions/{sid_a}/self-checks", headers=auth_headers(tok_a)).json()
    assert status["similarity_enabled"] is True and status["ai_enabled"] is False


def test_closed_after_the_deadline_and_after_grading(tmp_path):
    _, instructor_tok, assignment, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    now = datetime.now(timezone.utc)
    r = client.put(f"/assignments/{assignment['id']}",
                   json={"available_from": (now - timedelta(days=2)).isoformat(),
                         "deadline": (now - timedelta(minutes=5)).isoformat()},
                   headers=auth_headers(instructor_tok))
    assert r.status_code == 200, r.text
    closed = _run(tok_a, sid_a, "code_similarity")
    assert closed.status_code == 403 and "deadline" in closed.json()["detail"]
    assert client.get(f"/submissions/{sid_a}/self-checks", headers=auth_headers(tok_a)).json()["can_run"] is False

    client.put(f"/assignments/{assignment['id']}", json={"deadline": (now + timedelta(days=1)).isoformat()},
               headers=auth_headers(instructor_tok))
    db = SessionLocal()
    try:
        db.get(Submission, sid_a).status = "graded"
        db.commit()
    finally:
        db.close()
    graded = _run(tok_a, sid_a, "code_similarity")
    assert graded.status_code == 403 and "graded" in graded.json()["detail"]


def test_five_checks_per_hour_per_kind(tmp_path):
    _, _, _, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    for _ in range(self_checks.LIMIT_PER_HOUR):
        assert _run(tok_a, sid_a, "code_similarity").status_code == 202
    limited = _run(tok_a, sid_a, "code_similarity")
    assert limited.status_code == 429 and "minute" in limited.json()["detail"]
    status = client.get(f"/submissions/{sid_a}/self-checks", headers=auth_headers(tok_a)).json()
    assert status["remaining"] == {"code_similarity": 0, "report_similarity": 5, "ai_content": 5}
    assert _run(tok_a, sid_a, "report_similarity").status_code == 202  # separate limit


def test_rejected_requests_do_not_count_but_failed_jobs_do(tmp_path, monkeypatch):
    _, instructor_tok, assignment, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    client.put(f"/assignments/{assignment['id']}", json={"student_ai_check": False}, headers=auth_headers(instructor_tok))
    assert _run(tok_a, sid_a, "ai_content").status_code == 403  # refused before a job: not counted
    client.put(f"/assignments/{assignment['id']}", json={"student_ai_check": True}, headers=auth_headers(instructor_tok))

    def boom(submission):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(self_check_api, "_self_check_ai", boom)
    assert _run(tok_a, sid_a, "ai_content").status_code == 202
    check = _latest(tok_a, sid_a, "ai_content")
    assert check["status"] == "failed"
    assert check["error"] == "The check could not be completed. Please try again later."  # no internals
    status = client.get(f"/submissions/{sid_a}/self-checks", headers=auth_headers(tok_a)).json()
    assert status["remaining"]["ai_content"] == self_checks.LIMIT_PER_HOUR - 1


def test_one_running_job_per_kind_and_stale_jobs_expire(tmp_path):
    _, _, assignment, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    db = SessionLocal()
    try:
        student_id = db.get(Submission, sid_a).student_id
        db.add(SelfCheck(submission_id=sid_a, student_id=student_id, assignment_id=assignment["id"],
                         kind="code_similarity", status="running",
                         created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.commit()
    finally:
        db.close()
    busy = _run(tok_a, sid_a, "code_similarity")
    assert busy.status_code == 409 and "still running" in busy.json()["detail"]

    db = SessionLocal()
    try:
        running = db.query(SelfCheck).filter(SelfCheck.submission_id == sid_a, SelfCheck.status == "running").one()
        running.created_at = running.created_at - timedelta(minutes=self_checks.STALE_AFTER_MINUTES + 1)
        db.commit()
    finally:
        db.close()
    assert _run(tok_a, sid_a, "code_similarity").status_code == 202


def test_students_cannot_see_each_others_checks(tmp_path):
    _, _, _, students = _setup(tmp_path)
    tok_a, _ = students["a"]
    _, sid_b = students["b"]
    assert client.get(f"/submissions/{sid_b}/self-checks", headers=auth_headers(tok_a)).status_code == 404
    assert _run(tok_a, sid_b, "code_similarity").status_code == 404


def test_instructor_sees_check_counts_per_student(tmp_path):
    _, instructor_tok, assignment, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    _run(tok_a, sid_a, "code_similarity")
    _run(tok_a, sid_a, "code_similarity")
    _run(tok_a, sid_a, "ai_content")
    rows = client.get(f"/assignments/{assignment['id']}/self-checks", headers=auth_headers(instructor_tok))
    assert rows.status_code == 200, rows.text
    by_id = {r["submission_id"]: r for r in rows.json()}
    row = by_id[sid_a]
    assert (row["code_similarity_checks"], row["report_similarity_checks"], row["ai_checks"]) == (2, 0, 1)
    assert row["latest_kind"] == "ai_content" and row["latest_status"] == "done" and row["last_check_at"]
    assert by_id[students["c"][1]]["latest_status"] is None
    assert rows.json()[0]["submission_id"] == sid_a  # most recent first
    assert client.get(f"/assignments/{assignment['id']}/self-checks",
                      headers=auth_headers(tok_a)).status_code == 403


def test_matched_line_ranges_marks_the_shared_lines_only():
    from app.similarity.core import fingerprint_source

    shared_src = "def add(a, b):\n    total = a + b\n    return total\n"
    mine = "x = 1\n" * 3 + shared_src + "y = 2\n"
    other = fingerprint_source("o", "o.py", shared_src)
    ranges = matched_line_ranges(mine, "m.py", fingerprint_source("m", "m.py", mine).hashes & other.hashes)
    assert ranges and all(4 <= start and end <= 6 for start, end in ranges)
    assert matched_line_ranges(mine, "m.py", set()) == []


def test_bands_and_student_view_helpers():
    assert self_checks.worst(["low", "high", "moderate"]) == "high" and self_checks.worst([]) == "low"
    assert self_checks.ai_band("medium") == "moderate" and self_checks.ai_band(None) is None
    full = {"band": "high", "compared": 3, "similar_submissions": 1, "highlights": [],
            "pairs": [{"other_submission_id": 9, "jaccard": 0.9}]}
    assert self_checks.for_student("code_similarity", full) == {
        "band": "high", "compared": 3, "similar_submissions": 1, "highlights": []}


def test_docx_reports_are_compared_too(tmp_path):
    subject, instructor_tok, _ = setup_subject_with_users(client)
    name = "Docx Self Check"
    create_assignment(client, instructor_tok, subject["id"], name)
    docx = make_docx(tmp_path / "mine.docx", [REPORT])
    tok = new_student(client, subject["id"])
    mine = submit(client, subject["id"], name, {"report": (
        "mine.docx", io.BytesIO(docx.read_bytes()),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, tok)
    assert mine.status_code == 200, mine.text
    other = submit(client, subject["id"], name, {"report": _pdf(tmp_path, "theirs", REPORT)})
    assert other.status_code == 200, other.text
    assert _run(tok, mine.json()["id"], "report_similarity").status_code == 202
    result = _latest(tok, mine.json()["id"], "report_similarity")["result"]
    assert result["compared"] == 1 and result["band"] == "high"


def test_each_assignment_has_its_own_hourly_limit(tmp_path):
    subject, instructor_tok, _ = setup_subject_with_users(client)
    tok = new_student(client, subject["id"])
    sids = []
    for name in ("Limit One", "Limit Two"):
        create_assignment(client, instructor_tok, subject["id"], name)
        r = submit(client, subject["id"], name, {"code": _code("solution.py", COPIED_CODE)}, tok)
        assert r.status_code == 200, r.text
        sids.append(r.json()["id"])
    for _ in range(self_checks.LIMIT_PER_HOUR):
        assert _run(tok, sids[0], "code_similarity").status_code == 202
    limited = _run(tok, sids[0], "code_similarity")
    assert limited.status_code == 429 and "'Limit One'" in limited.json()["detail"]
    # the other assignment still has all of its checks
    other = client.get(f"/submissions/{sids[1]}/self-checks", headers=auth_headers(tok)).json()
    assert other["remaining"]["code_similarity"] == self_checks.LIMIT_PER_HOUR
    assert _run(tok, sids[1], "code_similarity").status_code == 202


def _pair(j, c, flag_level=None):
    from app.similarity.core import PairResult
    return PairResult(submission_a="1", submission_b="2", jaccard=j, containment=c, shared_fingerprints=1,
                      flag_level=flag_level)


def test_moderate_is_relative_to_the_class_typical_overlap():
    # Assignment 8: honest solutions share ~65% containment with each other.
    honest = [_pair(0.35, 0.65) for _ in range(20)]
    lines = self_checks.code_moderate_lines(honest + [_pair(1.0, 1.0)])
    assert lines["median_containment"] == 0.65 and lines["containment_line"] == 0.80
    assert self_checks.code_pair_band(_pair(0.37, 0.66), lines) == "low"        # typical for the class
    assert lines["jaccard_line"] == 0.50
    assert self_checks.code_pair_band(_pair(0.55, 0.70), lines) == "moderate"   # stands out, below "high"
    assert self_checks.code_pair_band(_pair(0.96, 0.99), lines) == "high"       # instructor's flag rule
    assert self_checks.code_pair_band(_pair(0.30, 0.50, "review"), lines) == "moderate"  # semantic review


def test_floor_applies_when_the_class_shares_little():
    lines = self_checks.code_moderate_lines([_pair(0.05, 0.10) for _ in range(10)])
    assert lines["containment_line"] == self_checks.CODE_MODERATE_CONTAINMENT
    assert self_checks.code_pair_band(_pair(0.20, 0.55), lines) == "low"


def test_docx_report_without_a_saved_extraction_is_still_read(tmp_path, monkeypatch):
    """The DOCX path falls back to extracting the report now. (extract_report_text
    was used but never imported in main.py, so this raised NameError.)"""
    from app import similarity_runs

    monkeypatch.setattr(similarity_runs, "load_extraction", lambda path: None)
    monkeypatch.setattr(self_check_api, "load_extraction", lambda path: None)
    subject, instructor_tok, _ = setup_subject_with_users(client)
    name = "Docx No Sidecar"
    create_assignment(client, instructor_tok, subject["id"], name)
    tok = new_student(client, subject["id"])
    docx = make_docx(tmp_path / "mine.docx", [REPORT])
    mine = submit(client, subject["id"], name, {"report": (
        "mine.docx", io.BytesIO(docx.read_bytes()),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, tok)
    assert submit(client, subject["id"], name, {"report": _pdf(tmp_path, "theirs", REPORT)}).status_code == 200
    sid = mine.json()["id"]
    assert _run(tok, sid, "report_similarity").status_code == 202
    assert _latest(tok, sid, "report_similarity")["result"]["band"] == "high"
    assert _run(tok, sid, "ai_content").status_code == 202
    ai = _latest(tok, sid, "ai_content")
    assert ai["status"] == "done" and ai["result"]["report"] in ("low", "moderate", "high")


def test_status_reads_never_write_and_report_stale_checks_as_failed(tmp_path):
    _, _, assignment, students = _setup(tmp_path)
    tok_a, sid_a = students["a"]
    db = SessionLocal()
    try:
        student_id = db.get(Submission, sid_a).student_id
        stale = SelfCheck(submission_id=sid_a, student_id=student_id, assignment_id=assignment["id"],
                          kind="code_similarity", status="running",
                          created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                          - timedelta(minutes=self_checks.STALE_AFTER_MINUTES + 1))
        db.add(stale)
        db.commit()
        stale_id = stale.id
    finally:
        db.close()
    shown = _latest(tok_a, sid_a, "code_similarity")
    assert shown["status"] == "failed" and shown["error"]  # the student can start a new check
    db = SessionLocal()
    try:
        assert db.get(SelfCheck, stale_id).status == "running"  # the read did not write
    finally:
        db.close()
    assert _run(tok_a, sid_a, "code_similarity").status_code == 202  # starting one clears it
    db = SessionLocal()
    try:
        assert db.get(SelfCheck, stale_id).status == "failed"
    finally:
        db.close()


def test_code_most_of_the_class_shares_is_ignored_but_copies_still_match(tmp_path):
    from app.similarity_runs import code_similarity_for_dirs

    shared = "def read_mark(prompt):\n    value = input(prompt)\n    return int(value.strip())\n\n"
    unique = {
        "a": "def average(xs):\n    return sum(xs) / len(xs)\n\nprint(average([1, 2, 3]))\n",
        "c": "class Shelf:\n    def __init__(self):\n        self.books = []\n    def add(self, b):\n        self.books.append(b)\n",
        "d": "for i in range(10):\n    if i % 2:\n        print(i * i)\n    else:\n        print(-i)\n",
        "e": "import json\nwith open('x.json') as f:\n    data = json.load(f)\nprint(len(data))\n",
    }
    unique["b"] = unique["a"]  # b copied a
    dirs = {}
    for sid, body in unique.items():
        d = tmp_path / sid
        d.mkdir()
        (d / "main.py").write_text(shared + body, encoding="utf-8")
        dirs[sid] = d

    kept = code_similarity_for_dirs(dirs)
    removed = code_similarity_for_dirs(dirs, remove_common=True)
    score = lambda run, x, y: next(p.jaccard for p in run.pairs if {p.submission_a, p.submission_b} == {x, y})  # noqa: E731
    assert removed.common_removed > 0 and kept.common_removed == 0
    assert score(removed, "c", "d") < score(kept, "c", "d")  # honest pair: the shared helper no longer counts
    assert score(removed, "a", "b") == 1.0  # the copy still matches fully


def test_ignore_common_code_is_on_by_default_and_the_instructor_can_switch_it(tmp_path):
    subject, instructor_tok, assignment, students = _setup(tmp_path, name="Common Code Setting")
    assert assignment["ignore_common_code"] is True
    url = f"/subjects/{subject['id']}/assignments/{assignment['name']}/check-similarity"
    on = client.post(url, headers=auth_headers(instructor_tok)).json()

    r = client.put(f"/assignments/{assignment['id']}", json={"ignore_common_code": False},
                   headers=auth_headers(instructor_tok))
    assert r.status_code == 200 and r.json()["ignore_common_code"] is False  # even after submissions
    off = client.post(url, headers=auth_headers(instructor_tok)).json()
    assert off["common_code_removed"] == 0
    # with only 3 submissions nothing is "most of the class" (needs at least 4)
    assert on["common_code_removed"] == 0
    # the student self-check follows the same setting and still finds the copy
    tok_a, sid_a = students["a"]
    assert _run(tok_a, sid_a, "code_similarity").status_code == 202
    assert _latest(tok_a, sid_a, "code_similarity")["result"]["band"] == "high"
    # students never see the setting
    seen = client.get(f"/assignments/{assignment['id']}", headers=auth_headers(tok_a)).json()
    assert "ignore_common_code" not in seen
