"""Report (PDF) similarity: cleaning, word Winnowing with matching passages,
MiniLM semantic signal (fake encoder here), and the
POST /subjects/{id}/assignments/{name}/check-report-similarity endpoint."""

import io
import sys
import textwrap
import zlib
from pathlib import Path

import numpy as np
import pymupdf
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.evaluator.semantic_consistency import SentenceEmbeddingService, set_consistency_service
from app.main import app as fastapi_app
from app.similarity import report_similarity as rs
from tests.auth_helpers import auth_headers, setup_subject_with_users, submit

client = TestClient(fastapi_app)

BRIEF = ("Assignment brief: write a Python program that reads student marks from a file, assigns letter "
         "grades and prints a summary with the class average and the highest and lowest scorer.")
ORIGINAL = (
    "My program first opens the marks file inside a try block so that a missing file produces a friendly "
    "message instead of a crash. Each line is split on the comma and the mark is converted to an integer, "
    "and lines that cannot be converted are skipped with a warning. I stored valid records in a dictionary "
    "mapping each name to its mark because it makes the summary easy. The grade function uses a chain of if "
    "statements from the highest band down, which keeps the boundaries readable. The hardest part was "
    "handling blank lines at the end of the file, which I fixed by stripping each line."
)
COPIED = ("My report explains a different design based on two parallel lists for names and marks. "
          + ORIGINAL[120:520] + " I tested it against a hand calculation of the average.")
HONEST = (
    "I approached the task with a class called GradeBook that holds a list of student objects. A regular "
    "expression validates every entry, which also rejects names with digits. Letter grades come from a "
    "lookup table searched with the bisect module, so changing the scheme only means editing the table. "
    "The report is printed in aligned columns using formatted strings, and small unit tests check every "
    "boundary value such as seventy four and seventy five, which caught an off by one error early on."
)
HONEST_2 = (
    "For this assignment everything is procedural. A function called load_marks returns tuples and collects "
    "error messages separately so they are shown together at the end. A mark with a decimal point is treated "
    "as invalid because the specification says marks are whole numbers. The highest and lowest scorers are "
    "found in a single pass to avoid sorting, and when two students share the top mark both names are listed. "
    "An empty input file prints a clear message instead of dividing by zero."
)


def make_pdf(body: str, student: str, pages: int = 2) -> bytes:
    """A report with a running header, page numbers and the shared brief."""
    lines = textwrap.wrap(f"{BRIEF} {body}", 90)
    per_page = -(-len(lines) // pages)
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((50, 40), f"CS101 Grade Report - {student}", fontsize=9)
        page.insert_textbox(pymupdf.Rect(50, 70, 550, 780), "\n".join(lines[n * per_page:(n + 1) * per_page]),
                            fontsize=10)
        page.insert_text((290, 820), f"Page {n + 1} of {pages}", fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


class FakeEncoder:
    """Hashed bag-of-words vectors: shared vocabulary -> high cosine."""

    def encode(self, texts):
        out = np.zeros((len(texts), 256))
        for i, text in enumerate(texts):
            for w in text.lower().split():
                out[i, zlib.crc32(w.strip(".,").encode()) % 256] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def fake_service() -> SentenceEmbeddingService:
    return SentenceEmbeddingService(encoder_factory=FakeEncoder, enabled=True)


# ---- cleaning -------------------------------------------------------------

def test_cleaning_removes_page_numbers_and_running_headers_keeps_content(tmp_path):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(make_pdf(ORIGINAL, "Alice", pages=3))
    text = rs.clean_report_pages(rs.extract_pdf_pages(pdf))
    assert "CS101 Grade Report" not in text
    assert "Page 1 of 3" not in text and "Page 3 of 3" not in text
    assert "dictionary mapping each name to its mark" in text


def test_cleaning_rejoins_hyphenated_words_and_drops_number_lines():
    pages = ["Intro\nThe pro-\ngram reads marks.\n1", "More text here.\n- 2 -", "Last part.\niii"]
    text = rs.clean_report_pages(pages)
    assert "program reads marks." in text
    assert " 1" not in text and "- 2 -" not in text and "iii" not in text


def test_single_page_keeps_its_first_and_last_lines():
    assert rs.clean_report_pages(["Title\nBody sentence.\nClosing line"]) == "Title Body sentence. Closing line"


def test_unreadable_pdf_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not really a pdf")
    try:
        rs.extract_pdf_pages(bad)
    except Exception:
        return
    raise AssertionError("corrupt PDF should raise")


# ---- winnowing + passages ---------------------------------------------------

def test_copied_section_is_found_as_a_passage():
    a, b = rs.tokenize("a", ORIGINAL), rs.tokenize("b", COPIED)
    passages, covered_a, covered_b = rs.matching_passages(a, b)
    assert passages and passages[0].words >= 50
    assert "stored valid records in a dictionary" in passages[0].text_a
    assert passages[0].text_a.lower().split() == passages[0].text_b.lower().split()
    assert covered_a > 0.5 * a.word_count


def test_short_shared_phrases_are_not_passages():
    a = rs.tokenize("a", "The program reads the marks file and prints a report for the class today.")
    b = rs.tokenize("b", "Overall the program reads the marks file but crashes on bad lines sometimes.")
    assert rs.matching_passages(a, b)[0] == []


OWN_WORDS = (
    "My approach keeps the parsing separate from the printing so each function has one job, and I tested "
    "the edge cases by hand with an empty file, a file with only invalid rows and a file with duplicate names."
)


def test_text_in_more_than_half_of_the_reports_is_ignored():
    bodies = [ORIGINAL, HONEST, HONEST_2, OWN_WORDS]  # the brief is in all 4 reports
    reports = [rs.tokenize(str(i), f"{BRIEF} {body}") for i, body in enumerate(bodies)]
    assert rs.remove_common_fingerprints(reports) > 0
    a, b = reports[1], reports[2]
    assert not (set(a.fingerprints) & set(b.fingerprints))  # the brief no longer links them


def test_three_reports_are_too_few_to_guess_the_brief():
    reports = [rs.tokenize(str(i), f"{BRIEF} {body}") for i, body in enumerate([ORIGINAL, HONEST, HONEST_2])]
    assert rs.remove_common_fingerprints(reports) == 0


def test_a_group_of_three_copiers_in_a_class_of_six_is_not_hidden():
    # Exactly half the class shares the same answers: that is a group, not the brief.
    copied = ORIGINAL
    texts = {"c1": copied, "c2": copied + " Done.", "c3": "Summary. " + copied,
             "h1": HONEST, "h2": HONEST_2, "h3": OWN_WORDS}
    result = rs.compare_reports(texts)
    assert result.common_fingerprints_excluded == 0
    flagged = {frozenset((p.submission_a, p.submission_b)) for p in result.pairs if p.flag_level == "high"}
    assert flagged == {frozenset(("c1", "c2")), frozenset(("c1", "c3")), frozenset(("c2", "c3"))}


def test_with_a_template_the_most_reports_rule_is_off():
    texts = {str(i): f"{BRIEF} {body}" for i, body in enumerate([ORIGINAL, HONEST, HONEST_2, OWN_WORDS])}
    assert rs.compare_reports(texts).common_fingerprints_excluded > 0
    assert rs.compare_reports(texts, template_text=BRIEF).common_fingerprints_excluded == 0


def test_fingerprints_are_stable_across_calls():
    assert rs.winnow_words(ORIGINAL.lower().split()) == rs.winnow_words(ORIGINAL.lower().split())


# ---- combined comparison -------------------------------------------------------

def test_compare_flags_copied_passages_high_and_leaves_honest_pairs():
    result = rs.compare_reports({"orig": ORIGINAL, "copy": COPIED, "honest": HONEST, "honest2": HONEST_2},
                                fake_service())
    pairs = {frozenset((p.submission_a, p.submission_b)): p for p in result.pairs}
    copied = pairs[frozenset(("orig", "copy"))]
    assert copied.flag_level == "high" and copied.passages
    assert pairs[frozenset(("honest", "honest2"))].flag_level is None
    assert result.semantic_status == "ok"
    assert all(0.0 <= p.semantic_similarity <= 1.0 for p in result.pairs)


def test_semantic_only_pair_gets_review_flag():
    # Every adjacent word pair swapped: same vocabulary (the fake encoder sees
    # the same meaning) but no identical run of words at all -- a paraphrase.
    words = ORIGINAL.split()
    swapped = " ".join(w for i in range(0, len(words) - 1, 2) for w in (words[i + 1], words[i]))
    result = rs.compare_reports({"a": ORIGINAL, "b": swapped}, fake_service())
    (pair,) = result.pairs
    assert pair.passages == [] and pair.coverage_a == 0.0
    assert pair.semantic_similarity >= rs.SEMANTIC_REVIEW_FLOOR
    assert pair.flag_level == "review" and "meaning" in pair.flag_reason


def test_semantic_disabled_keeps_text_results():
    service = SentenceEmbeddingService(encoder_factory=FakeEncoder, enabled=False)
    result = rs.compare_reports({"orig": ORIGINAL, "copy": COPIED}, service)
    assert result.semantic_status == "disabled" and result.semantic_warning
    (pair,) = result.pairs
    assert pair.semantic_similarity is None and pair.flag_level == "high"


def test_semantic_failure_keeps_text_results():
    class Broken:
        def encode(self, texts):
            raise RuntimeError("boom")

    result = rs.compare_reports({"orig": ORIGINAL, "copy": COPIED},
                                SentenceEmbeddingService(encoder_factory=Broken, enabled=True))
    assert result.semantic_status == "unavailable" and "boom" in result.semantic_warning
    assert result.pairs[0].flag_level == "high"


def test_cohort_rule_raises_the_bar_for_a_uniform_class():
    bar, median = rs.semantic_review_bar([0.80 + i * 0.001 for i in range(12)] + [0.99])
    assert median is not None and bar >= rs.SEMANTIC_REVIEW_FLOOR
    assert rs.semantic_review_bar([0.5, 0.6])[0] == rs.SEMANTIC_REVIEW_FLOOR


# ---- endpoint ----------------------------------------------------------------

def _report(name, body):
    return {"report": (f"{name}.pdf", io.BytesIO(make_pdf(body, name)), "application/pdf")}


def test_endpoint_compares_pdf_reports_and_skips_the_rest():
    subject, tok, _ = setup_subject_with_users(client)
    assignment = "Report Similarity Assignment"
    for name, body in [("orig", ORIGINAL), ("copy", COPIED), ("honest", HONEST)]:
        assert submit(client, subject["id"], assignment, _report(name, body)).status_code == 200
    assert submit(client, subject["id"], assignment,
                  {"report": ("notes.docx", io.BytesIO(b"PK\x03\x04 not really"),
                              "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
                  ).status_code in (200, 400)
    assert submit(client, subject["id"], assignment, _report("tiny", "Too short.")).status_code == 200

    set_consistency_service(fake_service())
    try:
        r = client.post(f"/subjects/{subject['id']}/assignments/{assignment}/check-report-similarity",
                        headers=auth_headers(tok))
    finally:
        set_consistency_service(None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compared"] == 3 and body["exploratory"] is True
    assert any("Too little text" in s["reason"] for s in body["skipped"])
    assert body["semantic"]["status"] == "ok"
    flagged = [p for p in body["pairs"] if p["flag_level"] == "high"]
    assert len(flagged) == 1 and flagged[0]["passages"]
    assert "CS101 Grade Report" not in flagged[0]["passages"][0]["text_a"]


def test_endpoint_does_not_store_flags_that_could_affect_grading():
    from app.db import SessionLocal
    from app.models import SimilarityFlag

    subject, tok, _ = setup_subject_with_users(client)
    assignment = "Report No Grading Effect"
    for name, body in [("orig", ORIGINAL), ("copy", COPIED)]:
        submit(client, subject["id"], assignment, _report(name, body))
    r = client.post(f"/subjects/{subject['id']}/assignments/{assignment}/check-report-similarity",
                    headers=auth_headers(tok))
    assert r.status_code == 200, r.text
    assert r.json()["semantic"]["status"] == "disabled"  # tests run with CROSS_MODAL_SEMANTIC=0
    with SessionLocal() as db:
        assert db.query(SimilarityFlag).filter(SimilarityFlag.subject_id == subject["id"]).count() == 0


def test_endpoint_needs_two_reports_and_instructor_access():
    subject, tok, student_tok = setup_subject_with_users(client)
    assignment = "Report Access"
    submit(client, subject["id"], assignment, _report("only", ORIGINAL))
    url = f"/subjects/{subject['id']}/assignments/{assignment}/check-report-similarity"
    assert client.post(url, headers=auth_headers(tok)).status_code == 400
    assert client.post(url, headers=auth_headers(student_tok)).status_code == 403
    other_subject, other_tok, _ = setup_subject_with_users(client)
    assert client.post(url, headers=auth_headers(other_tok)).status_code == 403


def test_failed_model_load_is_retried_after_the_cooldown(monkeypatch):
    import app.evaluator.semantic_consistency as sc

    attempts = []

    def flaky_factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Cannot send a request, as the client has been closed.")
        return FakeEncoder()

    service = SentenceEmbeddingService(encoder_factory=flaky_factory, enabled=True)
    assert service.load() is False and service.status == "unavailable"
    assert service.load() is False and len(attempts) == 1  # within the cooldown: no new attempt
    monkeypatch.setattr(sc, "RETRY_AFTER_SECONDS", 0)
    assert service.load() is True and service.status == "ready" and len(attempts) == 2
    result = rs.compare_reports({"orig": ORIGINAL, "copy": COPIED}, service)
    assert result.semantic_status == "ok"


# ---- cited material: reference lists and cited quotations are cut out ------

OWN_A = ("I designed the lending module around a single Loan class that records the book, the member and the due "
         "date, and every change to a loan goes through one method so that the fines are always recalculated. "
         "The menu reads one option at a time and validates it before calling the module, which kept the main "
         "loop short. Testing showed that dates entered with slashes were rejected, so I accepted both forms. ") * 2
OWN_B = ("My solution keeps the books and members in two dictionaries that are saved to separate CSV files when "
         "the program exits. Borrowing checks the member's limit first and then the book's availability, and a "
         "returned book clears its due date. The hardest part was the report of overdue loans, which I sorted "
         "by the number of days late so the worst cases appear at the top of the list for the librarian. ") * 2
SHARED_REFERENCES = (" 9. References Python Software Foundation (2024). csv - CSV File Reading and Writing. "
                     "https://docs.python.org/3/library/csv.html Python Software Foundation (2024). datetime - "
                     "Basic date and time types. https://docs.python.org/3/library/datetime.html")


def test_a_shared_reference_list_no_longer_makes_reports_look_alike():
    a, b = OWN_A + SHARED_REFERENCES, OWN_B + SHARED_REFERENCES
    text, cut = rs.remove_cited_text(a)
    assert text == " ".join(OWN_A.split()) and cut == rs._word_count(SHARED_REFERENCES)
    result = rs.compare_reports({"1": a, "2": b})
    assert result.pairs[0].passages == [] and result.pairs[0].jaccard == 0.0
    assert result.cited_words_removed == {"1": cut, "2": cut}


def test_an_informal_short_reference_list_is_cut_too():
    informal = OWN_A + " References Python docs: enum, dataclasses and csv modules. Lecture notes: Week 6 - Classes."
    text, cut = rs.remove_cited_text(informal)
    assert text == " ".join(OWN_A.split()) and cut > 0


def test_the_table_of_contents_entry_is_not_the_reference_list():
    report = "Contents 1. Design 2. Testing 9. References " + OWN_A + SHARED_REFERENCES
    text, _ = rs.remove_cited_text(report)
    assert text.startswith("Contents 1. Design 2. Testing 9. References I designed")  # only the real list goes


def test_copied_prose_under_a_made_up_references_heading_is_kept():
    # a long section that doesn't read like a reference list (no URLs, years, DOIs)
    hidden = OWN_A + " References " + OWN_B
    assert rs.remove_cited_text(hidden) == (" ".join(hidden.split()), 0)
    # nor is a reference list that is most of the report
    assert rs.remove_cited_text("Intro text here. References " + SHARED_REFERENCES * 3)[1] == 0


def test_an_appendix_after_the_references_is_kept():
    report = OWN_A + SHARED_REFERENCES + " Appendix A Sample run of the program with three loans."
    text, _ = rs.remove_cited_text(report)
    assert text.endswith("Appendix A Sample run of the program with three loans.")
    assert "docs.python.org" not in text


def test_only_quotations_followed_by_a_citation_are_cut():
    cited = 'As the guide puts it, "a function should do one thing and do it well" (Martin, 2008), so I split it.'
    numbered = 'The standard says "dates must be written in the ISO format year month day" [3] and I followed it.'
    bare = 'My tutor said "write the tests before the code every single time" and I did.'
    short = 'It is "fast" (Smith, 2020).'
    assert rs.remove_cited_text(cited) == ("As the guide puts it, , so I split it.", 10)
    assert rs.remove_cited_text(numbered)[1] == 11
    assert rs.remove_cited_text(bare) == (bare, 0)          # no citation: could be copied text in quote marks
    assert rs.remove_cited_text(short) == (short, 0)        # too short to matter
