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

    def flaky(db, submission, rubric_, **kwargs):
        if submission.id == bad_id:
            raise RuntimeError("Ollama exploded")
        return real(db, submission, rubric_, **kwargs)

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


# ---- rubric model on/off switch ------------------------------------------

def _fake_rubric_model(monkeypatch):
    """Stand in for the rubric model (Ollama) with a grader that
    reports its own name, so the tests can see which grader actually ran."""
    import app.evaluator.pipeline as pipeline
    from app.evaluator.rubric_grading import HeuristicRubricGrader

    class FakeRubricModel(HeuristicRubricGrader):
        name = "fake-model"

    monkeypatch.setattr(pipeline, "build_default_grader", FakeRubricModel)


def test_rubric_model_switch_on_by_default_and_off_uses_heuristic(monkeypatch):
    _fake_rubric_model(monkeypatch)
    subject, tok, rubric, assignment, subs = _setup(2, assignment="Switch Assignment")

    on = _batch(subject, assignment, tok, rubric["id"]).json()
    assert {item["grader"] for item in on["results"]} == {"fake-model"}

    off = _batch(subject, assignment, tok, rubric["id"], use_rubric_model=False).json()
    assert off["evaluated"] == 2
    assert {item["grader"] for item in off["results"]} == {"heuristic"}

    single = client.post(f"/submissions/{subs[0]['id']}/auto-evaluate",
                         json={"rubric_id": rubric["id"], "use_rubric_model": False},
                         headers=auth_headers(tok))
    assert single.status_code == 200, single.text
    assert single.json()["grader"] == "heuristic"
    single_on = client.post(f"/submissions/{subs[0]['id']}/auto-evaluate",
                            json={"rubric_id": rubric["id"]}, headers=auth_headers(tok))
    assert single_on.json()["grader"] == "fake-model"


# ---- similarity and AI-detection flag columns ----------------------------

def _high_ai_signal(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(main, "_score_ai_code", lambda sid, src: SimpleNamespace(
        signal="high", score=90, reasons=["uniform style"]))


def test_batch_rows_carry_similarity_flag(monkeypatch):
    subject, tok, rubric, assignment, subs = _setup(3, assignment="Similarity Flags")
    sim = client.post(f"/subjects/{subject['id']}/assignments/{assignment}/check-similarity",
                      headers=auth_headers(tok))
    assert sim.status_code == 200, sim.text
    # three identical solutions: every one is in a flagged pair
    body = _batch(subject, assignment, tok, rubric["id"]).json()
    assert {item["similarity_flagged"] for item in body["results"]} == {True}


def test_batch_rows_carry_ai_flag_without_changing_marks(monkeypatch):
    _high_ai_signal(monkeypatch)
    subject, tok, rubric, assignment, subs = _setup(2, assignment="AI Flags")
    body = _batch(subject, assignment, tok, rubric["id"]).json()
    assert {item["ai_flagged"] for item in body["results"]} == {True}
    assert {item["similarity_flagged"] for item in body["results"]} == {False}
    # the flag is a review signal only: marks are the grader's own
    assert all(item["recommended_score"] is not None for item in body["results"])


def test_skipped_rows_show_stored_marks_and_flags(monkeypatch):
    _high_ai_signal(monkeypatch)
    subject, tok, rubric, assignment, subs = _setup(2, assignment="Resume Flags")
    first = _batch(subject, assignment, tok, rubric["id"]).json()
    again = _batch(subject, assignment, tok, rubric["id"], skip_already_evaluated=True).json()
    assert (again["evaluated"], again["skipped"]) == (0, 2)
    before = {item["submission_id"]: item for item in first["results"]}
    for item in again["results"]:
        prev = before[item["submission_id"]]
        assert item["status"] == "skipped"
        assert item["recommended_score"] == prev["recommended_score"]
        assert item["recommended_max"] == prev["recommended_max"]
        assert item["grader"] == prev["grader"]
        assert item["ai_flagged"] is True and item["similarity_flagged"] is False



def test_batch_rows_carry_ai_signal_method_and_score(monkeypatch):
    _high_ai_signal(monkeypatch)
    subject, tok, rubric, assignment, subs = _setup(1, assignment="AI Signal Details")
    first = _batch(subject, assignment, tok, rubric["id"]).json()["results"][0]
    code = first["ai_signals"]["code"]
    assert (code["signal"], code["score"], code["method"]) == ("high", 90, "style-heuristic")
    assert first["ai_signals"]["report"] is None  # no report submitted
    # skipped rows show the stored details too
    again = _batch(subject, assignment, tok, rubric["id"], skip_already_evaluated=True).json()["results"][0]
    assert again["status"] == "skipped" and again["ai_signals"] == first["ai_signals"]

# ---- AI-content detection switch ---------------------------------------

def test_ai_detection_switch_off_skips_detectors_and_flags(monkeypatch):
    _high_ai_signal(monkeypatch)
    subject, tok, rubric, assignment, subs = _setup(2, assignment="AI Switch")

    def must_not_run(*args, **kwargs):
        raise AssertionError("AI detection ran although it was switched off")

    monkeypatch.setattr(main, "_score_ai_code", must_not_run)
    off = _batch(subject, assignment, tok, rubric["id"], use_ai_detection=False).json()
    assert off["evaluated"] == 2
    assert {item["ai_flagged"] for item in off["results"]} == {False}
    assert all(item["recommended_score"] is not None for item in off["results"])

    stored = client.get(f"/submissions/{subs[0]['id']}/auto-evaluate", headers=auth_headers(tok)).json()
    assert stored["ai_signals"] == {"report": None, "code": None, "disabled": True}

    single = client.post(f"/submissions/{subs[1]['id']}/auto-evaluate",
                         json={"rubric_id": rubric["id"], "use_ai_detection": False},
                         headers=auth_headers(tok))
    assert single.status_code == 200, single.text
    assert single.json()["ai_signals"]["disabled"] is True


def test_ai_detection_on_by_default(monkeypatch):
    _high_ai_signal(monkeypatch)
    subject, tok, rubric, assignment, subs = _setup(1, assignment="AI Default")
    body = _batch(subject, assignment, tok, rubric["id"]).json()
    assert body["results"][0]["ai_flagged"] is True
    stored = client.get(f"/submissions/{subs[0]['id']}/auto-evaluate", headers=auth_headers(tok)).json()
    assert stored["ai_signals"]["disabled"] is False
    assert stored["ai_signals"]["code"]["signal"] == "high"


def test_report_ai_text_signal_off_never_loads_the_detector(monkeypatch):
    from app.evaluator import ai_text_detection, report_analysis

    def must_not_load():
        raise AssertionError("AI-text model loaded although detection was off")

    monkeypatch.setattr(ai_text_detection, "get_ai_text_detector", must_not_load)
    result = report_analysis.ai_text_signal("Some report text. " * 50, enabled=False)
    assert (result.signal, result.method, result.score) == ("off", "off", 0)



def test_batch_runs_submissions_concurrently_and_keeps_their_order(monkeypatch):
    import threading

    subject, tok, rubric, assignment, subs = _setup(2)
    real = main._run_auto_evaluation
    # Both evaluations must be running at the same moment to pass the barrier;
    # run one after another, the first would wait alone and time out.
    both_running = threading.Barrier(2, timeout=10)

    def together(db, submission, rubric_, **kwargs):
        both_running.wait()
        return real(db, submission, rubric_, **kwargs)

    monkeypatch.setattr(main, "_run_auto_evaluation", together)
    monkeypatch.setattr(main, "AUTO_EVAL_WORKERS", 3)  # capped at the 2 submissions
    body = _batch(subject, assignment, tok, rubric["id"]).json()

    assert (body["evaluated"], body["failed"]) == (2, 0), body
    assert [item["submission_id"] for item in body["results"]] == [s["id"] for s in subs]
    for s in subs:  # each worker saved its result with its own database session
        assert client.get(f"/submissions/{s['id']}/auto-evaluate", headers=auth_headers(tok)).json() is not None


def _job(job_id):
    from app.db import SessionLocal
    from app.models import BatchJob

    db = SessionLocal()
    try:
        job = db.get(BatchJob, job_id)
        db.expunge(job)
        return job
    finally:
        db.close()


def test_each_batch_run_is_recorded_as_a_job_with_its_progress(monkeypatch):
    subject, tok, rubric, assignment, subs = _setup(3)
    real = main._run_auto_evaluation
    bad_id = subs[1]["id"]

    def flaky(db, submission, rubric_, **kwargs):
        if submission.id == bad_id:
            raise RuntimeError("Ollama exploded")
        return real(db, submission, rubric_, **kwargs)

    monkeypatch.setattr(main, "_run_auto_evaluation", flaky)
    body = _batch(subject, assignment, tok, rubric["id"]).json()
    assert body["job_id"]

    job = _job(body["job_id"])
    assert (job.status, job.assignment_name, job.rubric_id) == ("done", assignment, rubric["id"])
    assert (job.total, job.evaluated, job.skipped, job.failed, job.done) == (3, 2, 0, 1, 3)
    assert [r["status"] for r in job.results] == ["evaluated", "failed", "evaluated"]  # submission order
    assert job.started_at and job.finished_at and job.error is None
    assert job.options == {"skip_already_evaluated": False, "use_rubric_model": True, "use_ai_detection": True}

    # A resumed run records what it skipped.
    again = _batch(subject, assignment, tok, rubric["id"], skip_already_evaluated=True).json()
    resumed = _job(again["job_id"])
    assert again["job_id"] != body["job_id"]
    assert (resumed.total, resumed.skipped, resumed.evaluated, resumed.failed) == (3, 2, 0, 1)


def test_a_batch_job_that_breaks_is_marked_failed_with_the_reason(monkeypatch):
    subject, tok, rubric, assignment, subs = _setup(1)

    def broken(*args, **kwargs):  # breaks the job itself, not one submission
        raise RuntimeError("disk full")

    monkeypatch.setattr(main, "flag_modified", broken)
    r = _batch(subject, assignment, tok, rubric["id"])
    assert r.status_code == 500 and "disk full" in r.json()["detail"]

    from app.db import SessionLocal
    from app.models import BatchJob

    db = SessionLocal()
    try:
        job = db.query(BatchJob).order_by(BatchJob.id.desc()).first()
        assert (job.status, job.assignment_name) == ("failed", assignment)
        assert "disk full" in job.error and job.finished_at is not None
    finally:
        db.close()


def _start_job(subject, assignment, tok, rubric_id, **extra):
    return client.post(
        f"/subjects/{subject['id']}/assignments/{assignment}/auto-evaluate/jobs",
        json={"rubric_id": rubric_id, **extra},
        headers=auth_headers(tok),
    )


def test_starting_a_job_answers_at_once_and_evaluates_in_the_background():
    subject, tok, rubric, assignment, subs = _setup(3)
    r = _start_job(subject, assignment, tok, rubric["id"])

    # The answer is sent before any grading: the job is still queued.
    assert r.status_code == 202, r.text
    started = r.json()
    assert (started["status"], started["total"], started["done"], started["results"]) == ("queued", 3, 0, [])
    assert started["assignment_name"] == assignment and started["rubric_id"] == rubric["id"]

    # The test client then runs the background task; the job finishes on its own.
    job = _job(started["id"])
    assert (job.status, job.total, job.evaluated, job.failed) == ("done", 3, 3, 0)
    for s in subs:  # every evaluation was saved
        assert client.get(f"/submissions/{s['id']}/auto-evaluate", headers=auth_headers(tok)).json() is not None


def test_starting_a_job_checks_access_and_inputs_like_the_waiting_endpoint():
    subject, tok, rubric, assignment, subs = _setup(1)
    other_subject, other_tok, _ = setup_subject_with_users(client)

    assert _start_job(subject, assignment, other_tok, rubric["id"]).status_code == 403   # not their subject
    assert _start_job(subject, assignment, tok, 999999).status_code == 404               # unknown rubric
    assert _start_job(subject, "No Such Assignment", tok, rubric["id"]).status_code == 404  # no submissions


def _progress(job_id, tok):
    return client.get(f"/auto-evaluate/jobs/{job_id}", headers=auth_headers(tok))


def test_progress_of_a_finished_job():
    subject, tok, rubric, assignment, subs = _setup(3)
    job_id = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]

    r = _progress(job_id, tok)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["total"], body["done"], body["evaluated"], body["failed"]) == ("done", 3, 3, 3, 0)
    assert [item["submission_id"] for item in body["results"]] == [s["id"] for s in subs]
    assert body["started_at"] and body["finished_at"]


def test_progress_part_way_through_a_run(monkeypatch):
    from app.db import SessionLocal
    from app.models import BatchJob

    subject, tok, rubric, assignment, subs = _setup(3)
    monkeypatch.setattr(main, "_run_batch_job", lambda job_id: None)  # keep the job from running
    job_id = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]
    assert _progress(job_id, tok).json()["status"] == "queued"

    # What a real run looks like after the first of three submissions finished.
    db = SessionLocal()
    try:
        job = db.get(BatchJob, job_id)
        job.status, job.evaluated = "running", 1
        job.results = [{"submission_id": subs[0]["id"], "student_name": "A", "status": "evaluated",
                        "recommended_score": 7, "recommended_max": 10}, None, None]
        db.commit()
    finally:
        db.close()

    body = _progress(job_id, tok).json()
    assert (body["status"], body["total"], body["done"]) == ("running", 3, 1)
    assert body["results"][0]["recommended_score"] == 7 and body["results"][1:] == [None, None]
    assert body["finished_at"] is None


def test_progress_is_only_for_the_subjects_instructors():
    from tests.auth_helpers import new_student

    subject, tok, rubric, assignment, subs = _setup(1)
    job_id = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]
    _, other_tok, _ = setup_subject_with_users(client)

    assert _progress(job_id, other_tok).status_code == 403                             # another subject's instructor
    assert _progress(job_id, new_student(client, subject["id"])).status_code == 403    # a student
    assert _progress(999999, tok).status_code == 404                                   # no such job


def _latest(subject, assignment, tok):
    return client.get(f"/subjects/{subject['id']}/assignments/{assignment}/auto-evaluate/jobs/latest",
                      headers=auth_headers(tok))


def test_latest_job_lets_the_page_show_a_run_again(monkeypatch):
    subject, tok, rubric, assignment, subs = _setup(2)
    assert _latest(subject, assignment, tok).json() is None  # never run

    first = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]
    second = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]
    latest = _latest(subject, assignment, tok).json()
    assert latest["id"] == second != first and latest["status"] == "done"
    assert len([r for r in latest["results"] if r]) == 2

    # A job still running (the instructor left the page) is what comes back.
    monkeypatch.setattr(main, "_run_batch_job", lambda job_id: None)
    running = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]
    latest = _latest(subject, assignment, tok).json()
    assert (latest["id"], latest["status"]) == (running, "queued")


def test_latest_job_is_per_assignment_and_only_for_the_subjects_instructors():
    subject, tok, rubric, assignment, subs = _setup(1)
    _start_job(subject, assignment, tok, rubric["id"])
    _, other_tok, _ = setup_subject_with_users(client)

    assert _latest(subject, "Some Other Assignment", tok).json() is None
    assert _latest(subject, assignment, other_tok).status_code == 403


def test_a_second_run_of_the_same_assignment_is_refused_while_one_is_running(monkeypatch):
    from app.db import SessionLocal
    from app.models import BatchJob

    subject, tok, rubric, assignment, subs = _setup(2)
    monkeypatch.setattr(main, "_run_batch_job", lambda job_id: None)  # the first run stays queued
    first = _start_job(subject, assignment, tok, rubric["id"]).json()["id"]

    second = _start_job(subject, assignment, tok, rubric["id"])
    assert second.status_code == 409
    assert "already being evaluated (0 of 2 done)" in second.json()["detail"]
    # The waiting endpoint is blocked the same way.
    assert _batch(subject, assignment, tok, rubric["id"]).status_code == 409

    # Once that run has finished, a new run is allowed again.
    db = SessionLocal()
    try:
        db.get(BatchJob, first).status = "done"
        db.commit()
    finally:
        db.close()
    assert _start_job(subject, assignment, tok, rubric["id"]).status_code == 202
