"""Batch auto-evaluate: POST /subjects/{id}/assignments/{name}/auto-evaluate."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import app.main as main
from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, setup_subject_with_users, submit

client = TestClient(fastapi_app)

CODE = b'''
def bubble_sort(items):
    """Sort a list of numbers in ascending order."""
    return sorted(items)
'''


def _setup(n_submissions=3, assignment="Batch Assignment"):
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={"name": "Batch rubric", "subject_id": subject["id"],
              "criteria": [{"name": "Correctness", "description": "Implements bubble sort", "max_points": 10}]},
        headers=auth_headers(instructor_tok),
    ).json()
    submissions = []
    for _ in range(n_submissions):
        r = submit(client, subject["id"], assignment, {"code": ("solution.py", io.BytesIO(CODE), "text/x-python")})
        assert r.status_code == 200, r.text
        submissions.append(r.json())
    return subject, instructor_tok, rubric, assignment, submissions


def _batch(subject, assignment, tok, rubric_id, **extra):
    return client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/auto-evaluate",
        json={"rubric_id": rubric_id, **extra}, headers=auth_headers(tok),
    )


def test_batch_evaluates_every_submission_and_stores_results():
    subject, tok, rubric, assignment, subs = _setup(3)
    r = _batch(subject, assignment, tok, rubric["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total"], body["evaluated"], body["skipped"], body["failed"]) == (3, 3, 0, 0)
    assert {item["submission_id"] for item in body["results"]} == {s["id"] for s in subs}
    for item in body["results"]:
        assert item["status"] == "evaluated"
        assert 0 <= item["recommended_score"] <= item["recommended_max"] == 10
        assert item["grader"]
    for s in subs:
        stored = client.get(f"/submissions/{s['id']}/auto-evaluate", headers=auth_headers(tok)).json()
        assert stored["rubric_id"] == rubric["id"]


def test_batch_skip_already_evaluated_only_runs_the_rest():
    subject, tok, rubric, assignment, subs = _setup(3)
    first = client.post(f"/submissions/{subs[0]['id']}/auto-evaluate",
                        json={"rubric_id": rubric["id"]}, headers=auth_headers(tok))
    assert first.status_code == 200

    body = _batch(subject, assignment, tok, rubric["id"], skip_already_evaluated=True).json()
    assert (body["evaluated"], body["skipped"], body["failed"]) == (2, 1, 0)
    statuses = {item["submission_id"]: item["status"] for item in body["results"]}
    assert statuses[subs[0]["id"]] == "skipped"


def test_batch_continues_when_one_submission_fails(monkeypatch):
    subject, tok, rubric, assignment, subs = _setup(3)
    real = main._run_auto_evaluation
    bad_id = subs[1]["id"]

    def flaky(db, submission, rubric_):
        if submission.id == bad_id:
            raise RuntimeError("Ollama exploded")
        return real(db, submission, rubric_)

    monkeypatch.setattr(main, "_run_auto_evaluation", flaky)
    body = _batch(subject, assignment, tok, rubric["id"]).json()

    assert (body["evaluated"], body["failed"]) == (2, 1)
    failed = next(i for i in body["results"] if i["status"] == "failed")
    assert failed["submission_id"] == bad_id and "Ollama exploded" in failed["error"]
    # the submissions after the failing one were still evaluated and saved
    after = client.get(f"/submissions/{subs[2]['id']}/auto-evaluate", headers=auth_headers(tok)).json()
    assert after is not None


def test_batch_access_and_validation_errors():
    subject, tok, rubric, assignment, subs = _setup(1)
    other_subject, other_tok, _ = setup_subject_with_users(client)

    assert _batch(subject, assignment, other_tok, rubric["id"]).status_code == 403          # not their subject
    assert _batch(subject, assignment, tok, 999999).status_code == 404                      # unknown rubric
    assert _batch(subject, "No Such Assignment", tok, rubric["id"]).status_code == 404      # no submissions

    foreign_rubric = client.post(
        "/rubrics",
        json={"name": "Other", "subject_id": other_subject["id"],
              "criteria": [{"name": "X", "description": "", "max_points": 5}]},
        headers=auth_headers(other_tok),
    ).json()
    assert _batch(subject, assignment, tok, foreign_rubric["id"]).status_code == 400        # wrong subject's rubric


def test_batch_is_instructor_only():
    subject, tok, rubric, assignment, subs = _setup(1)
    _, _, student_tok = setup_subject_with_users(client)
    r = client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/auto-evaluate",
        json={"rubric_id": rubric["id"]}, headers=auth_headers(student_tok),
    )
    assert r.status_code == 403
