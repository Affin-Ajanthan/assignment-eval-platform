"""
Tests for scripts/calibrate_ai_text.py: the threshold metrics, and a full
run on small text files with a fake scorer (no model download needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.evaluator.ai_text_detection import AITextDetector, set_ai_text_detector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibrate_ai_text as cal  # noqa: E402


class FakeScorer:
    """Curvature comes from a ``score=<value>`` word in the text."""

    name = "fake/Model-0.1B"

    def __init__(self):
        self.calls = 0

    def token_count(self, text):
        return len(text.split())

    def chunk_curvatures(self, text, chunk_tokens, max_chunks):
        self.calls += 1
        value = next(float(w.split("=", 1)[1]) for w in text.split() if w.startswith("score="))
        return [value], len(text.split())


@pytest.fixture
def scorer():
    fake = FakeScorer()
    set_ai_text_detector(AITextDetector(scorer_factory=lambda: fake, enabled=True))
    yield fake
    set_ai_text_detector(None)


def _write_reports(folder: Path, scores: list[float], words: int = 150) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i, score in enumerate(scores):
        (folder / f"report_{i}.txt").write_text(f"score={score} " + "word " * words, encoding="utf-8")


def _dirs(tmp_path, human, ai):
    _write_reports(tmp_path / "human", human)
    _write_reports(tmp_path / "ai", ai)
    return ["--human", str(tmp_path / "human"), "--ai", str(tmp_path / "ai"), "--out", str(tmp_path / "out.csv")]


# ---- metrics ----------------------------------------------------------------

def test_flag_rate_counts_scores_at_or_above_the_threshold():
    assert cal.flag_rate([0.5, 1.0, 2.0, 3.0], 1.0) == 0.75
    assert cal.flag_rate([], 1.0) == 0.0


def test_auc_perfect_separation_and_chance():
    assert cal.auc([0.1, 0.2], [1.0, 2.0]) == 1.0
    assert cal.auc([1.0, 1.0], [1.0, 1.0]) == 0.5
    assert cal.auc([2.0], [1.0]) == 0.0
    assert cal.auc([], [1.0]) is None


def test_suggested_threshold_is_the_lowest_that_keeps_false_flags_under_the_limit():
    human = [0.5, 1.0, 1.5, 2.0]
    assert cal.suggest_threshold(human, 0.25) == 1.51  # only 2.0 flagged
    assert cal.suggest_threshold(human, 0.0) == 2.01  # nothing flagged
    assert cal.suggest_threshold(human, 1.0) == 0.51
    for limit in (0.0, 0.25, 0.5):
        assert cal.flag_rate(human, cal.suggest_threshold(human, limit)) <= limit
    assert cal.suggest_threshold([], 0.05) is None


def test_suggested_medium_is_never_above_high():
    rows = [cal.Row(f"h{i}", "human", "ok", float(i), 1, 200, "m", 0) for i in range(10)]
    s = cal.summarize(rows, high_fpr=0.05, medium_fpr=0.0)
    assert s["suggested"]["medium"]["threshold"] <= s["suggested"]["high"]["threshold"]


# ---- full run -----------------------------------------------------------------

def test_run_scores_every_report_and_prints_a_suggestion(tmp_path, scorer, capsys):
    args = _dirs(tmp_path, human=[-1.0, -0.5, 0.0, 0.5], ai=[1.5, 2.5, 3.0])
    assert cal.main(args) == 0
    rows = cal.load_rows(tmp_path / "out.csv")
    assert len(rows) == 7 and {r.status for r in rows} == {"ok"}
    assert sorted(r.curvature for r in rows if r.label == "ai") == [1.5, 2.5, 3.0]
    out = capsys.readouterr().out
    assert "AUC: 1.000" in out
    assert "AI_TEXT_MEDIUM=" in out and "AI_TEXT_HIGH=" in out
    assert "fewer than 20" in out  # small set is called out


def test_rerun_resumes_without_scoring_again(tmp_path, scorer):
    args = _dirs(tmp_path, human=[0.0, 0.5], ai=[2.0])
    cal.main(args)
    calls = scorer.calls
    _write_reports(tmp_path / "ai2", [3.0])
    (tmp_path / "ai2" / "report_0.txt").rename(tmp_path / "ai" / "extra.txt")
    cal.main(args)
    assert scorer.calls == calls + 1  # only the new file
    assert len(cal.load_rows(tmp_path / "out.csv")) == 4


def test_short_reports_are_recorded_but_left_out_of_the_metrics(tmp_path, scorer):
    args = _dirs(tmp_path, human=[0.0], ai=[2.0])
    (tmp_path / "human" / "short.txt").write_text("score=9.0 too short", encoding="utf-8")
    cal.main(args)
    rows = cal.load_rows(tmp_path / "out.csv")
    assert next(r for r in rows if Path(r.path).name == "short.txt").status == "insufficient_text"
    summary = cal.summarize(rows, 0.05, 0.2)
    assert (summary["human"], summary["ai"], summary["skipped"]) == (1, 1, 1)


def test_limit_scores_only_that_many_per_group(tmp_path, scorer):
    args = _dirs(tmp_path, human=[0.0, 0.1, 0.2], ai=[2.0, 2.1, 2.2])
    cal.main(args + ["--limit", "1"])
    rows = cal.load_rows(tmp_path / "out.csv")
    assert sorted(r.label for r in rows) == ["ai", "human"]


def test_unavailable_detector_stops_instead_of_calibrating_the_heuristic(tmp_path, capsys):
    def broken():
        raise OSError("model not downloaded")

    set_ai_text_detector(AITextDetector(scorer_factory=broken, enabled=True))
    try:
        assert cal.main(_dirs(tmp_path, human=[0.0], ai=[2.0])) == 1
    finally:
        set_ai_text_detector(None)
    assert "not available" in capsys.readouterr().err
    assert not (tmp_path / "out.csv").exists()
