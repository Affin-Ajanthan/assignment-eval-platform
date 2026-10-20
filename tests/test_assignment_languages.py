"""Optional per-assignment programming language: when the instructor picks
languages, students can submit code only in those; with no choice, every
supported language is accepted as before."""

import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, new_student, setup_subject_with_users

client = TestClient(fastapi_app)


def _assignment(tok, subject_id, languages=None, name="Lang Assignment"):
    now = datetime.now(timezone.utc)
    body = {"subject_id": subject_id, "name": name, "description": "",
            "available_from": (now - timedelta(hours=1)).isoformat(),
            "deadline": (now + timedelta(days=7)).isoformat()}
    if languages is not None:
        body["code_languages"] = languages
    r = client.post("/assignments", json=body, headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    return r.json()


def _zip(files: dict[str, str]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    buf.seek(0)
    return buf


def _submit(subject_id, assignment, name, data, student_tok=None):
    return client.post(
        "/submissions", data={"subject_id": subject_id, "assignment_id": assignment["id"]},
        files={"code": (name, data, "application/octet-stream")},
        headers=auth_headers(student_tok or new_student(client, subject_id)),
    )


def test_no_language_chosen_accepts_every_supported_language():
    subject, tok, _ = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"])
    assert a["code_languages"] == []
    for name in ("main.py", "Main.java", "main.go", "app.rb", "index.php"):
        r = _submit(subject["id"], a, name, io.BytesIO(b"x = 1\n"))
        assert r.status_code == 200, (name, r.text)


def test_chosen_language_is_stored_in_canonical_order_and_shown_to_students():
    subject, tok, student_tok = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"], ["go", "python", "go"])
    assert a["code_languages"] == ["python", "go"]
    seen = client.get(f"/assignments/{a['id']}", headers=auth_headers(student_tok))
    assert seen.status_code == 200, seen.text
    assert seen.json()["code_languages"] == ["python", "go"]


def test_single_file_in_another_language_is_refused():
    subject, tok, _ = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"], ["go"])
    ok = _submit(subject["id"], a, "main.go", io.BytesIO(b"package main\n"))
    assert ok.status_code == 200, ok.text
    bad = _submit(subject["id"], a, "main.py", io.BytesIO(b"print(1)\n"))
    assert bad.status_code == 400
    detail = bad.json()["detail"]
    assert "'Lang Assignment' must be written in Go (.go)" in detail
    assert "'main.py' is Python" in detail


def test_zip_with_code_in_another_language_is_refused_but_other_files_are_fine():
    subject, tok, _ = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"], ["csharp"])
    ok = _submit(subject["id"], a, "project.zip",
                 _zip({"Program.cs": "class P {}", "README.md": "# app", "data/marks.csv": "a,1"}))
    assert ok.status_code == 200, ok.text
    bad = _submit(subject["id"], a, "project.zip",
                  _zip({"Program.cs": "class P {}", "tools/helper.py": "x = 1", "web/app.js": "x"}))
    assert bad.status_code == 400
    detail = bad.json()["detail"]
    assert "must be written in C# (.cs)" in detail
    assert "tools/helper.py (Python)" in detail and "web/app.js (JavaScript)" in detail


def test_header_files_count_for_c_and_cpp():
    subject, tok, _ = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"], ["cpp"])
    r = _submit(subject["id"], a, "project.zip", _zip({"main.cpp": "int main(){}", "grades.h": "int x;"}))
    assert r.status_code == 200, r.text


def test_edit_submission_is_checked_too():
    subject, tok, _ = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"], ["ruby"])
    student = new_student(client, subject["id"])
    first = _submit(subject["id"], a, "app.rb", io.BytesIO(b"puts 1\n"), student)
    assert first.status_code == 200, first.text
    r = client.put(f"/submissions/{first.json()['id']}",
                   files={"code": ("app.php", io.BytesIO(b"<?php echo 1;"), "application/octet-stream")},
                   headers=auth_headers(student))
    assert r.status_code == 400 and "must be written in Ruby (.rb)" in r.json()["detail"]


def test_language_can_be_changed_or_cleared_until_someone_submits():
    subject, tok, _ = setup_subject_with_users(client)
    a = _assignment(tok, subject["id"], ["java"])
    r = client.put(f"/assignments/{a['id']}", json={"code_languages": ["python"]}, headers=auth_headers(tok))
    assert r.status_code == 200 and r.json()["code_languages"] == ["python"]
    r = client.put(f"/assignments/{a['id']}", json={"code_languages": []}, headers=auth_headers(tok))
    assert r.status_code == 200 and r.json()["code_languages"] == []

    r = client.put(f"/assignments/{a['id']}", json={"code_languages": ["python"]}, headers=auth_headers(tok))
    assert _submit(subject["id"], a, "main.py", io.BytesIO(b"x = 1\n")).status_code == 200
    locked = client.put(f"/assignments/{a['id']}", json={"code_languages": ["go"]}, headers=auth_headers(tok))
    assert locked.status_code == 409
    # sending the same choice again (e.g. saving other fields) is fine
    same = client.put(f"/assignments/{a['id']}", json={"code_languages": ["python"], "description": "x"},
                      headers=auth_headers(tok))
    assert same.status_code == 200, same.text


def test_unknown_language_is_rejected():
    subject, tok, _ = setup_subject_with_users(client)
    now = datetime.now(timezone.utc)
    r = client.post("/assignments", json={
        "subject_id": subject["id"], "name": "Bad", "available_from": now.isoformat(),
        "deadline": (now + timedelta(days=1)).isoformat(), "code_languages": ["cobol"]},
        headers=auth_headers(tok))
    assert r.status_code == 422
