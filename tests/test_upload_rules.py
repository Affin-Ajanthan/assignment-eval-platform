"""Student upload rules: file types and size limits are enforced by the backend.

The limits are shrunk with monkeypatch so the tests stay fast: the upload code
reads the module-level limits at call time, so a patched value takes effect."""

import io
import zipfile

from fastapi.testclient import TestClient

from app import main
from app.main import app
from tests.auth_helpers import setup_subject_with_users, submit

client = TestClient(app)


def _setup():
    return setup_subject_with_users(client)


def _file(name, data, mime="application/octet-stream"):
    return (name, io.BytesIO(data), mime)


def _zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


# ---- size limits (413) ----------------------------------------------------


def test_single_code_file_over_the_limit_is_rejected(monkeypatch):
    subject, _itok, _stok = _setup()
    monkeypatch.setattr(main, "_CODE_MAX_BYTES", 100)
    r = submit(client, subject["id"], "Code limit", {"code": _file("solution.py", b"x" * 500, "text/x-python")})
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_zip_that_unpacks_over_the_limit_is_rejected(monkeypatch):
    subject, _itok, _stok = _setup()
    monkeypatch.setattr(main, "_ZIP_MAX_UNCOMPRESSED_BYTES", 1000)
    # Tiny when compressed, large once unpacked: the unpacked-size rule must catch it.
    bomb = _zip_bytes({"big.txt": b"0" * 5000})
    assert len(bomb) < 1000
    r = submit(client, subject["id"], "Zip limit", {"code": _file("code.zip", bomb, "application/zip")})
    assert r.status_code == 413 and "unpacked" in r.json()["detail"]


def test_video_over_the_limit_is_rejected(monkeypatch):
    subject, _itok, _stok = _setup()
    monkeypatch.setattr(main, "_VIDEO_MAX_BYTES", 100)
    r = submit(client, subject["id"], "Video limit", {"video": _file("talk.mp4", b"v" * 500, "video/mp4")})
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_files_within_the_limits_are_accepted(monkeypatch):
    subject, _itok, _stok = _setup()
    monkeypatch.setattr(main, "_CODE_MAX_BYTES", 10_000)
    monkeypatch.setattr(main, "_VIDEO_MAX_BYTES", 10_000)
    r = submit(client, subject["id"], "Within limits", {
        "code": _file("solution.py", b"print('ok')\n", "text/x-python"),
        "video": _file("talk.mp4", b"v" * 500, "video/mp4"),
    })
    assert r.status_code == 200, r.text


# ---- accepted types (400) -------------------------------------------------


def test_unsupported_code_type_is_rejected():
    subject, _itok, _stok = _setup()
    r = submit(client, subject["id"], "Bad code type", {"code": _file("program.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 400 and ".zip" in r.json()["detail"]


def test_unsupported_video_type_is_rejected():
    subject, _itok, _stok = _setup()
    r = submit(client, subject["id"], "Bad video type", {"video": _file("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "MP4" in r.json()["detail"]


def test_unsupported_report_type_is_rejected():
    subject, _itok, _stok = _setup()
    r = submit(client, subject["id"], "Bad report type", {"report": _file("essay.odt", b"x", "application/vnd.oasis")})
    assert r.status_code == 400 and "PDF or DOCX" in r.json()["detail"]


def test_accepted_code_zip_and_single_file_are_both_allowed():
    subject, _itok, _stok = _setup()
    single = submit(client, subject["id"], "Single file", {"code": _file("solution.py", b"x = 1\n", "text/x-python")})
    zipped = submit(client, subject["id"], "Zipped", {"code": _file("code.zip", _zip_bytes({"a.py": "x = 1\n"}), "application/zip")})
    assert single.status_code == 200, single.text
    assert zipped.status_code == 200, zipped.text
