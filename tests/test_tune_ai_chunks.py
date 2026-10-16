"""
Tests for scripts/tune_ai_chunks.py: simulating AI_TEXT_MAX_CHUNKS settings
from per-chunk scores, with a fake scorer (no model download needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.evaluator.ai_text_detection import CHUNK_TOKENS, select_chunks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tune_ai_chunks as tune  # noqa: E402


class FakeScorer:
    """Every word is a number; a chunk's curvature is its first word."""

    def __init__(self):
        self.scored = 0

    def all_chunks(self, text, chunk_tokens):
        tokens = [float(w) for w in text.split()]
        return select_chunks(tokens, chunk_tokens, len(tokens) + 1)

    def score_chunks(self, chunks):
        self.scored += len(chunks)
        return [chunk[0] for chunk in chunks]


def _report(path: Path, chunk_scores: list[float]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(" ".join(" ".join([str(s)] * CHUNK_TOKENS) for s in chunk_scores), encoding="utf-8")
    return path


def _run(tmp_path, scorer, *extra):
    args = ["--folder", str(tmp_path / "reports"), "--out", str(tmp_path / "out.csv"), *extra]
    return tune.main(args, scorer_factory=lambda: scorer)


def test_picked_matches_the_detector_chunk_selection():
    assert tune.picked(10, 4) == [0, 2, 5, 7]
    assert tune.picked(3, 8) == [0, 1, 2]  # fewer chunks than the limit: all of them
    ids = list(range(10 * CHUNK_TOKENS))
    real = select_chunks(ids, CHUNK_TOKENS, 4)
    assert [c[0] // CHUNK_TOKENS for c in real] == tune.picked(10, 4)


def test_uniform_reports_suggest_the_fewest_chunks(tmp_path, capsys):
    scorer = FakeScorer()
    _report(tmp_path / "reports" / "a.txt", [0.5] * 12)
    _report(tmp_path / "reports" / "b.txt", [2.5] * 9)
    assert _run(tmp_path, scorer) == 0
    out = capsys.readouterr().out
    assert "Suggested: AI_TEXT_MAX_CHUNKS=2" in out
    assert "fewer than 20 reports" in out


def test_uneven_report_keeps_the_reference_when_fewer_chunks_change_the_level(tmp_path, capsys):
    scorer = FakeScorer()
    _report(tmp_path / "reports" / "a.txt", [3, 0, 0, 0, 3, 0, 0, 0])  # 8 chunks: mean 0.75 (low)
    assert _run(tmp_path, scorer) == 0
    reports = list(tune.load(tmp_path / "out.csv").values())
    s = tune.summarize(reports, [2, 3, 4, 6, 8], 8, medium=1.0, high=2.0, batch_size=30, tolerance=0.15)
    by = {row["max_chunks"]: row for row in s["rows"]}
    assert by[2]["signal_changes"] == 1 and by[2]["max_delta"] == 2.25  # chunks 0 and 4: mean 3.0
    assert by[8]["signal_changes"] == 0 and by[8]["mean_delta"] == 0
    assert s["suggestion"] == 8
    assert "Suggested: AI_TEXT_MAX_CHUNKS=8" in capsys.readouterr().out


def test_each_chunk_is_scored_once_and_reruns_resume(tmp_path):
    scorer = FakeScorer()
    _report(tmp_path / "reports" / "a.txt", [1.0] * 20)
    _run(tmp_path, scorer)
    union = {i for s in (2, 3, 4, 6, 8) for i in tune.picked(20, s)}
    assert scorer.scored == len(union) < 20  # shared chunks scored once, not per setting
    _run(tmp_path, scorer)
    assert scorer.scored == len(union)  # nothing new to score
    _run(tmp_path, scorer, "--chunks", "5")
    assert scorer.scored == len(union | set(tune.picked(20, 5)))  # only the missing chunks


def test_time_estimate_scales_with_chunks_used():
    report = tune.Report("a", "g", "m", "ok", total_chunks=16, scores={i: 0.0 for i in range(16)},
                         chunks_scored=10, seconds=50.0)  # 5 s per chunk
    s = tune.summarize([report], [2, 8], 8, 1.0, 2.0, batch_size=30, tolerance=0.15)
    assert s["seconds_per_chunk"] == 5.0
    assert [row["seconds_per_report"] for row in s["rows"]] == [10.0, 40.0]


def test_short_reports_are_skipped(tmp_path, capsys):
    scorer = FakeScorer()
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "short.txt").write_text("1.0 " * 50, encoding="utf-8")
    _report(tmp_path / "reports" / "ok.txt", [0.5] * 4)
    assert _run(tmp_path, scorer) == 0
    assert "1 report(s) scored (1 skipped" in capsys.readouterr().out


def test_model_load_failure_stops(tmp_path, capsys):
    _report(tmp_path / "reports" / "a.txt", [0.5] * 4)

    def broken():
        raise OSError("model not downloaded")

    args = ["--folder", str(tmp_path / "reports"), "--out", str(tmp_path / "out.csv")]
    assert tune.main(args, scorer_factory=broken) == 1
    assert "Could not load" in capsys.readouterr().err
