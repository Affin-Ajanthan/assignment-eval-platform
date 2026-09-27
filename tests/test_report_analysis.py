from app.evaluator.report_analysis import analyze_report, check_images, extract_report, score_text
from app.evaluator.report_analysis import ReportContent
from helpers import make_docx, make_pdf


def test_extract_pdf_text_and_images(tmp_path):
    pdf_path = make_pdf(
        tmp_path / "report.pdf",
        ["This report describes our sorting algorithm implementation.",
         "See Figure 1 and the screenshot below for the test results."],
        image_count=2,
    )
    content = extract_report(pdf_path)
    assert "sorting algorithm" in content.text
    assert content.image_count == 2
    assert content.source_format == "pdf"


def test_extract_docx_text_and_images(tmp_path):
    docx_path = make_docx(
        tmp_path / "report.docx",
        ["Our bubble sort implementation runs in quadratic time.",
         "The architecture diagram is attached below."],
        image_count=1,
    )
    content = extract_report(docx_path)
    assert "bubble sort" in content.text
    assert content.image_count == 1
    assert content.source_format == "docx"


def test_extract_plain_text_fallback(tmp_path):
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("Plain text report with no special format.")
    content = extract_report(txt_path)
    assert "Plain text report" in content.text
    assert content.image_count == 0


def test_score_text_flags_uniform_ai_style_prose():
    ai_like = " ".join([
        "In conclusion, this project demonstrates a robust solution.",
        "Furthermore, it is important to note the design choices made.",
        "Moreover, it is worth noting that the implementation is comprehensive.",
        "In summary, the system delivers a comprehensive comprehensive comprehensive result.",
        "Overall, it can be seen that the approach delivers a comprehensive result.",
        "It is essential to understand the comprehensive comprehensive design.",
    ])
    result = score_text(ai_like)
    assert result.score >= 34
    assert result.signal in {"medium", "high"}


def test_score_text_low_signal_for_varied_human_prose():
    human_like = (
        "I spent way too long debugging an off-by-one error in the loop before I found it. "
        "Turns out I forgot to decrement the index! Once fixed, sorting 10,000 items took about "
        "40ms on my laptop, which felt slow at first, but profiling showed the bottleneck was "
        "actually the print statements I'd left in for debugging, oops."
    )
    result = score_text(human_like)
    assert result.score < 67


def test_check_images_flags_missing_screenshots():
    content = ReportContent(
        text="See Figure 1 below. Also refer to the screenshot in Figure 2.",
        image_count=0, unit_count=1, source_format="pdf",
    )
    result = check_images(content)
    assert result.flagged is True


def test_check_images_flags_unexplained_images():
    content = ReportContent(text="No visuals discussed here at all, just prose.", image_count=4, unit_count=1, source_format="pdf")
    result = check_images(content)
    assert result.flagged is True


def test_check_images_ok_when_consistent():
    content = ReportContent(text="See Figure 1 for the results.", image_count=1, unit_count=1, source_format="pdf")
    result = check_images(content)
    assert result.flagged is False


def test_analyze_report_end_to_end(tmp_path):
    pdf_path = make_pdf(tmp_path / "r.pdf", ["A short report with no figures mentioned."], image_count=0)
    analysis = analyze_report(pdf_path)
    assert analysis.content.image_count == 0
    assert analysis.image_check.flagged is False
    assert analysis.ai_text.signal in {"low", "medium", "high"}
