"""
Tests for scripts/measure_ai_flags.py: low/medium/high counts on real
reports, from folders or the database, with a fake scorer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.evaluator.ai_text_detection import AITextDetector, set_ai_text_detector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import measure_ai_flags as flags  # noqa: E402
from calibrate_ai_text import Row  # noqa: E402


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


def _report(path: Path, score: float, words: int = 150) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"score={score} " + "word " * words, encoding="utf-8")
    return path


def _row(label, curvature, status="ok"):
    return Row(f"{label}-{curvature}", label, status, curvature, 1, 200, "m", 0)


def test_signal_uses_the_pipeline_banding():
    assert flags.signal(0.99, 1.0, 2.0) == "low"
    assert flags.signal(1.0, 1.0, 2.0) == "medium"
    assert flags.signal(2.0, 1.0, 2.0) == "high"


def test_summary_counts_per_group_and_lists_flagged_highest_first():
    rows = [_row("A1", 0.1), _row("A1", 1.5), _row("A1", 2.5), _row("A2", 0.2), _row("A2", None, "insufficient_text")]
    s = flags.summarize(rows, medium=1.0, high=2.0)
    assert s["total"] == {"low": 2, "medium": 1, "high": 1, "skipped": 1}
    assert s["groups"]["A1"] == {"low": 1, "medium": 1, "high": 1, "skipped": 0}
    assert s["groups"]["A2"]["skipped"] == 1
    assert [f[0] for f in s["flagged"]] == [2.5, 1.5]


def test_folder_run_prints_flag_rate(tmp_path, scorer, capsys):
    for i, score in enumerate([0.0, 0.5, 1.5, 2.5]):
        _report(tmp_path / "cohort" / f"r{i}.txt", score)
    assert flags.main(["--folder", str(tmp_path / "cohort"), "--out", str(tmp_path / "out.csv")]) == 0
    out = capsys.readouterr().out
    assert "4 scored" in out
    assert "50.0% of real reports would show a medium or high" in out
    assert "r3.txt" in out  # flagged reports are listed


def test_new_thresholds_rescore_nothing(tmp_path, scorer, capsys):
    for i, score in enumerate([0.0, 1.5, 2.5]):
        _report(tmp_path / "cohort" / f"r{i}.txt", score)
    args = ["--folder", str(tmp_path / "cohort"), "--out", str(tmp_path / "out.csv")]
    flags.main(args)
    calls = scorer.calls
    capsys.readouterr()
    # even with the model gone, cached scores are enough to try new thresholds
    set_ai_text_detector(AITextDetector(scorer_factory=lambda: (_ for _ in ()).throw(OSError("gone")),
                                        enabled=True))
    assert flags.main(args + ["--medium", "3", "--high", "4"]) == 0
    assert scorer.calls == calls
    assert "0.0% of real reports" in capsys.readouterr().out


def test_unavailable_detector_stops_when_reports_need_scoring(tmp_path, capsys):
    _report(tmp_path / "cohort" / "r0.txt", 1.0)
    set_ai_text_detector(AITextDetector(scorer_factory=lambda: (_ for _ in ()).throw(OSError("gone")),
                                        enabled=True))
    try:
        assert flags.main(["--folder", str(tmp_path / "cohort"), "--out", str(tmp_path / "out.csv")]) == 1
    finally:
        set_ai_text_detector(None)
    assert "not available" in capsys.readouterr().err


def test_database_mode_reads_submitted_reports_and_filters(tmp_path, scorer, capsys):
    from app.db import Base, SessionLocal, engine
    from app.models import Submission

    Base.metadata.create_all(bind=engine)
    subject_id = 987654  # not used by any other test
    with SessionLocal() as db:
        for i, (assignment, score) in enumerate([("Essay", 0.1), ("Essay", 2.5), ("Lab", 1.5)]):
            path = _report(tmp_path / "uploads" / f"s{i}" / "report.txt", score)
            db.add(Submission(student_id=1, subject_id=subject_id, assignment_name=assignment,
                              report_path=str(path)))
        db.add(Submission(student_id=1, subject_id=subject_id, assignment_name="Essay",
                          report_path=str(tmp_path / "missing.pdf")))  # file gone: ignored
        db.commit()

    found = flags.db_reports(subject_id=subject_id)
    assert len(found) == 3
    assert {group for _, group in found} == {f"subject {subject_id} / Essay", f"subject {subject_id} / Lab"}
    assert len(flags.db_reports(subject_id=subject_id, assignment="Lab")) == 1

    assert flags.main(["--subject-id", str(subject_id), "--assignment", "Essay",
                       "--out", str(tmp_path / "out.csv")]) == 0
    out = capsys.readouterr().out
    assert "2 scored" in out and "high   1" in out
