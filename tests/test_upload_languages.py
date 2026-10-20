"""Code uploads are limited to languages the code checks read; anything else is
refused with a message that lists what is accepted (no silently unchecked work)."""

import io
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, new_student, setup_subject_with_users, submit

client = TestClient(fastapi_app)


def _zip(files: dict[str, str]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    buf.seek(0)
    return buf


def _code(subject_id, name, data):
    return submit(client, subject_id, "Language Assignment", {"code": (name, data, "application/octet-stream")})


def test_unsupported_single_files_are_refused_with_the_accepted_list():
    subject, _, _ = setup_subject_with_users(client)
    for name in ("app.ts", "App.tsx", "App.jsx", "Main.kt", "main.swift", "main.rs", "notes"):
        r = _code(subject["id"], name, io.BytesIO(b"let x = 1;"))
        assert r.status_code == 400, (name, r.text)
        detail = r.json()["detail"]
        assert "not a supported language" in detail
        assert "Python (.py, .ipynb)" in detail and "Java (.java)" in detail and "PHP (.php)" in detail


def test_supported_single_files_are_accepted():
    subject, _, _ = setup_subject_with_users(client)
    for name in ("main.py", "Main.java", "app.js", "main.c", "main.cpp", "Program.cs", "main.go", "app.rb", "index.php"):
        r = _code(subject["id"], name, io.BytesIO(b"x = 1\n"))
        assert r.status_code == 200, (name, r.text)


def test_zip_without_supported_code_is_refused():
    subject, _, _ = setup_subject_with_users(client)
    r = _code(subject["id"], "project.zip", _zip({"src/app.ts": "let x = 1;", "README.md": "# app"}))
    assert r.status_code == 400
    assert "contains no code in a supported language" in r.json()["detail"]


def test_zip_with_supported_code_and_other_files_is_accepted():
    subject, _, _ = setup_subject_with_users(client)
    r = _code(subject["id"], "project.zip",
              _zip({"main.py": "print(1)\n", "README.md": "# app", "data/marks.csv": "a,1", "extra/app.ts": "x"}))
    assert r.status_code == 200, r.text


def test_editing_with_an_unsupported_file_keeps_the_original():
    subject, _, _ = setup_subject_with_users(client)
    tok = new_student(client, subject["id"])
    first = submit(client, subject["id"], "Language Edit Assignment",
                   {"code": ("main.py", io.BytesIO(b"print(1)\n"), "text/x-python")}, student_tok=tok)
    assert first.status_code == 200, first.text
    r = client.put(f"/submissions/{first.json()['id']}", headers=auth_headers(tok),
                   files={"code": ("main.rs", io.BytesIO(b"fn main() {}"), "text/plain")})
    assert r.status_code == 400 and "not a supported language" in r.json()["detail"]
    files = client.get(f"/submissions/{first.json()['id']}/files", headers=auth_headers(tok)).json()
    assert any(f["path"].endswith("main.py") for f in files)
