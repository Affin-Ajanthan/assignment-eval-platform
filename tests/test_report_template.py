"""Template PDF for the report similarity check: the instructor's question
paper / report template is cut out of every student report before comparing.
POST/DELETE /assignments/{id}/report-template."""

import io
import sys
import textwrap
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app as fastapi_app
from app.similarity import report_similarity as rs
from tests.auth_helpers import auth_headers, ensure_assignment, setup_subject_with_users, submit

client = TestClient(fastapi_app)
H = auth_headers

QUESTION = (
    "Assignment 3 Library Lending System. Write a command-line program that loads books, members and loans "
    "from three CSV files, validates every row, lends and returns books under the student and staff rules, "
    "calculates late fines capped at one thousand rupees per loan, and prints an overdue report and a library "
    "summary with the most borrowed books, the most active member and the percentage of loans returned late."
)
REPORT_A = (
    "In my design the data is loaded once by a storage module and the rules live in a separate lending class. "
    "I used dataclasses for books, members and loans, and dictionaries keyed by id so lookups are fast. The fine "
    "is the number of late days times the daily rate for the member type, and the menu only prints results."
)
REPORT_B = (
    "I wrote plain functions instead of classes because the program is small. Each CSV parser returns an object "
    "or raises an error with a reason that the menu prints. For the overdue report I sort open loans by days late "
    "and I treat a fine as paid when the book comes back, which is how the summary separates collected fines."
)


def pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), "\n".join(textwrap.wrap(text, 90)), fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(tok, assignment_id, data, name="question.pdf"):
    return client.post(f"/assignments/{assignment_id}/report-template", headers=H(tok),
                       files={"file": (name, io.BytesIO(data), "application/pdf")})


# ---- text removal ------------------------------------------------------------

def test_template_runs_are_cut_and_own_text_is_kept():
    report = f"Question: {QUESTION} My answer: {REPORT_A}"
    text, cut = rs.remove_template_text(report, QUESTION)
    assert cut >= 60
    assert "Library Lending System" not in text and "capped at one thousand" not in text
    assert "dataclasses for books, members and loans" in text


def test_short_shared_phrases_are_kept():
    # Under TEMPLATE_MIN_WORDS consecutive words in common: ordinary phrasing, not the template.
    text, cut = rs.remove_template_text("I loads books, members and loans from disk.", QUESTION)
    assert cut == 0 and "members and loans" in text


def test_pasted_question_no_longer_makes_honest_reports_look_copied():
    reports = {"a": f"{QUESTION} {REPORT_A}", "b": f"{QUESTION} {REPORT_B}"}
    without = rs.compare_reports(reports)
    assert without.pairs[0].flag_level == "high"  # only 2 reports: the shared question isn't "common" yet
    with_template = rs.compare_reports(reports, template_text=QUESTION)
    assert with_template.pairs[0].flag_level is None
    assert with_template.pairs[0].passages == []
    assert set(with_template.template_words_removed) == {"a", "b"}


def test_real_copying_is_still_caught_with_a_template():
    reports = {"a": f"{QUESTION} {REPORT_A}", "b": f"{QUESTION} {REPORT_A} I also tested it."}
    result = rs.compare_reports(reports, template_text=QUESTION)
    assert result.pairs[0].flag_level == "high"
    assert "dataclasses" in result.pairs[0].passages[0].text_a


# ---- endpoints -----------------------------------------------------------------

def test_upload_replace_and_remove_template():
    subject, tok, _ = setup_subject_with_users(client)
    assignment = ensure_assignment(client, subject["id"], "Template Upload Assignment")
    r = _upload(tok, assignment["id"], pdf(QUESTION))
    assert r.status_code == 200, r.text
    assert r.json()["report_template_filename"] == "question.pdf"
    assert r.json()["report_template_words"] >= 50

    r = _upload(tok, assignment["id"], pdf(QUESTION + " Extra instructions for the report."), "v2.pdf")
    assert r.json()["report_template_filename"] == "v2.pdf"

    r = client.delete(f"/assignments/{assignment['id']}/report-template", headers=H(tok))
    assert r.status_code == 200 and r.json()["report_template_filename"] == ""


def test_upload_validation():
    subject, tok, _ = setup_subject_with_users(client)
    assignment = ensure_assignment(client, subject["id"], "Template Validation Assignment")
    assert _upload(tok, assignment["id"], b"hello", "notes.txt").status_code == 400
    assert _upload(tok, assignment["id"], b"not a pdf at all", "fake.pdf").status_code == 400
    assert _upload(tok, assignment["id"], pdf("Too short."), "empty.pdf").status_code == 400


def test_only_the_subjects_instructors_can_manage_templates():
    subject, tok, student_tok = setup_subject_with_users(client)
    _, other_tok, _ = setup_subject_with_users(client)
    assignment = ensure_assignment(client, subject["id"], "Template Access Assignment")
    assert _upload(student_tok, assignment["id"], pdf(QUESTION)).status_code == 403
    assert _upload(other_tok, assignment["id"], pdf(QUESTION)).status_code == 403
    assert client.delete(f"/assignments/{assignment['id']}/report-template",
                         headers=H(other_tok)).status_code == 403


def test_report_similarity_endpoint_uses_the_template():
    subject, tok, _ = setup_subject_with_users(client)
    name = "Template Check Assignment"
    assignment = ensure_assignment(client, subject["id"], name)
    for i, body in enumerate((REPORT_A, REPORT_B)):
        r = submit(client, subject["id"], name,
                   {"report": (f"r{i}.pdf", io.BytesIO(pdf(f"{QUESTION} {body}")), "application/pdf")})
        assert r.status_code == 200, r.text
    url = f"/subjects/{subject['id']}/assignments/{name}/check-report-similarity"

    before = client.post(url, headers=H(tok)).json()
    assert before["template_filename"] is None and before["pairs"][0]["flag_level"] == "high"

    _upload(tok, assignment["id"], pdf(QUESTION))
    after = client.post(url, headers=H(tok)).json()
    assert after["template_filename"] == "question.pdf"
    assert after["pairs"][0]["flag_level"] is None
    assert all(n > 0 for n in after["template_words_removed"].values())
