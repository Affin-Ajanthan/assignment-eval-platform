from app.evaluator.code_analysis import analyze_python
from app.evaluator.cross_modal import check_consistency
from app.evaluator.report_analysis import ReportContent, ReportAnalysis, score_text, check_images

CODE = """
def bubble_sort(items):
    \"\"\"Sort numbers ascending.\"\"\"
    return sorted(items)

def calculate_total_price(cart_items):
    return sum(cart_items)
"""


def _report(text: str) -> ReportAnalysis:
    content = ReportContent(text=text, image_count=0, unit_count=1, source_format="pdf")
    return ReportAnalysis(content=content, ai_text=score_text(text), image_check=check_images(content))


def test_consistency_high_when_report_mentions_code_terms():
    reports = [analyze_python(CODE, "solution.py")]
    report = _report("This report explains our bubble sort implementation and how we calculate the total price of the cart.")
    result = check_consistency(reports, report, video_transcript="")
    assert result.flagged is False
    assert result.report_ratio == 1.0


def test_consistency_flags_unrelated_report():
    reports = [analyze_python(CODE, "solution.py")]
    report = _report("This report is about a completely different topic: weather forecasting models and rainfall data.")
    result = check_consistency(reports, report, video_transcript="")
    assert result.flagged is True
    assert result.report_ratio == 0.0
    assert "bubble" in result.unmentioned_in_report or "sort" in result.unmentioned_in_report


def test_consistency_uses_video_transcript_too():
    reports = [analyze_python(CODE, "solution.py")]
    result = check_consistency(reports, None, video_transcript="today I will show my bubble sort and total price calculator")
    assert result.video_ratio > 0
    assert result.report_ratio is None  # no report text provided at all


def test_consistency_no_code_terms_is_neutral():
    result = check_consistency([], None, video_transcript="")
    assert result.consistency_score == 50
    assert result.flagged is False


def test_consistency_no_evidence_at_all_is_noted():
    reports = [analyze_python(CODE, "solution.py")]
    result = check_consistency(reports, None, video_transcript="")
    assert any("no report text or video transcript" in r for r in result.reasons)
