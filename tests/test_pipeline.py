from app.evaluator.pipeline import evaluate_submission
from app.evaluator.rubric_grading import Criterion
from app.evaluator.video_analysis import Transcriber, TranscriptionResult
from helpers import make_pdf, make_two_scene_video

CODE = '''
def bubble_sort(items):
    """Sort numbers ascending using bubble sort."""
    n = len(items)
    for i in range(n):
        for j in range(0, n - i - 1):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
    return items
'''

CRITERIA = [
    Criterion(name="Correctness", description="Implements bubble sort correctly", max_points=60),
    Criterion(name="Report quality", description="Report clearly explains the bubble sort approach", max_points=25),
    Criterion(name="Academic integrity", description="Original, authentic work", max_points=15),
]


class _FakeTranscriber(Transcriber):
    def transcribe(self, video_path):
        return TranscriptionResult(
            text="today I will demo my bubble sort implementation",
            segments=[], backend="fake",
        )


def _make_code_dir(tmp_path):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "solution.py").write_text(CODE)
    return code_dir


def test_full_pipeline_end_to_end(tmp_path):
    code_dir = _make_code_dir(tmp_path)
    report_path = make_pdf(tmp_path / "report.pdf", ["This report explains our bubble sort implementation in detail."])
    video_path = make_two_scene_video(tmp_path / "demo.mp4", seg_seconds=1.0, fps=10)

    result = evaluate_submission(
        code_dir=code_dir,
        report_path=report_path,
        video_path=video_path,
        criteria=CRITERIA,
        transcriber=_FakeTranscriber(),
    )

    assert len(result.code_reports) == 1
    assert result.report_analysis is not None
    assert result.video_analysis is not None
    assert result.grading.grader == "heuristic"
    assert 0 <= result.recommended_score <= result.recommended_max
    # the report DOES mention bubble sort, so consistency should not be flagged
    assert result.consistency.flagged is False


def test_pipeline_flags_similarity_and_ai_content(tmp_path):
    code_dir = _make_code_dir(tmp_path)
    result = evaluate_submission(
        code_dir=code_dir,
        report_path=None,
        video_path=None,
        criteria=CRITERIA,
        similarity_flagged=True,
        code_ai_flagged=True,
    )
    assert result.needs_human_review is True
    assert any("similarity checker flagged" in f for f in result.review_flags)
    assert any("AI-content heuristic" in f for f in result.review_flags)
    # academic integrity criterion should be capped low given both flags
    integrity = next(c for c in result.grading.criteria if c.name == "Academic integrity")
    assert integrity.score <= 0.5 * integrity.max_points


def test_pipeline_partial_submission_notes_missing_parts(tmp_path):
    code_dir = _make_code_dir(tmp_path)
    result = evaluate_submission(code_dir=code_dir, report_path=None, video_path=None, criteria=CRITERIA)
    assert any("still missing" in f for f in result.review_flags)


def test_pipeline_handles_completely_empty_submission():
    result = evaluate_submission(code_dir=None, report_path=None, video_path=None, criteria=CRITERIA)
    assert result.code_reports == []
    assert result.report_analysis is None
    assert result.video_analysis is None
    assert result.grading.total_score >= 0
