"""Viewing submitted files: the owning student and the subject's instructors
can list and download a submission's files; nobody else can, and nothing
outside the submission's own folders is reachable."""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from helpers import make_pdf
from tests.auth_helpers import admin_token, auth_headers, create_assignment, new_student, setup_subject_with_users

client = TestClient(app)
H = auth_headers


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def _submission(tmp_path):
    subject, itok, stok = setup_subject_with_users(client)
    a = create_assignment(client, itok, subject["id"])
    code = _zip({"proj/main.py": "print('hello')\n", "proj/README.txt": "Calculator", "proj/page.html": "<script>x</script>"})
    pdf = make_pdf(tmp_path / "report.pdf", ["My report."]).read_bytes()
    r = client.post("/submissions", data={"subject_id": subject["id"], "assignment_id": a["id"]},
                    files={"code": ("project.zip", io.BytesIO(code), "application/zip"),
                           "report": ("report.pdf", io.BytesIO(pdf), "application/pdf")}, headers=H(stok))
    assert r.status_code == 200, r.text
    return subject, itok, stok, r.json(), pdf


def test_student_and_instructor_can_list_and_download(tmp_path):
    subject, itok, stok, sub, pdf = _submission(tmp_path)
    for tok in (stok, itok, admin_token(client)):
        files = client.get(f"/submissions/{sub['id']}/files", headers=H(tok)).json()
        assert {(f["kind"], f["path"]) for f in files} == {
            ("code", "proj/README.txt"), ("code", "proj/main.py"), ("code", "proj/page.html"), ("report", "report.pdf"),
        }
    r = client.get(f"/submissions/{sub['id']}/files/code/proj/main.py", headers=H(itok))
    assert r.status_code == 200 and r.text == "print('hello')\n"
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    r = client.get(f"/submissions/{sub['id']}/files/report/report.pdf", headers=H(stok))
    assert r.status_code == 200 and r.content == pdf and r.headers["content-type"] == "application/pdf"


def test_renderable_files_are_sent_as_plain_text(tmp_path):
    _, itok, _, sub, _ = _submission(tmp_path)
    r = client.get(f"/submissions/{sub['id']}/files/code/proj/page.html", headers=H(itok))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")


def test_other_students_and_other_instructors_are_refused(tmp_path):
    subject, _, _, sub, _ = _submission(tmp_path)
    classmate = new_student(client, subject["id"])
    _, other_itok, _ = setup_subject_with_users(client)
    for tok in (classmate, other_itok):
        assert client.get(f"/submissions/{sub['id']}/files", headers=H(tok)).status_code == 403
        assert client.get(f"/submissions/{sub['id']}/files/code/proj/main.py", headers=H(tok)).status_code == 403
    assert client.get(f"/submissions/{sub['id']}/files").status_code == 401


def test_paths_outside_the_submission_are_not_reachable(tmp_path):
    _, itok, _, sub, _ = _submission(tmp_path)
    # (A literal "../" is resolved by the HTTP client before sending, so only
    # encoded forms can carry a traversal attempt to the server.)
    for bad in ("code/..%2F..%2F..%2Fapp%2Fmain.py", "code/..%2Freport%2Freport.pdf", "report/../../../../app/main.py",
                "code/%2E%2E/%2E%2E/%2E%2E/portal.db", "video/x.mp4", "secrets/main.py", "code/proj/missing.py"):
        r = client.get(f"/submissions/{sub['id']}/files/{bad}", headers=H(itok))
        assert r.status_code == 404, (bad, r.status_code)
    assert client.get("/submissions/999999/files", headers=H(itok)).status_code == 404
