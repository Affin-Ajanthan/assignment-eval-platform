"""
Tests for the similarity-check and auto-evaluate endpoints of the
single merged app -- these exercise app.similarity and app.evaluator
through the FastAPI layer end to end, under the subject-scoped auth
model (see tests/auth_helpers.py for the admin -> instructor/student
setup every test starts from).
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, ensure_assignment, setup_subject_with_users, submit

client = TestClient(fastapi_app)

BUBBLE_SORT = b'''
def bubble_sort(items):
    """Sort a list of numbers in ascending order."""
    n = len(items)
    for i in range(n):
        for j in range(0, n - i - 1):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
    return items
'''

BUBBLE_SORT_RENAMED = b'''
def sort_list(values):
    """Sort a list of numbers in ascending order."""
    length = len(values)
    for a in range(length):
        for b in range(0, length - a - 1):
            if values[b] > values[b + 1]:
                values[b], values[b + 1] = values[b + 1], values[b]
    return values
'''

UNRELATED_CODE = b'''
def fibonacci(n):
    """Return the first n Fibonacci numbers."""
    a, b = 0, 1
    out = []
    for _ in range(n):
        out.append(a)
        a, b = b, a + b
    return out
'''


def _submit(student_tok, subject_id, assignment, code_bytes, filename="solution.py"):
    """Submit as student_tok, or as a fresh student when None (a student can
    submit an assignment only once)."""
    r = submit(client, subject_id, assignment, {"code": (filename, io.BytesIO(code_bytes), "text/x-python")},
               student_tok=student_tok)
    assert r.status_code == 200, r.text
    return r.json()


def test_check_similarity_flags_renamed_copy():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Similarity Test Assignment"
    s1 = _submit(None, subject["id"], assignment, BUBBLE_SORT)
    s2 = _submit(None, subject["id"], assignment, BUBBLE_SORT_RENAMED)
    s3 = _submit(None, subject["id"], assignment, UNRELATED_CODE)

    r = client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/check-similarity",
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["compared"] == 3

    flagged_pairs = {(p["submission_a_id"], p["submission_b_id"]) for p in body["pairs"] if p["flagged"]}
    assert (s1["id"], s2["id"]) in flagged_pairs or (s2["id"], s1["id"]) in flagged_pairs
    assert (s1["id"], s3["id"]) not in flagged_pairs
    assert (s2["id"], s3["id"]) not in flagged_pairs


def test_check_similarity_requires_two_submissions():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Lonely Assignment"
    _submit(student_tok, subject["id"], assignment, BUBBLE_SORT)
    r = client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/check-similarity",
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 400


def test_check_similarity_rejects_instructor_outside_subject():
    subject, _instructor_tok, student_tok = setup_subject_with_users(client)
    # A second, unrelated instructor with no assignment to this subject.
    other_subject, other_instructor_tok, _ = setup_subject_with_users(client)
    assignment = "Cross-subject Assignment"
    _submit(student_tok, subject["id"], assignment, BUBBLE_SORT)
    r = client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/check-similarity",
        headers=auth_headers(other_instructor_tok),
    )
    assert r.status_code == 403


def test_auto_evaluate_runs_full_pipeline_and_stores_result():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={
            "name": "Auto-eval rubric",
            "subject_id": subject["id"],
            "criteria": [
                {"name": "Correctness", "description": "Implements bubble sort correctly", "max_points": 70},
                {"name": "Academic integrity", "description": "Original, authentic work", "max_points": 30},
            ],
        },
        headers=auth_headers(instructor_tok),
    ).json()

    submission = _submit(student_tok, subject["id"], "Auto-eval Assignment", BUBBLE_SORT)

    r = client.post(
        f"/submissions/{submission['id']}/auto-evaluate",
        json={"rubric_id": rubric["id"]},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["grader"] == "heuristic"
    assert 0 <= body["recommended_score"] <= body["recommended_max"]
    assert len(body["criterion_breakdown"]) == 2
    assert body["similarity_flagged"] is False

    fetched = client.get(
        f"/submissions/{submission['id']}/auto-evaluate", headers=auth_headers(instructor_tok)
    ).json()
    assert fetched["id"] == body["id"]

    # Automated evaluation is instructor-only: not even the owning student
    # sees it, and neither does an unrelated instructor.
    assert client.get(
        f"/submissions/{submission['id']}/auto-evaluate", headers=auth_headers(student_tok)
    ).status_code == 403
    _, other_instructor_tok, _ = setup_subject_with_users(client)
    assert client.get(
        f"/submissions/{submission['id']}/auto-evaluate", headers=auth_headers(other_instructor_tok)
    ).status_code == 403


def test_auto_evaluate_reflects_similarity_flag():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Flagged Assignment"
    rubric = client.post(
        "/rubrics",
        json={
            "name": "Flag rubric",
            "subject_id": subject["id"],
            "criteria": [{"name": "Academic integrity", "description": "original work", "max_points": 20}],
        },
        headers=auth_headers(instructor_tok),
    ).json()
    s1 = _submit(None, subject["id"], assignment, BUBBLE_SORT)
    _submit(None, subject["id"], assignment, BUBBLE_SORT_RENAMED)
    client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/check-similarity",
        headers=auth_headers(instructor_tok),
    )

    r = client.post(
        f"/submissions/{s1['id']}/auto-evaluate",
        json={"rubric_id": rubric["id"]},
        headers=auth_headers(instructor_tok),
    )
    body = r.json()
    assert body["similarity_flagged"] is True
    # Shown to the instructor as a review flag...
    assert any("similarity checker flagged" in f for f in body["review_flags"])
    # ...but it does not change the marks (no cap on the integrity criterion).
    integrity = next(c for c in body["criterion_breakdown"] if c["name"] == "Academic integrity")
    assert "capped" not in integrity["justification"]
    assert "score not changed" in integrity["justification"]


def test_auto_evaluate_404_for_unknown_submission():
    subject, instructor_tok, _ = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={"name": "R", "subject_id": subject["id"], "criteria": [{"name": "C", "max_points": 10}]},
        headers=auth_headers(instructor_tok),
    ).json()
    r = client.post(
        "/submissions/999999/auto-evaluate",
        json={"rubric_id": rubric["id"]},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 404


CSHARP = """using System;
class Calc {
    static int Add(int a, int b) { return a + b; }
    static int Multiply(int a, int b) { return a * b; }
    static void Main() {
        int x = int.Parse(Console.ReadLine());
        int y = int.Parse(Console.ReadLine());
        Console.WriteLine("Sum: " + Add(x, y));
        Console.WriteLine("Product: " + Multiply(x, y));
    }
}
"""
CSHARP_RENAMED = (CSHARP.replace("Add", "Plus").replace("Multiply", "Times")
                  .replace("x", "first").replace("y", "second"))
HEADER = "#ifndef CALC_H\n#define CALC_H\nint add(int a, int b);\nint multiply(int a, int b);\n#endif\n"


def test_check_similarity_reads_csharp_and_header_files():
    import zipfile

    def zipped(cs_source):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("src/Calc.cs", cs_source)
            zf.writestr("src/calc.h", HEADER)
        return buf.getvalue()

    subject, instructor_tok, _ = setup_subject_with_users(client)
    assignment = "CSharp Assignment"
    ids = []
    for source in (CSHARP, CSHARP_RENAMED):
        r = submit(client, subject["id"], assignment,
                   {"code": ("project.zip", io.BytesIO(zipped(source)), "application/zip")})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])

    body = client.post(f"/subjects/{subject['id']}/assignments/{assignment}/check-similarity",
                       headers=auth_headers(instructor_tok)).json()
    pair = body["pairs"][0]
    assert {pair["submission_a_id"], pair["submission_b_id"]} == set(ids)
    assert pair["shared_fingerprints"] > 0  # the .cs/.h files were actually read
    assert pair["flagged"] and pair["token_flagged"]  # renaming doesn't hide a copy
