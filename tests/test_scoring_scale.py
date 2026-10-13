"""Proportional scoring: the model reports check counts and the program computes
the score; static metrics don't decide code quality; files with no real logic
are flagged and capped."""

import json

import pytest

from app.evaluator import rubric_grading
from app.evaluator.code_analysis import analyze_python
from app.evaluator.rubric_grading import Criterion, Evidence, OllamaRubricGrader, _score_from_checks


class _SeqPost:
    """Returns each scripted reply in turn, as Ollama's /api/chat would."""

    def __init__(self, *criteria_lists):
        self.replies = list(criteria_lists)
        self.prompts = []

    def __call__(self, url, payload, timeout):
        self.prompts.append(payload["messages"][0]["content"])
        return {"message": {"content": json.dumps({"criteria": self.replies.pop(0)})}}


def _entry(name, total, met, partly=0, score=None):
    e = {"name": name, "checks_total": total, "checks_met": met, "checks_partly": partly,
         "justification": "checks"}
    if score is not None:
        e["score"] = score
    return e


# ---- the arithmetic -------------------------------------------------------


def test_score_is_proportional_to_checks_met():
    assert _score_from_checks({"checks_total": 4, "checks_met": 2}, 10) == pytest.approx(5.0)
    assert _score_from_checks({"checks_total": 4, "checks_met": 4}, 10) == pytest.approx(10.0)
    assert _score_from_checks({"checks_total": 4, "checks_met": 0, "checks_partly": 2}, 10) == pytest.approx(2.5)


def test_partly_met_counts_as_half_and_cannot_exceed_the_total():
    assert _score_from_checks({"checks_total": 4, "checks_met": 3, "checks_partly": 2}, 8) == pytest.approx(7.0)
    assert _score_from_checks({"checks_total": 2, "checks_met": 1, "checks_partly": 5}, 10) == pytest.approx(7.5)


def test_unusable_counts_return_none_so_the_plain_score_is_used():
    assert _score_from_checks({"checks_total": 0, "checks_met": 0}, 10) is None
    assert _score_from_checks({"checks_total": "three"}, 10) is None
    assert _score_from_checks({"score": 7}, 10) is None


def test_the_counts_decide_the_mark_and_a_stated_score_is_ignored():
    post = _SeqPost([_entry("Correctness", 4, 2, score=99)])
    result = OllamaRubricGrader(post=post).grade([Criterion("Correctness", "d", 10)], Evidence())
    assert result.criteria[0].score == pytest.approx(5.0)


def test_a_reply_with_only_a_score_still_works():
    post = _SeqPost([{"name": "Correctness", "score": 7, "justification": "ok"}])
    result = OllamaRubricGrader(post=post).grade([Criterion("Correctness", "d", 10)], Evidence())
    assert result.criteria[0].score == pytest.approx(7.0)


def test_missing_criteria_are_asked_for_again_not_scored_zero():
    post = _SeqPost(
        [_entry("Correctness", 2, 2)],                       # "Code quality" was left out
        [_entry("Code quality", 4, 1)],                      # the retry returns just the missing one
    )
    criteria = [Criterion("Correctness", "d", 10), Criterion("Code quality", "d", 8)]
    result = OllamaRubricGrader(post=post).grade(criteria, Evidence())
    assert len(post.prompts) == 2
    assert "left out these criteria: Code quality" in post.prompts[1]
    assert [c.score for c in result.criteria] == [pytest.approx(10.0), pytest.approx(2.0)]


# ---- the prompt -----------------------------------------------------------


def test_prompt_explains_the_scale_and_the_checks():
    prompt = rubric_grading._build_prompt([Criterion("X", "Checks a, b and c.", 10)], Evidence())
    assert "HOW TO SCORE EACH CRITERION" in prompt
    assert "Give full marks only when every check is met" in prompt
    assert "nothing attempted" in prompt


def test_prompt_does_not_show_the_static_quality_number():
    source = "def f(x):\n    return x + 1\n"
    evidence = Evidence(code_reports=[analyze_python(source, "a.py")], code_sources={"a.py": source})
    prompt = rubric_grading._build_prompt([Criterion("Code quality", "Readable", 5)], evidence)
    assert "quality score" not in prompt
    assert "/100" not in prompt
    assert "not evidence of readability" in prompt


# ---- files with no real logic ----------------------------------------------


@pytest.mark.parametrize("source", [
    "def main():\n    pass\n",
    "# only a comment\n\"\"\"and a docstring\"\"\"\n",
    "def read(path):\n    \"\"\"Doc.\"\"\"\n    pass\n\n\ndef main():\n    return None\n",
    "def main():\n    pass\n\n\nif __name__ == \"__main__\":\n    main()\n",
])
def test_files_with_no_real_logic_are_flagged_and_capped(source):
    report = analyze_python(source, "x.py")
    assert any("no real logic" in issue for issue in report.issues)
    assert report.quality_score <= 10


def test_a_real_program_is_not_flagged():
    source = (
        "def total(values):\n"
        "    result = 0\n"
        "    for v in values:\n"
        "        result += v\n"
        "    return result\n\n\n"
        "print(total([1, 2]))\n"
    )
    report = analyze_python(source, "x.py")
    assert not any("no real logic" in issue for issue in report.issues)
    assert report.quality_score > 50
