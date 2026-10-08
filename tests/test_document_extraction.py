"""
Tests for report text extraction with Microsoft MarkItDown
(app/evaluator/document_extraction.py), the hardened upload endpoint, and
how the extracted text reaches cross-modal semantic consistency.

MarkItDown itself runs for real here (it's local and fast); MiniLM is
replaced by a fake encoder except in the one test marked ``slow``.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.db import BASE_DIR, UPLOAD_DIR
from app.evaluator import document_extraction as dx
from app.evaluator.document_extraction import (
    EXTRACTED_MARKDOWN_NAME,
    EXTRACTION_META_NAME,
    ReportValidationError,
    extract_and_store,
    extract_report_text,
    load_extraction,
    markdown_to_text,
    validate_report_file,
)
from app.evaluator.pipeline import evaluate_submission
from app.evaluator.rubric_grading import Criterion
from app.evaluator.semantic_consistency import SentenceEmbeddingService, set_consistency_service
from app.main import app
from consistency_samples import LIBRARY_CODE, LIBRARY_REPORT, WEATHER_REPORT
from helpers import make_docx, make_pdf
from tests.auth_helpers import auth_headers, ensure_assignment, setup_subject_with_users, submit

client = TestClient(app)
INTERNALS = ("markitdown", "minilm", "unixcoder", "jaccard", "containment", "winnowing", "semantic",
             "plagiar", "ai detection")
CRITERIA = [Criterion(name="Correctness", description="Library loans and fines work", max_points=10)]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.strip().split("\n\n")]


def _multi_page_pdf(path: Path, pages: int) -> Path:
    """One distinct paragraph per page -- make_pdf only fills one page."""
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, page.rect.width - 72, page.rect.height - 72),
                            f"Page {i + 1} discusses loan rules. Unique marker token marker{i + 1}x.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


class FakeEncoder:
    def __init__(self):
        self.texts: list[str] = []

    def encode(self, texts):
        self.texts.extend(texts)
        out = np.zeros((len(texts), 128))
        for i, t in enumerate(texts):
            for w in t.lower().split():
                out[i, zlib.crc32(w.strip(".,").encode()) % 128] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def _service(encoder=None):
    encoder = encoder or FakeEncoder()
    return SentenceEmbeddingService(encoder_factory=lambda: encoder, enabled=True)


# --------------------------------------------------------------------------
# Extraction service
# --------------------------------------------------------------------------


def test_pdf_report_is_extracted(tmp_path):
    pdf = make_pdf(tmp_path / "report.pdf", _paragraphs(LIBRARY_REPORT))
    r = extract_report_text(pdf)
    assert r.status == "ok" and r.backend == "markitdown"
    assert "overdue fine is calculated" in r.text
    assert r.words > 50 and r.error is None


def test_docx_report_is_extracted(tmp_path):
    docx = make_docx(tmp_path / "report.docx", _paragraphs(LIBRARY_REPORT))
    r = extract_report_text(docx)
    assert r.status == "ok"
    assert "fourteen days after the borrowing date" in r.text


def test_markdown_syntax_is_removed_but_content_kept():
    md = (
        "# Design\n\nWe use a **priority queue** and _memoization_.\n\n"
        "| Step | Cost |\n|---|---:|\n| sort | O(n log n) |\n\n"
        "- see [the docs](http://example.com/x)\n- ![architecture diagram](img.png)\n"
        "> quoted remark\n<b>bold html</b>"
    )
    text = markdown_to_text(md)
    for word in ("Design", "priority queue", "memoization", "sort", "O(n log n)", "the docs",
                 "architecture diagram", "quoted remark", "bold html"):
        assert word in text
    for syntax in ("#", "**", "|", "---", "http://", "img.png", "<b>"):
        assert syntax not in text


def test_empty_report_is_reported_as_empty(tmp_path):
    r = extract_report_text(make_docx(tmp_path / "empty.docx", []))
    assert r.status == "empty" and r.text == "" and "no extractable text" in r.error


def test_corrupted_report_fails_without_raising(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.7\n this is not really a pdf body")
    r = extract_report_text(bad)
    assert r.status == "failed"
    assert "PDFSyntaxError" in r.error or "Conversion" in r.error


def test_unsupported_and_disguised_reports(tmp_path):
    txt = tmp_path / "report.txt"
    txt.write_text("plain text report")
    assert extract_report_text(txt).status == "unsupported"

    fake_pdf = tmp_path / "report.pdf"
    fake_pdf.write_bytes(b"MZ\x90\x00 this is an executable, not a pdf")
    r = extract_report_text(fake_pdf)
    assert r.status == "unsupported" and "not a valid PDF" in r.error


def test_converter_exception_becomes_failed_status(tmp_path, monkeypatch):
    def boom(path):
        raise RuntimeError("converter crashed")

    monkeypatch.setattr(dx, "_convert", boom)
    r = extract_report_text(make_pdf(tmp_path / "r.pdf", ["Some text here."]))
    assert r.status == "failed" and "converter crashed" in r.error


def test_slow_conversion_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(dx, "_convert", lambda path: time.sleep(2) or "late")
    monkeypatch.setenv("REPORT_EXTRACTION_TIMEOUT", "1")
    r = extract_report_text(make_pdf(tmp_path / "r.pdf", ["Some text here."]))
    assert r.status == "failed" and "timed out" in r.error


def test_long_report_is_extracted_in_full(tmp_path):
    r = extract_report_text(_multi_page_pdf(tmp_path / "long.pdf", pages=40))
    assert r.status == "ok"
    for i in (1, 20, 40):
        assert f"marker{i}x" in r.text  # the last page is there too: no truncation


def test_extraction_is_stored_next_to_the_upload_and_reloaded(tmp_path):
    report_dir = tmp_path / "sub1" / "report"
    report_dir.mkdir(parents=True)
    pdf = make_pdf(report_dir / "report.pdf", ["The loan period is fourteen days."])
    assert load_extraction(pdf) is None
    stored = extract_and_store(pdf)
    meta = json.loads((tmp_path / "sub1" / EXTRACTION_META_NAME).read_text())
    assert meta["status"] == "ok" and "text" not in meta
    assert (tmp_path / "sub1" / EXTRACTED_MARKDOWN_NAME).read_text() == stored.text
    reloaded = load_extraction(pdf)
    assert reloaded.text == stored.text and reloaded.status == "ok"


def test_report_validation(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "r.pdf", ["Valid."])
    validate_report_file(pdf, "r.pdf", "application/pdf")
    validate_report_file(pdf, "r.pdf", "application/octet-stream")
    with pytest.raises(ReportValidationError):
        validate_report_file(pdf, "r.pdf", "text/html")
    with pytest.raises(ReportValidationError):
        validate_report_file(pdf, "r.docx", "application/pdf")  # extension doesn't match content
    monkeypatch.setenv("REPORT_MAX_BYTES", "10")
    with pytest.raises(ReportValidationError, match="too large"):
        validate_report_file(pdf, "r.pdf", "application/pdf")


# --------------------------------------------------------------------------
# Pipeline: extracted text reaches MiniLM; failures don't stop evaluation
# --------------------------------------------------------------------------


def _code_dir(tmp_path):
    d = tmp_path / "code"
    d.mkdir()
    (d / "library.py").write_text(LIBRARY_CODE)
    return d


def test_extracted_report_text_reaches_the_embedding_model(tmp_path):
    encoder = FakeEncoder()
    pdf = make_pdf(tmp_path / "report.pdf", ["# Library", "Overdue items accrue a zanzibarfine each day."])
    result = evaluate_submission(code_dir=_code_dir(tmp_path), report_path=pdf, criteria=CRITERIA,
                                 consistency_service=_service(encoder))
    sc = result.semantic_consistency
    assert any("zanzibarfine" in t for t in encoder.texts)  # MarkItDown text was embedded
    assert not any(t.lstrip().startswith("#") for t in encoder.texts)  # as plain text
    assert sc.code_report is not None
    assert sc.report_extraction["status"] == "ok" and sc.report_extraction["backend"] == "markitdown"


def test_markitdown_failure_does_not_stop_evaluation_or_change_grades(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "report.pdf", _paragraphs(LIBRARY_REPORT))
    kwargs = dict(code_dir=_code_dir(tmp_path), report_path=pdf, criteria=CRITERIA)
    working = evaluate_submission(**kwargs, consistency_service=_service())

    monkeypatch.setattr(dx, "_convert", lambda path: (_ for _ in ()).throw(RuntimeError("markitdown down")))
    failed = evaluate_submission(**kwargs, consistency_service=_service())

    sc = failed.semantic_consistency
    assert sc.report_extraction["status"] == "failed"
    assert sc.code_report is None and sc.report_transcript is None  # null, not 0
    assert sc.components["report"].note == "Report unavailable (text extraction failed)"
    assert "Report text extraction was unavailable" in sc.warning
    assert failed.report_analysis is not None  # the existing report analysis still ran
    assert [(c.name, c.score) for c in failed.grading.criteria] == \
           [(c.name, c.score) for c in working.grading.criteria]


def test_corrupted_report_does_not_stop_evaluation(tmp_path):
    bad = tmp_path / "report.pdf"
    bad.write_bytes(b"%PDF-1.7\n corrupted")
    result = evaluate_submission(code_dir=_code_dir(tmp_path), report_path=bad, criteria=CRITERIA,
                                 consistency_service=_service())
    assert result.report_analysis is None
    assert any("could not be read" in f for f in result.review_flags)
    assert result.semantic_consistency.report_extraction["status"] == "failed"
    assert result.grading.criteria


# --------------------------------------------------------------------------
# Upload endpoint + auto-evaluate
# --------------------------------------------------------------------------


@pytest.fixture
def consistency(request):
    service = _service()
    set_consistency_service(service)
    yield service
    set_consistency_service(None)


def _setup():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post("/rubrics", json={"name": "R", "subject_id": subject["id"],
                                           "criteria": [{"name": "Correctness", "max_points": 10}]},
                         headers=auth_headers(instructor_tok)).json()
    return subject, instructor_tok, student_tok, rubric


def _submit(student_tok, subject_id, files):
    return submit(client, subject_id, "Library", files, student_tok=student_tok)


def _code():
    return ("library.py", io.BytesIO(LIBRARY_CODE.encode()), "text/x-python")


def _upload_dirs() -> set[str]:
    return {p.name for p in UPLOAD_DIR.iterdir() if p.is_dir()}


def _auto_eval(instructor_tok, submission_id, rubric_id):
    r = client.post(f"/submissions/{submission_id}/auto-evaluate", json={"rubric_id": rubric_id},
                    headers=auth_headers(instructor_tok))
    assert r.status_code == 200, r.text
    return r.json()


def test_pdf_upload_is_extracted_after_submission(tmp_path, consistency):
    subject, instructor_tok, student_tok, rubric = _setup()
    pdf = make_pdf(tmp_path / "report.pdf", _paragraphs(LIBRARY_REPORT)).read_bytes()
    r = _submit(student_tok, subject["id"], {"code": _code(), "report": ("report.pdf", io.BytesIO(pdf), "application/pdf")})
    assert r.status_code == 200, r.text
    sub = r.json()
    assert not any(k in json.dumps(sub).lower() for k in INTERNALS)  # nothing internal shown to the student

    stored = load_extraction(BASE_DIR / sub["report_path"])  # written by the background task
    assert stored.status == "ok" and "overdue fine" in stored.text

    body = _auto_eval(instructor_tok, sub["id"], rubric["id"])
    cmc = body["cross_modal_consistency"]
    assert cmc["code_report"] is not None
    assert cmc["report_extraction"]["status"] == "ok" and cmc["report_extraction"]["backend"] == "markitdown"


def test_docx_upload_is_extracted(tmp_path, consistency):
    subject, instructor_tok, student_tok, rubric = _setup()
    docx = make_docx(tmp_path / "report.docx", _paragraphs(LIBRARY_REPORT)).read_bytes()
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    sub = _submit(student_tok, subject["id"], {"code": _code(), "report": ("report.docx", io.BytesIO(docx), mime)}).json()
    assert load_extraction(BASE_DIR / sub["report_path"]).status == "ok"
    assert _auto_eval(instructor_tok, sub["id"], rubric["id"])["cross_modal_consistency"]["code_report"] is not None


@pytest.mark.parametrize("filename,content,mime", [
    ("report.txt", b"plain text", "text/plain"),
    ("report.md", b"# markdown", "text/markdown"),
    ("report.pdf", b"MZ\x90\x00 executable pretending to be a pdf", "application/pdf"),
    ("report.docx", b"PK\x03\x04 not really a docx", "application/octet-stream"),
])
def test_unsupported_or_disguised_report_is_rejected_cleanly(filename, content, mime):
    subject, _, student_tok, _ = _setup()
    before = _upload_dirs()
    r = _submit(student_tok, subject["id"], {"code": _code(), "report": (filename, io.BytesIO(content), mime)})
    assert r.status_code == 400
    assert "PDF or DOCX" in r.json()["detail"]
    assert not any(k in r.json()["detail"].lower() for k in INTERNALS)
    assert _upload_dirs() == before  # nothing left behind, not even the code file


def test_oversized_report_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_MAX_BYTES", "200")
    subject, _, student_tok, _ = _setup()
    pdf = make_pdf(tmp_path / "report.pdf", _paragraphs(LIBRARY_REPORT)).read_bytes()
    r = _submit(student_tok, subject["id"], {"report": ("report.pdf", io.BytesIO(pdf), "application/pdf")})
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_corrupted_report_is_accepted_but_marked_unavailable_for_the_instructor(consistency):
    subject, instructor_tok, student_tok, rubric = _setup()
    r = _submit(student_tok, subject["id"], {
        "code": _code(), "report": ("report.pdf", io.BytesIO(b"%PDF-1.7\n corrupted body"), "application/pdf")})
    assert r.status_code == 200  # the student isn't told about internal processing
    body = _auto_eval(instructor_tok, r.json()["id"], rubric["id"])
    cmc = body["cross_modal_consistency"]
    assert cmc["report_extraction"]["status"] == "failed"
    assert cmc["code_report"] is None and cmc["report_transcript"] is None
    assert cmc["components"]["report"]["note"] == "Report unavailable (text extraction failed)"
    assert "Report text extraction was unavailable" in cmc["warning"]
    assert body["recommended_max"] == 10  # grading still ran


def test_empty_report_upload(tmp_path, consistency):
    subject, instructor_tok, student_tok, rubric = _setup()
    docx = make_docx(tmp_path / "empty.docx", []).read_bytes()
    sub = _submit(student_tok, subject["id"], {"code": _code(), "report": ("empty.docx", io.BytesIO(docx), "")}).json()
    cmc = _auto_eval(instructor_tok, sub["id"], rubric["id"])["cross_modal_consistency"]
    assert cmc["report_extraction"]["status"] == "empty"
    assert cmc["components"]["report"]["note"] == "Report unavailable (no extractable text)"
    assert cmc["code_report"] is None


def test_missing_report_is_null_not_zero(consistency):
    subject, instructor_tok, student_tok, rubric = _setup()
    sub = _submit(student_tok, subject["id"], {"code": _code()}).json()
    cmc = _auto_eval(instructor_tok, sub["id"], rubric["id"])["cross_modal_consistency"]
    assert cmc["code_report"] is None and cmc["report_transcript"] is None
    assert cmc["report_extraction"] is None
    assert cmc["components"]["report"]["note"] == "Report not submitted"
    assert cmc["status"] == "limited_data" and cmc["overall"] is None


def test_older_submission_without_stored_extraction_is_extracted_on_demand(tmp_path, consistency):
    subject, instructor_tok, student_tok, rubric = _setup()
    pdf = make_pdf(tmp_path / "report.pdf", _paragraphs(WEATHER_REPORT)).read_bytes()
    sub = _submit(student_tok, subject["id"], {"code": _code(), "report": ("report.pdf", io.BytesIO(pdf), "application/pdf")}).json()
    folder = (BASE_DIR / sub["report_path"]).parent.parent
    (folder / EXTRACTION_META_NAME).unlink()
    (folder / EXTRACTED_MARKDOWN_NAME).unlink()
    cmc = _auto_eval(instructor_tok, sub["id"], rubric["id"])["cross_modal_consistency"]
    assert cmc["report_extraction"]["status"] == "ok"
    assert (folder / EXTRACTION_META_NAME).exists()  # kept for next time


def test_crafted_filenames_cannot_escape_the_submission_folder():
    subject, _, student_tok, _ = _setup()
    for name in ("../../app/main.py", "..\\..\\evil.py", "C:/Windows/evil.py", ".hidden.py"):
        before = _upload_dirs()
        r = _submit(None, subject["id"], {"code": (name, io.BytesIO(b"x = 1\n"), "text/plain")})
        assert r.status_code == 200, (name, r.text)
        new_dir = UPLOAD_DIR / (_upload_dirs() - before).pop()
        written = [p for p in new_dir.rglob("*") if p.is_file()]
        assert len(written) == 1 and written[0].parent == new_dir / "code"
    assert (BASE_DIR / "app" / "main.py").read_text(encoding="utf-8").startswith('"""')


def test_zip_entries_pointing_outside_are_skipped():
    subject, _, student_tok, _ = _setup()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/ok.py", "print('ok')\n")
        zf.writestr("../../escaped.py", "print('bad')\n")
    before = _upload_dirs()
    r = _submit(student_tok, subject["id"], {"code": ("project.zip", io.BytesIO(buf.getvalue()), "application/zip")})
    assert r.status_code == 200
    new_dir = UPLOAD_DIR / (_upload_dirs() - before).pop()
    files = sorted(p.relative_to(new_dir).as_posix() for p in new_dir.rglob("*") if p.is_file())
    assert files == ["code/src/ok.py"]
    assert not (UPLOAD_DIR / "escaped.py").exists() and not (BASE_DIR / "escaped.py").exists()


def test_invalid_code_and_video_types_are_rejected():
    subject, _, student_tok, _ = _setup()
    r = _submit(student_tok, subject["id"], {"code": ("tool.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert r.status_code == 400 and "source-code" in r.json()["detail"]
    r = _submit(student_tok, subject["id"], {"video": ("talk.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert r.status_code == 400 and "MP4" in r.json()["detail"]
    r = _submit(student_tok, subject["id"], {"code": ("project.zip", io.BytesIO(b"not a zip"), "application/zip")})
    assert r.status_code == 400 and "not a valid .zip" in r.json()["detail"]


# --------------------------------------------------------------------------
# Real MiniLM on MarkItDown output (slow; skips if the model can't load)
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_real_minilm_on_markitdown_report(tmp_path):
    service = SentenceEmbeddingService(enabled=True)
    if not service.load():
        pytest.skip(f"all-MiniLM-L6-v2 unavailable: {service.error}")
    kwargs = dict(code_dir=_code_dir(tmp_path), criteria=CRITERIA, consistency_service=service)
    matching = evaluate_submission(report_path=make_pdf(tmp_path / "a.pdf", _paragraphs(LIBRARY_REPORT)), **kwargs)
    other = evaluate_submission(report_path=make_docx(tmp_path / "b.docx", _paragraphs(WEATHER_REPORT)), **kwargs)
    assert matching.semantic_consistency.code_report >= 0.6
    assert other.semantic_consistency.code_report < 0.25
