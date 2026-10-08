"""
Tests for the Fast-DetectGPT report AI-text signal (app/evaluator/ai_text_detection.py).

Plumbing is tested with a fake scorer; one test marked ``slow`` runs the real
local model and skips when it can't be loaded.
"""

from __future__ import annotations

import pytest

from app.evaluator.ai_text_detection import (
    MIN_TOKENS,
    AITextDetector,
    DetectionResult,
    select_chunks,
    set_ai_text_detector,
    to_score,
)
from app.evaluator.pipeline import evaluate_submission
from app.evaluator.report_analysis import ai_text_signal, analyze_report
from app.evaluator.rubric_grading import Criterion

LONG_TEXT = " ".join(f"Sentence number {i} explains part of the design in plain words." for i in range(60))


class FakeScorer:
    name = "fake/Model-0.1B"

    def __init__(self, curvatures=(2.5,), fail=False):
        self.curvatures = list(curvatures)
        self.fail = fail
        self.calls = 0

    def token_count(self, text):
        return len(text.split())

    def chunk_curvatures(self, text, chunk_tokens, max_chunks):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated inference failure")
        return self.curvatures, len(text.split())


def _detector(scorer=None, **kw):
    scorer = scorer or FakeScorer()
    return AITextDetector(scorer_factory=lambda: scorer, enabled=True, **kw), scorer


@pytest.fixture
def installed():
    def install(detector):
        set_ai_text_detector(detector)
        return detector

    yield install
    set_ai_text_detector(None)


def test_chunks_cover_the_whole_document_evenly():
    ids = list(range(256 * 20))
    chunks = select_chunks(ids, 256, 8)
    assert len(chunks) == 8 and all(len(c) == 256 for c in chunks)
    starts = [c[0] for c in chunks]
    assert starts[0] == 0 and starts[-1] >= 256 * 17  # reaches the end, not just the start
    assert select_chunks(list(range(256 + 50)), 256, 8) == [list(range(256))]  # short tail dropped
    assert select_chunks(list(range(200)), 256, 8) == [list(range(200))]  # single short chunk kept


@pytest.mark.parametrize("curvature,signal", [(0.2, "low"), (1.4, "medium"), (2.0, "high"), (3.5, "high")])
def test_curvature_bands(curvature, signal):
    s = to_score(DetectionResult(curvature, 3, 900, "Qwen/Qwen2.5-0.5B", "ok"))
    assert s.signal == signal
    assert 0 <= s.score <= 100 and s.method == "fast-detectgpt:Qwen2.5-0.5B"
    assert "not proof" in s.reasons[0]


def test_thresholds_are_configurable(monkeypatch):
    monkeypatch.setenv("AI_TEXT_HIGH", "4.0")
    monkeypatch.setenv("AI_TEXT_MEDIUM", "3.0")
    assert to_score(DetectionResult(2.5, 1, 300, "m", "ok")).signal == "low"
    assert to_score(DetectionResult(3.2, 1, 300, "m", "ok")).signal == "medium"


def test_short_text_is_insufficient_not_high():
    detector, scorer = _detector(FakeScorer(curvatures=(9.0,)))
    result = detector.detect("Too short to judge.")
    assert result.status == "insufficient_text" and result.curvature is None and scorer.calls == 0
    s = to_score(result)
    assert s.signal == "low" and "too little text" in s.reasons[0]


def test_results_are_cached_and_model_loaded_once():
    created = []
    scorer = FakeScorer()
    detector = AITextDetector(scorer_factory=lambda: created.append(1) or scorer, enabled=True)
    first = detector.detect(LONG_TEXT)
    second = detector.detect(LONG_TEXT)
    assert first == second and first.status == "ok"
    assert len(created) == 1 and scorer.calls == 1


def test_failures_fall_back_to_the_style_heuristic(installed):
    def broken():
        raise OSError("model download failed")

    installed(AITextDetector(scorer_factory=broken, enabled=True))
    assert ai_text_signal(LONG_TEXT).method == "style-heuristic"

    installed(_detector(FakeScorer(fail=True))[0])
    assert ai_text_signal(LONG_TEXT).method == "style-heuristic"

    installed(AITextDetector(scorer_factory=lambda: FakeScorer(), enabled=False))
    assert ai_text_signal(LONG_TEXT).method == "style-heuristic"


def test_load_failure_is_not_retried_every_call():
    attempts = []

    def broken():
        attempts.append(1)
        raise OSError("offline")

    detector = AITextDetector(scorer_factory=broken, enabled=True)
    assert detector.detect(LONG_TEXT) is None and detector.detect(LONG_TEXT) is None
    assert len(attempts) == 1 and detector.status == "unavailable"


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("AI_TEXT_DETECTION", "0")
    created = []
    detector = AITextDetector(scorer_factory=lambda: created.append(1))
    assert detector.detect(LONG_TEXT) is None and not created


def test_off_by_default_and_opt_in(monkeypatch):
    monkeypatch.delenv("AI_TEXT_DETECTION", raising=False)
    assert AITextDetector(scorer_factory=lambda: FakeScorer()).enabled is False
    monkeypatch.setenv("AI_TEXT_DETECTION", "1")
    assert AITextDetector(scorer_factory=lambda: FakeScorer()).enabled is True


def test_ai_signals_never_lower_the_suggested_score(tmp_path, installed):
    integrity = [Criterion(name="Academic integrity", description="original, authentic work", max_points=20)]
    report = tmp_path / "report.md"
    report.write_text(LONG_TEXT)
    installed(AITextDetector(scorer_factory=lambda: FakeScorer(), enabled=False))
    baseline = evaluate_submission(report_path=report, criteria=integrity)

    installed(_detector(FakeScorer(curvatures=(4.0,)))[0])  # report AI signal: high
    flagged = evaluate_submission(report_path=report, criteria=integrity, code_ai_flagged=True)
    assert flagged.report_analysis.ai_text.signal == "high"
    assert any("not proof" in f for f in flagged.review_flags)
    assert any("AI-content heuristic" in f for f in flagged.review_flags)
    assert flagged.grading.criteria[0].score == baseline.grading.criteria[0].score


def test_report_analysis_and_pipeline_use_the_detector(tmp_path, installed):
    installed(_detector(FakeScorer(curvatures=(3.0, 2.6)))[0])
    report = tmp_path / "report.md"
    report.write_text(LONG_TEXT)
    analysis = analyze_report(report)
    assert analysis.ai_text.method == "fast-detectgpt:Model-0.1B" and analysis.ai_text.signal == "high"

    result = evaluate_submission(report_path=report, criteria=[Criterion(name="Report", max_points=10)])
    flag = next(f for f in result.review_flags if f.startswith("report AI-text signal is high"))
    assert "review recommended, not proof" in flag and "Fast-DetectGPT curvature 2.80" in flag


@pytest.mark.slow
def test_real_model_scores_ai_text_above_human_text():
    detector = AITextDetector(enabled=True)
    if not detector.load():
        pytest.skip(f"Fast-DetectGPT model unavailable: {detector.error}")
    ai_text = (
        "This report presents the design and implementation of a simple calculator program developed in Python. "
        "The primary objective of the project was to create an application capable of reading two integer inputs "
        "from the user and computing both their sum and their product. To achieve this, the program was structured "
        "into two modules: a calculator module containing the core arithmetic functions, and a main module "
        "responsible for handling user interaction. This modular approach improves readability, maintainability, "
        "and testability, as each component has a clearly defined responsibility. Testing was carried out by "
        "running the program with a variety of inputs, including positive numbers, negative numbers, and zero, to "
        "verify that the results were correct in all cases. Overall, the project successfully met its objectives "
        "and provided valuable experience in modular programming, function design, and basic input handling."
    )
    # Stand-in for human writing: informal, typo-laden student style. (It was
    # written for this test by an AI imitating a student -- it only checks
    # the ordering; real calibration needs genuine student reports.)
    human_text = (
        "ok so my calc thing. it reads 2 numbers (ints only!! floats crash it, didnt fix that, sorry) and spits out "
        "sum + product. split into calculator.py and main.py bc the lecturer said modules = marks lol. tested w/ "
        "3,4 -> 7 and 12 fine. 0 and -5 also fine. typed 'abc' once and it blew up with ValueError, so thats a "
        "known bug. took me like 2 hrs mostly cause i forgot int() and kept getting '34' instead of 7, classic. "
        "next time: input checking, maybe division but then theres the divide by zero mess to deal with which i "
        "really dont want to do at 2am again. also the README is 3 lines, will expand later, maybe, probably not."
    )
    assert len(human_text.split()) * 1.2 > MIN_TOKENS
    ai, human = detector.detect(ai_text), detector.detect(human_text)
    assert ai.status == human.status == "ok"
    assert ai.curvature > human.curvature


def test_auto_evaluate_returns_both_ai_signals_and_no_keyword_overlap_flag(tmp_path):
    import io

    from fastapi.testclient import TestClient

    from app.main import app
    from helpers import make_pdf
    from tests.auth_helpers import auth_headers, setup_subject_with_users, submit

    client = TestClient(app)
    subject, itok, stok = setup_subject_with_users(client)
    rubric = client.post("/rubrics", json={"name": "R", "subject_id": subject["id"],
                                           "criteria": [{"name": "Works", "max_points": 10}]},
                         headers=auth_headers(itok)).json()
    code = "def add(x, y):\n    return x + y\n\n\ndef multiply(x, y):\n    return x * y\n"
    # The report never names the functions, so the keyword-overlap check scores 0%.
    pdf = make_pdf(tmp_path / "r.pdf", ["This program reads two integers and prints their total and product."])
    sub = submit(client, subject["id"], "AI panel", {
        "code": ("calc.py", io.BytesIO(code.encode()), "text/x-python"),
        "report": ("r.pdf", io.BytesIO(pdf.read_bytes()), "application/pdf"),
    }, student_tok=stok).json()
    body = client.post(f"/submissions/{sub['id']}/auto-evaluate", json={"rubric_id": rubric["id"]},
                       headers=auth_headers(itok)).json()

    assert body["consistency_score"] == 0  # the keyword check still runs and is stored...
    assert not any("function/feature terms" in f for f in body["review_flags"])  # ...but adds no flag
    report_ai, code_ai = body["ai_signals"]["report"], body["ai_signals"]["code"]
    assert report_ai["signal"] in {"low", "medium", "high"} and report_ai["method"] == "style-heuristic"
    assert code_ai["signal"] in {"low", "medium", "high"} and code_ai["reasons"]
    stored = client.get(f"/submissions/{sub['id']}/auto-evaluate", headers=auth_headers(itok)).json()
    assert stored["ai_signals"] == body["ai_signals"]
