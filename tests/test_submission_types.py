"""Instructors choose which file kinds an assignment accepts (code, report,
video, or any combination); students can only submit those kinds."""

import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from tests.auth_helpers import (
    admin_token,
    auth_headers,
    create_assignment,
    create_instructor,
    create_student,
    create_subject,
    setup_subject_with_users,
    submit,
)
from tests.helpers import make_pdf

client = TestClient(app)
H = auth_headers
ALL = ["code", "report", "video"]


def _file(name, data, mime="application/octet-stream"):
    return (name, io.BytesIO(data), mime)


def _code():
    return {"code": _file("solution.py", b"print('ok')\n", "text/x-python")}


def _video():
    return {"video": _file("talk.mp4", b"v" * 64, "video/mp4")}


def _report(tmp_path):
    pdf = make_pdf(tmp_path / "report.pdf", ["A short report describing the solution."])
    return {"report": _file("report.pdf", pdf.read_bytes(), "application/pdf")}


def _assignment(instructor_tok, subject_id, name, types=None):
    return create_assignment(client, instructor_tok, subject_id, name, submission_types=types)


# ---- creating and reading the setting -------------------------------------


def test_assignments_accept_every_type_by_default():
    subject, itok, stok = setup_subject_with_users(client)
    created = _assignment(itok, subject["id"], "Default types")
    assert created["submission_types"] == ALL
    listed = client.get("/assignments", headers=H(stok)).json()
    assert next(a for a in listed if a["name"] == "Default types")["submission_types"] == ALL


def test_instructor_can_choose_a_subset_in_canonical_order():
    subject, itok, _ = setup_subject_with_users(client)
    created = _assignment(itok, subject["id"], "Video and code", types=["video", "code", "video"])
    assert created["submission_types"] == ["code", "video"]  # de-duplicated, canonical order


def test_an_empty_or_unknown_type_is_rejected():
    subject, itok, _ = setup_subject_with_users(client)
    empty = client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": "Nothing", "available_from": "2026-01-01T00:00:00Z",
        "deadline": "2026-12-31T00:00:00Z", "submission_types": []})
    assert empty.status_code == 400 and "at least one" in empty.json()["detail"]
    unknown = client.post("/assignments", headers=H(itok), json={
        "subject_id": subject["id"], "name": "Slides", "available_from": "2026-01-01T00:00:00Z",
        "deadline": "2026-12-31T00:00:00Z", "submission_types": ["slides"]})
    assert unknown.status_code == 422


# ---- students are limited to the accepted kinds ---------------------------


def test_report_only_assignment_refuses_code_and_video(tmp_path):
    subject, itok, _ = setup_subject_with_users(client)
    _assignment(itok, subject["id"], "Report only", types=["report"])

    code = submit(client, subject["id"], "Report only", _code())
    assert code.status_code == 400 and "accepts only: report" in code.json()["detail"]
    assert "code" in code.json()["detail"].split("Remove the")[1]

    video = submit(client, subject["id"], "Report only", _video())
    assert video.status_code == 400 and "accepts only: report" in video.json()["detail"]


def test_report_only_assignment_accepts_a_report(tmp_path):
    subject, itok, _ = setup_subject_with_users(client)
    _assignment(itok, subject["id"], "Report accepted", types=["report"])
    r = submit(client, subject["id"], "Report accepted", _report(tmp_path))
    assert r.status_code == 200, r.text
    assert r.json()["report_path"] and r.json()["code_path"] is None


def test_code_and_video_assignment_accepts_either_but_not_a_report(tmp_path):
    subject, itok, _ = setup_subject_with_users(client)
    _assignment(itok, subject["id"], "Code or video", types=["code", "video"])
    assert submit(client, subject["id"], "Code or video", _video()).status_code == 200
    refused = submit(client, subject["id"], "Code or video", _report(tmp_path))
    assert refused.status_code == 400 and "accepts only: code" in refused.json()["detail"]


def test_default_assignment_still_accepts_every_kind(tmp_path):
    subject, _itok, _stok = setup_subject_with_users(client)
    r = submit(client, subject["id"], "Legacy default", {**_code(), **_report(tmp_path)})
    assert r.status_code == 200, r.text


def test_edit_cannot_add_a_kind_the_assignment_does_not_accept(tmp_path):
    subject, itok, _ = setup_subject_with_users(client)
    _assignment(itok, subject["id"], "Edit limits", types=["report"])
    first = submit(client, subject["id"], "Edit limits", _report(tmp_path))
    assert first.status_code == 200, first.text
    student_tok = first.request.headers["Authorization"].split(" ", 1)[1]
    sub_id = first.json()["id"]
    r = client.put(f"/submissions/{sub_id}", files=_video(), headers=H(student_tok))
    assert r.status_code == 400 and "accepts only: report" in r.json()["detail"]


# ---- changing the setting -------------------------------------------------


def test_instructor_can_change_types_before_anyone_submits():
    subject, itok, _ = setup_subject_with_users(client)
    a = _assignment(itok, subject["id"], "Change early")
    r = client.put(f"/assignments/{a['id']}", headers=H(itok), json={"submission_types": ["video"]})
    assert r.status_code == 200, r.text
    assert r.json()["submission_types"] == ["video"]


def test_types_are_locked_once_a_student_has_submitted(tmp_path):
    subject, itok, _ = setup_subject_with_users(client)
    a = _assignment(itok, subject["id"], "Change late", types=["report"])
    assert submit(client, subject["id"], "Change late", _report(tmp_path)).status_code == 200
    r = client.put(f"/assignments/{a['id']}", headers=H(itok), json={"submission_types": ["code"]})
    assert r.status_code == 409 and "can't be changed" in r.json()["detail"]
    # Changing other fields is still allowed, and an unchanged list is not a change.
    same = client.put(f"/assignments/{a['id']}", headers=H(itok),
                      json={"submission_types": ["report"], "description": "Updated"})
    assert same.status_code == 200, same.text


def test_other_instructors_cannot_change_an_assignment():
    subject, itok, _ = setup_subject_with_users(client)
    _, other_itok, _ = setup_subject_with_users(client)
    a = _assignment(itok, subject["id"], "Not yours")
    r = client.put(f"/assignments/{a['id']}", headers=H(other_itok), json={"submission_types": ["video"]})
    assert r.status_code in (403, 404)
