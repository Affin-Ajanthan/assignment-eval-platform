import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, setup_subject_with_users

client = TestClient(fastapi_app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


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
        data={"subject_id": subject["id"], "assignment_name": "Assignment 2"},
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

    # The owning student can see their own grade too.
    fetched_grade = client.get(f"/submissions/{submission['id']}/grade", headers=auth_headers(student_tok)).json()
    assert fetched_grade["total_score"] == 90


def test_grade_rejects_unknown_criterion():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post(
        "/rubrics",
        json={"name": "Tiny rubric", "subject_id": subject["id"], "criteria": [{"name": "Only", "max_points": 10}]},
        headers=auth_headers(instructor_tok),
    ).json()
    submission = client.post(
        "/submissions",
        data={"subject_id": subject["id"], "assignment_name": "Assignment X"},
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
        data={"subject_id": subject["id"], "assignment_name": "Assignment Y"},
        headers=auth_headers(student_tok),
    ).json()
    r = client.post(
        f"/submissions/{submission['id']}/grade",
        json={"rubric_id": rubric["id"], "criterion_scores": {"Only": 99}},
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 400
