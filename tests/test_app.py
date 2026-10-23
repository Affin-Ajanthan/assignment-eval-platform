import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, create_assignment, ensure_assignment, setup_subject_with_users, submit

client = TestClient(fastapi_app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def _health_detector(detector):
    from app.evaluator.ai_text_detection import set_ai_text_detector

    set_ai_text_detector(detector)
    try:
        return client.get("/health").json()["ai_text_detector"]
    finally:
        set_ai_text_detector(None)


def test_health_shows_ai_detector_disabled():
    from app.evaluator.ai_text_detection import AITextDetector

    info = _health_detector(AITextDetector(enabled=False))
    assert info["status"] == "disabled" and info["fallback_to_heuristic"] is True
    assert info["error"] is None and info["model"]


def test_health_shows_ai_detector_ready():
    from app.evaluator.ai_text_detection import AITextDetector

    detector = AITextDetector(scorer_factory=lambda: object(), enabled=True)
    assert detector.load()
    info = _health_detector(detector)
    assert info["status"] == "ready" and info["fallback_to_heuristic"] is False


def test_health_shows_ai_detector_unavailable_without_leaking_the_message():
    from app.evaluator.ai_text_detection import AITextDetector

    def broken():
        raise OSError(r"C:\secret\path\model.safetensors not found")

    detector = AITextDetector(scorer_factory=broken, enabled=True)
    detector.load()
    info = _health_detector(detector)
    assert info["status"] == "unavailable" and info["fallback_to_heuristic"] is True
    assert info["error"] == "OSError"  # type only, not the path


def test_create_and_list_rubric():
    subject, instructor_tok, _ = setup_subject_with_users(client)
    r = client.post(
        "/rubrics",
        json={
            "name": "Assignment 1 rubric",
            "subject_id": subject["id"],
            "criteria": [
                {"name": "Correctness", "description": "Tests pass", "max_points": 60},
                {"name": "Code quality", "description": "Style + structure", "max_points": 40},
            ],
        },
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Assignment 1 rubric"
    assert body["subject_id"] == subject["id"]
    assert body["max_total"] == 100

    listed = client.get("/rubrics", headers=auth_headers(instructor_tok)).json()
    assert any(rb["id"] == body["id"] for rb in listed)


def test_submit_and_grade_flow():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={
            "name": "Assignment 2 rubric",
            "subject_id": subject["id"],
            "criteria": [
                {"name": "Correctness", "description": "", "max_points": 70},
                {"name": "Report clarity", "description": "", "max_points": 30},
            ],
        },
        headers=auth_headers(instructor_tok),
    ).json()

    code_file = io.BytesIO(b"print('hello world')")
    submission = client.post(
        "/submissions",
        data={"subject_id": subject["id"], "assignment_id": ensure_assignment(client, subject["id"], "Assignment 2")["id"]},
        files={"code": ("solution.py", code_file, "text/x-python")},
        headers=auth_headers(student_tok),
    ).json()
    assert submission["status"] == "submitted"
    assert submission["code_path"] is not None
    assert submission["subject_id"] == subject["id"]

    graded = client.post(
        f"/submissions/{submission['id']}/grade",
        json={
            "rubric_id": rubric["id"],
            "criterion_scores": {"Correctness": 65, "Report clarity": 25},
            "comments": "Solid work, minor edge case missed.",
        },
        headers=auth_headers(instructor_tok),
    )
    assert graded.status_code == 200
    grade_body = graded.json()
    assert grade_body["total_score"] == 90
    assert grade_body["graded_by"]  # instructor's name, filled in server-side

    fetched_submission = client.get(f"/submissions/{submission['id']}", headers=auth_headers(instructor_tok)).json()
    assert fetched_submission["status"] == "graded"

    # The owning student sees only the final mark -- not the criterion-level
    # breakdown or comments, which stay instructor-only.
    mine = client.get("/submissions", headers=auth_headers(student_tok)).json()
    assert [(s["id"], s["final_mark"], s["max_mark"]) for s in mine] == [(submission["id"], 90, 100)]
    assert client.get(f"/submissions/{submission['id']}/grade", headers=auth_headers(student_tok)).status_code == 403


def test_grade_rejects_unknown_criterion():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={"name": "Tiny rubric", "subject_id": subject["id"], "criteria": [{"name": "Only", "max_points": 10}]},
        headers=auth_headers(instructor_tok),
    ).json()
    submission = client.post(
        "/submissions",
        data={"subject_id": subject["id"], "assignment_id": ensure_assignment(client, subject["id"], "Assignment X")["id"]},
        files={"code": ("solution.py", io.BytesIO(b"x = 1"), "text/x-python")},
        headers=auth_headers(student_tok),
    ).json()
    r = client.post(
        f"/submissions/{submission['id']}/grade",
        json={"rubric_id": rubric["id"], "criterion_scores": {"Nope": 5}},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 400


def test_grade_rejects_out_of_range_score():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={"name": "Range rubric", "subject_id": subject["id"], "criteria": [{"name": "Only", "max_points": 10}]},
        headers=auth_headers(instructor_tok),
    ).json()
    submission = client.post(
        "/submissions",
        data={"subject_id": subject["id"], "assignment_id": ensure_assignment(client, subject["id"], "Assignment Y")["id"]},
        files={"code": ("solution.py", io.BytesIO(b"x = 1"), "text/x-python")},
        headers=auth_headers(student_tok),
    ).json()
    r = client.post(
        f"/submissions/{submission['id']}/grade",
        json={"rubric_id": rubric["id"], "criterion_scores": {"Only": 99}},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 400


def _two_criteria_submission(assignment_name):
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={"name": "Final mark rubric", "subject_id": subject["id"], "criteria": [
            {"name": "Correctness", "max_points": 70}, {"name": "Report", "max_points": 30}]},
        headers=auth_headers(instructor_tok),
    ).json()
    submission = client.post(
        "/submissions",
        data={"subject_id": subject["id"], "assignment_id": ensure_assignment(client, subject["id"], assignment_name)["id"]},
        files={"code": ("solution.py", io.BytesIO(b"x = 1"), "text/x-python")},
        headers=auth_headers(student_tok),
    ).json()
    return rubric, submission, instructor_tok, student_tok


def test_grade_with_final_mark_only():
    rubric, submission, instructor_tok, student_tok = _two_criteria_submission("Assignment F")
    r = client.post(
        f"/submissions/{submission['id']}/grade",
        json={"rubric_id": rubric["id"], "total_score": 70, "comments": "Overall judgement"},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 200
    assert r.json()["total_score"] == 70
    assert r.json()["criterion_scores"] == {}  # no invented per-criterion split
    mine = client.get("/submissions", headers=auth_headers(student_tok)).json()
    assert [(s["final_mark"], s["max_mark"]) for s in mine] == [(70, 100)]


def test_grade_final_mark_rejects_out_of_range_and_mixed_input():
    rubric, submission, instructor_tok, _ = _two_criteria_submission("Assignment G")
    url = f"/submissions/{submission['id']}/grade"
    for body in ({"total_score": 101}, {"total_score": -1},
                 {"total_score": 50, "criterion_scores": {"Correctness": 50}}):
        r = client.post(url, json={"rubric_id": rubric["id"], **body}, headers=auth_headers(instructor_tok))
        assert r.status_code == 400, body


def test_assignment_with_rubric_is_graded_only_with_that_rubric():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    H = auth_headers(instructor_tok)

    def rubric(name):
        return client.post("/rubrics", headers=H, json={
            "name": name, "subject_id": subject["id"], "criteria": [{"name": "Only", "max_points": 10}]}).json()

    own, other = rubric("Own rubric"), rubric("Other rubric")
    assignment = create_assignment(client, instructor_tok, subject["id"], "Locked rubric", rubric_id=own["id"])
    submission = client.post(
        "/submissions",
        data={"subject_id": subject["id"], "assignment_id": assignment["id"]},
        files={"code": ("solution.py", io.BytesIO(b"x = 1"), "text/x-python")},
        headers=auth_headers(student_tok),
    ).json()
    url = f"/submissions/{submission['id']}"

    wrong = client.post(f"{url}/grade", headers=H, json={"rubric_id": other["id"], "criterion_scores": {"Only": 5}})
    assert wrong.status_code == 400 and "Own rubric" in wrong.json()["detail"]
    assert client.post(f"{url}/auto-evaluate", headers=H, json={"rubric_id": other["id"]}).status_code == 400
    assert client.post(f"{url}/grade", headers=H,
                       json={"rubric_id": own["id"], "criterion_scores": {"Only": 5}}).status_code == 200


def test_grade_marks_allow_at_most_two_decimal_places():
    rubric, submission, instructor_tok, _ = _two_criteria_submission("Assignment D")
    url = f"/submissions/{submission['id']}/grade"
    H = auth_headers(instructor_tok)
    for body in ({"criterion_scores": {"Correctness": 7.3333}}, {"total_score": 70.125}):
        r = client.post(url, json={"rubric_id": rubric["id"], **body}, headers=H)
        assert r.status_code == 400 and "2 decimal places" in r.json()["detail"], body
    ok = client.post(url, json={"rubric_id": rubric["id"], "criterion_scores": {"Correctness": 0.1, "Report": 0.2}},
                     headers=H)
    assert ok.status_code == 200 and ok.json()["total_score"] == 0.3  # not 0.30000000000000004


def test_grade_stores_student_feedback_separately_from_internal_comments():
    rubric, submission, instructor_tok, student_tok = _two_criteria_submission("Assignment Feedback")
    url = f"/submissions/{submission['id']}/grade"
    saved = client.post(url, headers=auth_headers(instructor_tok), json={
        "rubric_id": rubric["id"], "criterion_scores": {"Correctness": 60, "Report": 20},
        "comments": "Check for copying from last year", "feedback": "  Good sorting; explain the design more.  "})
    assert saved.status_code == 200
    assert saved.json()["feedback"] == "Good sorting; explain the design more."  # trimmed
    assert saved.json()["comments"] == "Check for copying from last year"

    fetched = client.get(url, headers=auth_headers(instructor_tok)).json()
    assert fetched["feedback"] == "Good sorting; explain the design more."
    # Blank feedback is stored as "no feedback".
    blank = client.post(url, headers=auth_headers(instructor_tok), json={
        "rubric_id": rubric["id"], "total_score": 70, "feedback": "   "})
    assert blank.json()["feedback"] is None
