"""Language-mismatch review flag: video/report language vs. submitted code."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.evaluator.language_mismatch import (
    code_languages,
    language_mismatches,
    mentioned_languages,
)
from app.evaluator.pipeline import evaluate_submission
from app.evaluator.rubric_grading import Criterion, HeuristicRubricGrader

# Shaped like the real C# walkthrough transcript (Whisper's spelling).
CSHARP_VIDEO = (
    "Hi there, I'm excited to walk you through my custom-built C-Sharp.net Student Performance "
    "Management System. It reads student marks, calculates the average and grade, sorts the records "
    "and saves them to a file. I chose C sharp because of its strong typing."
)
GO_REPORT = (
    "This report describes the Student Performance System written in the Go programming language. "
    "Golang's slices keep the records and the sort package orders them."
)


def _code(tmp_path, *names):
    d = tmp_path / "code"
    d.mkdir()
    for name in names:
        (d / name).write_text("// student records\n", encoding="utf-8")
    return d


def test_detects_code_languages_by_extension(tmp_path):
    d = _code(tmp_path, "main.go", "student.go", "storage.go", "go.mod", "README.md")
    assert code_languages(d) == ["go"]
    assert code_languages(None) == []


def test_counts_whisper_spellings_of_csharp():
    assert mentioned_languages(CSHARP_VIDEO) == {"csharp": 2}
    assert mentioned_languages("Built with C# and .NET 8 (dotnet run).") == {"csharp": 3}


def test_ambiguous_english_words_do_not_count():
    text = "Let's go through the menu. We go back, and rust never sleeps; a swift sort."
    assert mentioned_languages(text) == {}
    assert mentioned_languages("JavaScript and Java script are not Java") == {"javascript": 2, "java": 1}


def test_csharp_video_with_go_php_ruby_code_is_flagged(tmp_path):
    for ext, name in ((".go", "Go"), (".php", "PHP"), (".rb", "Ruby")):
        d = tmp_path / ext.strip(".")
        d.mkdir()
        (d / f"main{ext}").write_text("x", encoding="utf-8")
        flags = [m.flag for m in language_mismatches(d, transcript=CSHARP_VIDEO, report_text=None)]
        assert len(flags) == 1, ext
        assert "video transcript talks about C# (2 mentions)" in flags[0]
        assert f"submitted code is {name}" in flags[0]


def test_matching_language_is_not_flagged(tmp_path):
    d = _code(tmp_path, "student_management.cs")
    assert language_mismatches(d, transcript=CSHARP_VIDEO, report_text=None) == []


def test_text_naming_the_code_language_too_is_not_flagged(tmp_path):
    d = _code(tmp_path, "main.go")
    report = "Unlike C# and .NET, which I used before, Golang has no classes; this is a Go language project."
    assert language_mismatches(d, transcript=None, report_text=report) == []


def test_single_passing_mention_is_not_flagged(tmp_path):
    d = _code(tmp_path, "main.go")
    assert language_mismatches(d, transcript="I first learned Java at school.", report_text=None) == []


def test_c_and_cpp_are_compatible(tmp_path):
    d = _code(tmp_path, "main.cpp", "util.h")
    text = "A C++ program; C++ classes keep the records."
    assert language_mismatches(d, transcript=text, report_text=text) == []


def test_no_code_or_no_mentions_means_no_flag(tmp_path):
    assert language_mismatches(None, transcript=CSHARP_VIDEO, report_text=None) == []
    d = _code(tmp_path, "main.go")
    assert language_mismatches(d, transcript="Student marks are sorted.", report_text="") == []


def test_report_mismatch_becomes_a_pipeline_review_flag(tmp_path):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "main.rb").write_text("# Student performance system\nputs 'hi'\n", encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text("# Report\n\n" + GO_REPORT + "\n", encoding="utf-8")
    result = evaluate_submission(
        code_dir=code_dir, report_path=report, video_path=None,
        criteria=[Criterion(name="Correctness", description="works", max_points=10)],
        grader=HeuristicRubricGrader(), ai_detection=False,
    )
    flags = [f for f in result.review_flags if f.startswith("language mismatch")]
    assert flags == ["language mismatch: the report talks about Go (2 mentions) but the submitted code is Ruby "
                     "-- check that the report belongs to this submission"]
    # a review signal only: marks still come from the grader
    assert result.recommended_score is not None
