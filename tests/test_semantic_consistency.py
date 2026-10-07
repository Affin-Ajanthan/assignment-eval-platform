"""
Tests for cross-modal semantic consistency (app/evaluator/semantic_consistency.py):
code documentation <-> report <-> video transcript, compared by meaning.

- Fast, offline tests use a fake encoder and cover extraction, cleanup,
  chunking, missing components (missing data is never 0%), failures,
  caching, the pipeline, the API and a 50-student run.
- Tests marked ``slow`` load the real sentence-transformers/all-MiniLM-L6-v2
  model and check its behavior on tests/consistency_samples.py. They skip
  when the model can't be loaded (e.g. offline on first run).
"""

from __future__ import annotations

import io
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.evaluator.pipeline import evaluate_submission
from app.evaluator.rubric_grading import Criterion
from app.evaluator.semantic_consistency import (
    CHUNK_WORDS,
    DEFAULT_THRESHOLD,
    SentenceEmbeddingService,
    check_semantic_consistency,
    chunk_text,
    clean_text,
    consistency_threshold,
    extract_code_documentation,
    extract_documentation,
    set_consistency_service,
)
from app.evaluator.video_analysis import Transcriber, TranscriptionResult
from app.main import app
from consistency_samples import (
    LIBRARY_CODE,
    LIBRARY_REPORT,
    LIBRARY_REPORT_PARAPHRASED,
    LIBRARY_TRANSCRIPT,
    WEATHER_REPORT,
    WEATHER_TRANSCRIPT,
    long_text,
)
from helpers import make_pdf
from tests.auth_helpers import auth_headers, ensure_assignment, setup_subject_with_users, submit

client = TestClient(app)
LIBRARY_DOCS = extract_documentation(LIBRARY_CODE, "library.py")
BANNED = ("plagiar", "cheat", "ai generated", "ai-generated", "misconduct detected", "proof")


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeEncoder:
    """Hashed bag-of-words vectors: shared vocabulary -> high cosine.
    Records how many texts it was asked to encode."""

    def __init__(self, dim: int = 256, fail: bool = False, bad_output: bool = False):
        self.dim = dim
        self.fail = fail
        self.bad_output = bad_output
        self.calls: list[int] = []
        self.texts: list[str] = []

    def encode(self, texts):
        self.calls.append(len(texts))
        self.texts.extend(texts)
        if self.fail:
            raise RuntimeError("simulated inference failure")
        out = np.zeros((len(texts), self.dim))
        for i, text in enumerate(texts):
            for w in text.lower().split():
                out[i, zlib.crc32(w.strip(".,").encode()) % self.dim] += 1
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
        if self.bad_output:
            out[:] = np.nan
        return out


def _service(encoder=None, **kwargs) -> SentenceEmbeddingService:
    encoder = encoder or FakeEncoder()
    return SentenceEmbeddingService(encoder_factory=lambda: encoder, enabled=True, **kwargs)


def _check(service, code=LIBRARY_DOCS, report=LIBRARY_REPORT, transcript=LIBRARY_TRANSCRIPT, **kwargs):
    return check_semantic_consistency(code_documentation=code, report_text=report, transcript=transcript,
                                      service=service, **kwargs)


def _no_banned_words(*texts: str | None) -> bool:
    joined = " ".join(t for t in texts if t).lower()
    return not any(b in joined for b in BANNED)


# --------------------------------------------------------------------------
# Code documentation extraction
# --------------------------------------------------------------------------


def test_python_docstrings_and_comments_are_extracted_but_code_is_not():
    docs = LIBRARY_DOCS
    assert "Lend a book to a member and return the date it is due back" in docs
    assert "fine is 50 cents per day late" in docs  # a # comment
    assert "already borrowed" not in docs  # an ordinary string literal, not documentation
    assert "def " not in docs and "self.loans" not in docs and "timedelta" not in docs


def test_c_family_comments_are_extracted_and_strings_ignored():
    java = '''
    /**
     * Computes the shipping cost for an order.
     * @param weight parcel weight in kilograms
     */
    double cost(double weight) {
        String url = "http://example.com/rates"; // look up the regional rate table
        // return weight * rate;
        return weight * 2.5;
    }
    '''
    docs = extract_documentation(java, "Shipping.java")
    assert "Computes the shipping cost for an order" in docs
    assert "parcel weight in kilograms" in docs
    assert "look up the regional rate table" in docs
    assert "example.com" not in docs  # inside a string literal
    assert "return weight * rate" not in docs  # commented-out code is dropped


def test_js_and_typescript_comments_are_extracted():
    js = "// Debounce user input so the search box doesn't fire on every keystroke\nconst x = 1; /* wait 300 ms between calls */"
    docs = extract_documentation(js, "search.ts")
    assert "Debounce user input" in docs and "wait 300 ms between calls" in docs


def test_boilerplate_comments_are_dropped():
    src = (
        "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n# Copyright (c) 2026 Some University\n"
        "# pylint: disable=invalid-name\n# ------------------------------\n"
        "# TODO: validate the student number before saving\nx = 1  # noqa: E501\n"
    )
    docs = extract_documentation(src, "a.py")
    assert docs == "validate the student number before saving"


def test_unparsable_python_still_yields_comments():
    docs = extract_documentation("def broken(:\n    # explains the sorting strategy here\n", "a.py")
    assert "explains the sorting strategy here" in docs


def test_code_directory_documentation_spans_all_files(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""Parses the uploaded timetable file."""\n')
    (tmp_path / "b.js").write_text("// Renders the weekly timetable grid\n")
    (tmp_path / "notes.txt").write_text("not source code at all")
    docs = extract_code_documentation(tmp_path)
    assert "Parses the uploaded timetable file" in docs and "Renders the weekly timetable grid" in docs
    assert "not source code" not in docs


# --------------------------------------------------------------------------
# Cleanup + chunking
# --------------------------------------------------------------------------


def test_clean_text_drops_page_numbers_headers_and_toc_but_keeps_content():
    pages = "\n".join(
        f"CS101 Project Report\nThe parser handles nested brackets in part {i}.\nPage {i} of 4" for i in range(1, 5)
    )
    toc = "Table of Contents\n1. Introduction ........ 3\n"
    cleaned = clean_text(toc + pages + "\nimple-\nmentation details")
    assert "CS101 Project Report" not in cleaned  # repeated running header
    assert "Page 2 of 4" not in cleaned and "........" not in cleaned
    assert "The parser handles nested brackets in part 3." in cleaned
    assert "implementation details" in cleaned  # hyphenation rejoined
    assert "  " not in cleaned


def test_repeated_sentences_are_content_not_headers():
    text = "\n".join(["The fine is capped at twenty dollars."] * 5 + ["Results"] * 5)
    cleaned = clean_text(text)
    assert cleaned.count("The fine is capped at twenty dollars.") == 5
    assert "Results" not in cleaned  # short heading-like line repeated: running header


def test_long_text_is_chunked_without_losing_any_words():
    text = clean_text(long_text(LIBRARY_REPORT, sections=30))
    chunks = chunk_text(text)
    assert len(chunks) > 10
    assert all(len(c.split()) <= CHUNK_WORDS for c in chunks)
    assert " ".join(chunks).split() == text.split()  # full coverage, in order


def test_overlong_sentence_is_split_on_word_boundaries():
    sentence = " ".join(f"w{i}" for i in range(CHUNK_WORDS * 2 + 7))
    chunks = chunk_text(sentence)
    assert [len(c.split()) for c in chunks] == [CHUNK_WORDS, CHUNK_WORDS, 7]


# --------------------------------------------------------------------------
# Missing components: unavailable, never 0%
# --------------------------------------------------------------------------


def test_missing_report_is_null_not_zero_and_overall_uses_only_available_pair():
    r = _check(_service(), report=None, report_submitted=False)
    assert r.code_report is None and r.report_transcript is None
    assert r.code_transcript is not None
    assert r.overall == r.code_transcript
    assert r.components["report"].available is False
    assert r.components["report"].note == "Report not submitted"
    assert r.status in {"limited_data", "review_recommended"}


def test_missing_transcript_reports_why():
    no_video = _check(_service(), transcript=None, video_submitted=False)
    assert no_video.code_transcript is None and no_video.report_transcript is None
    assert no_video.components["transcript"].note == "No video submitted"

    no_stt = _check(_service(), transcript="", video_submitted=True, transcript_backend="null")
    assert no_stt.components["transcript"].note == "Transcript unavailable (speech-to-text not configured)"

    silent = _check(_service(), transcript="", video_submitted=True, transcript_backend="faster-whisper-tiny")
    assert silent.components["transcript"].note == "Transcript unavailable (no speech detected)"


def test_code_without_documentation_is_unavailable_not_zero():
    docs = extract_documentation("def add(a, b):\n    return a + b\n", "calc.py")
    r = _check(_service(), code=docs)
    assert docs == ""
    assert r.code_report is None and r.code_transcript is None
    assert r.components["code"].note == "No code documentation found"
    assert r.report_transcript is not None and r.overall == r.report_transcript


def test_empty_or_tiny_text_everywhere_is_limited_data_and_never_loads_the_model():
    created = []
    service = SentenceEmbeddingService(encoder_factory=lambda: created.append(1) or FakeEncoder(), enabled=True)
    r = _check(service, code="", report="   \n ", transcript="ok bye")
    assert r.status == "limited_data"
    assert r.overall is None and r.code_report is None and r.code_transcript is None and r.report_transcript is None
    assert "too little to compare" in r.components["transcript"].note
    assert "not a low score" in r.reason
    assert not created  # nothing to compare -> no model work at all


def test_one_component_alone_is_never_flagged():
    r = _check(_service(), report=None, transcript=None, report_submitted=False, video_submitted=False)
    assert r.status == "limited_data" and r.overall is None


def test_missing_data_serializes_as_null():
    d = _check(_service(), report=None, report_submitted=False).to_dict()
    assert d["code_report"] is None and d["report_transcript"] is None
    assert d["code_report"] != 0


# --------------------------------------------------------------------------
# Status, reason wording, threshold
# --------------------------------------------------------------------------


def test_consistent_components_are_marked_consistent():
    r = _check(_service(), code="library loans books due dates fines members",
               report="library loans books due dates fines members borrow",
               transcript="library loans books due dates fines members return")
    assert r.status == "consistent" and r.overall >= DEFAULT_THRESHOLD
    assert _no_banned_words(r.reason)


def test_inconsistent_component_gets_review_recommended_with_the_odd_one_named():
    r = _check(_service(), code="library loans books due dates fines members",
               report="weather station sensors rainfall humidity temperature dashboard",
               transcript="library loans books due dates fines members borrow")
    assert r.status == "review_recommended"
    assert "report shows limited semantic overlap with the code documentation and video transcript" in r.reason
    assert "Review recommended" in r.reason
    assert _no_banned_words(r.reason)


def test_threshold_is_configurable(monkeypatch):
    assert consistency_threshold() == DEFAULT_THRESHOLD
    monkeypatch.setenv("CROSS_MODAL_CONSISTENCY_THRESHOLD", "0.9")
    assert consistency_threshold() == 0.9
    r = _check(_service(), code="library loans books due dates fines members",
               report="library loans books due dates fines members borrow",
               transcript="library loans books return dates penalty")
    assert r.threshold == 0.9
    monkeypatch.setenv("CROSS_MODAL_CONSISTENCY_THRESHOLD", "not-a-number")
    assert consistency_threshold() == DEFAULT_THRESHOLD


# --------------------------------------------------------------------------
# Failures, disabling, caching, loading once
# --------------------------------------------------------------------------


def test_model_load_failure_returns_unavailable_without_scores():
    def broken():
        raise OSError("couldn't download all-MiniLM-L6-v2")

    r = _check(SentenceEmbeddingService(encoder_factory=broken, enabled=True))
    assert r.status == "unavailable"
    assert "could not be loaded" in r.warning and "all-MiniLM-L6-v2" in r.warning
    assert r.overall is None and r.code_report is None


def test_inference_failure_returns_unavailable_without_a_false_score():
    r = _check(_service(FakeEncoder(fail=True)))
    assert r.status == "unavailable" and r.overall is None and "Embedding failed" in r.warning


def test_malformed_model_output_is_treated_as_failure():
    r = _check(_service(FakeEncoder(bad_output=True)))
    assert r.status == "unavailable" and r.overall is None


def test_feature_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CROSS_MODAL_SEMANTIC", "0")
    created = []
    service = SentenceEmbeddingService(encoder_factory=lambda: created.append(1))
    r = _check(service)
    assert r.status == "disabled" and r.overall is None and not created


def test_cached_embeddings_are_reused():
    encoder = FakeEncoder()
    service = _service(encoder)
    first = _check(service)
    encoded_first = sum(encoder.calls)
    assert encoded_first > 0
    second = _check(service)
    assert sum(encoder.calls) == encoded_first  # nothing re-encoded
    assert service.cache_hits >= encoded_first
    assert (first.code_report, first.overall) == (second.code_report, second.overall)

    # A new report that shares nothing with earlier text only encodes its own chunks.
    _check(service, report=WEATHER_REPORT)
    assert sum(encoder.calls) == encoded_first + len(chunk_text(clean_text(WEATHER_REPORT)))


def test_model_is_loaded_once_across_many_checks():
    created = []

    def factory():
        created.append(1)
        return FakeEncoder()

    service = SentenceEmbeddingService(encoder_factory=factory, enabled=True)
    for _ in range(5):
        _check(service)
    assert len(created) == 1


def test_fifty_students_one_model_load_and_bounded_encoding():
    encoder = FakeEncoder()
    created = []
    service = SentenceEmbeddingService(encoder_factory=lambda: created.append(1) or encoder, enabled=True)
    started = time.perf_counter()
    results = [
        _check(service, report=LIBRARY_REPORT + f"\nStudent {i} added a reservation queue.",
               transcript=LIBRARY_TRANSCRIPT + f" this is student number {i}.")
        for i in range(50)
    ]
    assert time.perf_counter() - started < 10
    assert len(created) == 1
    assert all(r.status in {"consistent", "review_recommended"} for r in results)
    # The shared code-docs chunks are encoded once, not 50 times.
    assert encoder.texts.count(clean_text(LIBRARY_DOCS)) == 1


# --------------------------------------------------------------------------
# Pipeline + API
# --------------------------------------------------------------------------


class _Transcriber(Transcriber):
    def __init__(self, text):
        self.text = text

    def transcribe(self, video_path):
        return TranscriptionResult(text=self.text, segments=[], backend="fake")


CRITERIA = [
    Criterion(name="Correctness", description="Library loans and fines work", max_points=70),
    Criterion(name="Academic integrity", description="Original, authentic work", max_points=30),
]


def _code_dir(tmp_path):
    d = tmp_path / "code"
    d.mkdir()
    (d / "library.py").write_text(LIBRARY_CODE)
    return d


def test_pipeline_reuses_extracted_report_text_and_low_consistency_never_changes_grades(tmp_path):
    report = make_pdf(tmp_path / "report.pdf", WEATHER_REPORT.strip().split("\n\n"))
    kwargs = dict(code_dir=_code_dir(tmp_path), report_path=report, criteria=CRITERIA)

    flagged = evaluate_submission(**kwargs, consistency_service=_service())
    baseline = evaluate_submission(**kwargs, consistency_service=SentenceEmbeddingService(enabled=False))

    sc = flagged.semantic_consistency
    assert sc.status == "review_recommended"
    assert sc.code_report is not None and sc.code_transcript is None
    assert sc.components["transcript"].note == "No video submitted"
    assert any(f.startswith("cross-modal semantic consistency:") for f in flagged.review_flags)
    # A review signal only: identical grading with the feature on or off.
    assert [(c.name, c.score) for c in flagged.grading.criteria] == \
           [(c.name, c.score) for c in baseline.grading.criteria]
    assert _no_banned_words(*flagged.review_flags[-1:], sc.reason)


def test_pipeline_survives_model_failure(tmp_path):
    report = make_pdf(tmp_path / "report.pdf", LIBRARY_REPORT.strip().split("\n\n"))

    def broken():
        raise ImportError("No module named 'sentence_transformers'")

    result = evaluate_submission(code_dir=_code_dir(tmp_path), report_path=report, criteria=CRITERIA,
                                 consistency_service=SentenceEmbeddingService(encoder_factory=broken, enabled=True))
    assert result.semantic_consistency.status == "unavailable"
    assert result.grading.criteria and 0 <= result.recommended_score <= result.recommended_max


@pytest.fixture
def injected_service():
    def install(service):
        set_consistency_service(service)
        return service

    yield install
    set_consistency_service(None)


def _pdf_bytes(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        return make_pdf(Path(d) / "r.pdf", text.strip().split("\n\n")).read_bytes()


def _auto_evaluate(code: str, report: tuple[str, str] | None = None):
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    rubric = client.post("/rubrics", json={"name": "R", "subject_id": subject["id"],
                                           "criteria": [{"name": "Correctness", "max_points": 10}]},
                         headers=auth_headers(instructor_tok)).json()
    files = {"code": ("library.py", io.BytesIO(code.encode()), "text/plain")}
    if report:
        files["report"] = (report[0], io.BytesIO(_pdf_bytes(report[1])), "application/pdf")
    sub = submit(client, subject["id"], "Consistency", files, student_tok=student_tok).json()
    r = client.post(f"/submissions/{sub['id']}/auto-evaluate", json={"rubric_id": rubric["id"]},
                    headers=auth_headers(instructor_tok))
    assert r.status_code == 200, r.text
    stored = client.get(f"/submissions/{sub['id']}/auto-evaluate", headers=auth_headers(instructor_tok)).json()
    return r.json(), stored


def test_api_returns_and_stores_cross_modal_consistency(injected_service):
    injected_service(_service())
    body, stored = _auto_evaluate(LIBRARY_CODE, ("report.pdf", LIBRARY_REPORT))
    cmc = body["cross_modal_consistency"]
    assert set(cmc) >= {"code_report", "code_transcript", "report_transcript", "overall", "status", "reason",
                        "threshold", "model", "components"}
    assert cmc["code_report"] is not None
    assert cmc["code_transcript"] is None and cmc["report_transcript"] is None  # no video -> null, not 0
    assert cmc["components"]["transcript"] == {"available": False, "words": 0, "chunks": 0,
                                               "note": "No video submitted"}
    assert cmc["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert stored["cross_modal_consistency"] == cmc


def test_api_reports_disabled_without_breaking_evaluation():
    body, _ = _auto_evaluate(LIBRARY_CODE, ("report.pdf", LIBRARY_REPORT))  # conftest disables it
    assert body["cross_modal_consistency"]["status"] == "disabled"
    assert body["cross_modal_consistency"]["overall"] is None
    assert body["recommended_max"] == 10


# --------------------------------------------------------------------------
# Real model (slow; skips if it can't be loaded)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def minilm():
    service = SentenceEmbeddingService(enabled=True)
    if not service.load():
        pytest.skip(f"all-MiniLM-L6-v2 unavailable: {service.error}")
    return service


@pytest.mark.slow
def test_real_similar_code_documentation_and_report(minilm):
    r = _check(minilm)
    assert r.code_report >= 0.6
    assert r.status == "consistent"


@pytest.mark.slow
def test_real_different_wording_same_meaning(minilm):
    # Little shared vocabulary, same content: semantic score stays high.
    a = set(clean_text(LIBRARY_REPORT).lower().split())
    b = set(clean_text(LIBRARY_REPORT_PARAPHRASED).lower().split())
    assert len(a & b) / len(a | b) < 0.25
    r = _check(minilm, report=LIBRARY_REPORT_PARAPHRASED)
    assert r.code_report >= DEFAULT_THRESHOLD
    unrelated = _check(minilm, report=WEATHER_REPORT)
    assert r.code_report > unrelated.code_report + 0.4


@pytest.mark.slow
def test_real_unrelated_report_and_code_documentation(minilm):
    r = _check(minilm, report=WEATHER_REPORT)
    assert r.code_report < 0.25
    assert r.status == "review_recommended"
    assert "report" in r.reason and _no_banned_words(r.reason)


@pytest.mark.slow
def test_real_similar_report_and_transcript(minilm):
    r = _check(minilm, code=None, code_submitted=False)
    assert r.report_transcript >= 0.6
    weather = _check(minilm, code=None, code_submitted=False, report=WEATHER_REPORT, transcript=WEATHER_TRANSCRIPT)
    assert weather.report_transcript >= 0.6


@pytest.mark.slow
def test_real_long_report_is_fully_covered(minilm):
    # 20 sections about the weather project, then the library content at the
    # very end: if the report were truncated to its first part, the ending
    # couldn't move the score.
    weather_only = long_text(WEATHER_REPORT, sections=20)
    with_library_at_end = weather_only + "\n\n" + long_text(LIBRARY_REPORT, sections=8)
    a = _check(minilm, report=weather_only, transcript=None, video_submitted=False)
    b = _check(minilm, report=with_library_at_end, transcript=None, video_submitted=False)
    assert b.components["report"].chunks > 10
    assert b.code_report > a.code_report + 0.15


@pytest.mark.slow
def test_real_long_transcript_is_fully_covered(minilm):
    long_tx = long_text(LIBRARY_TRANSCRIPT, sections=30)
    r = _check(minilm, transcript=long_tx)
    assert r.components["transcript"].words > 500 and r.components["transcript"].chunks >= 4
    assert r.code_transcript >= 0.6 and r.status == "consistent"


@pytest.mark.slow
def test_real_fifty_students_performance(minilm):
    started = time.perf_counter()
    results = []
    for i in range(50):
        report = LIBRARY_REPORT if i % 5 else WEATHER_REPORT
        results.append(_check(minilm, report=report + f"\nAppendix: test log for student {i}.",
                              transcript=LIBRARY_TRANSCRIPT + f" I am student {i}."))
    elapsed = time.perf_counter() - started
    assert elapsed < 60, f"50 students took {elapsed:.1f}s"
    flagged = [i for i, r in enumerate(results) if r.status == "review_recommended"]
    assert flagged == [i for i in range(50) if i % 5 == 0]  # exactly the mismatched reports
