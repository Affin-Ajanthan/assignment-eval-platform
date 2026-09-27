from dataclasses import dataclass, field

import pytest

from app.evaluator.code_analysis import analyze_python
from app.evaluator.rubric_grading import (
    Criterion,
    Evidence,
    HeuristicRubricGrader,
    LLMRubricGrader,
    build_default_grader,
)

GOOD_CODE = """
def bubble_sort(items):
    \"\"\"Sort numbers in ascending order using bubble sort.\"\"\"
    n = len(items)
    for i in range(n):
        for j in range(0, n - i - 1):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
    return items
"""


def _evidence():
    report = analyze_python(GOOD_CODE, "solution.py")
    return Evidence(code_reports=[report], report=None, video_transcript="")


def test_heuristic_grader_scores_within_bounds():
    grader = HeuristicRubricGrader()
    criteria = [
        Criterion(name="Correctness", description="Implements bubble sort correctly", max_points=60),
        Criterion(name="Code quality", description="Clean, well-structured code", max_points=40),
    ]
    result = grader.grade(criteria, _evidence())
    assert result.grader == "heuristic"
    assert len(result.criteria) == 2
    for c in result.criteria:
        assert 0 <= c.score <= c.max_points
    assert result.total_score <= result.max_total


def test_heuristic_grader_matches_keywords_present_in_code():
    grader = HeuristicRubricGrader()
    criteria = [Criterion(name="Sorting", description="Implements a bubble sort function", max_points=10)]
    result = grader.grade(criteria, _evidence())
    # "bubble" and "sort" both appear in the function name -- should score well above zero.
    assert result.criteria[0].score >= 4


def test_heuristic_grader_caps_score_when_similarity_flagged():
    grader = HeuristicRubricGrader()
    criteria = [Criterion(name="Academic integrity", description="Original, authentic work", max_points=20)]
    evidence = Evidence(code_reports=[], similarity_flagged=True)
    result = grader.grade(criteria, evidence)
    assert result.criteria[0].score <= 6  # 0.3 * 20


def test_heuristic_grader_blends_code_quality_score():
    grader = HeuristicRubricGrader()
    criteria = [Criterion(name="Code quality", description="clean readable structure", max_points=10)]
    good_report = analyze_python(GOOD_CODE, "solution.py")
    evidence = Evidence(code_reports=[good_report])
    result = grader.grade(criteria, evidence)
    assert result.criteria[0].score >= 5  # good code (quality score 100/100) should score at least half


# --------------------------------------------------------------------------
# LLM grader -- tested with a fake client, no real network/API key needed.
# --------------------------------------------------------------------------


@dataclass
class _FakeToolUseBlock:
    input: dict
    type: str = "tool_use"


@dataclass
class _FakeResponse:
    content: list = field(default_factory=list)


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeResponse(content=[_FakeToolUseBlock(input=self._payload)])


class _FakeAnthropicClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def test_llm_grader_parses_tool_use_response():
    payload = {
        "criteria": [
            {"name": "Correctness", "score": 55, "justification": "Implements the algorithm correctly."},
            {"name": "Code quality", "score": 30, "justification": "Well documented."},
        ]
    }
    client = _FakeAnthropicClient(payload)
    grader = LLMRubricGrader(client=client)
    criteria = [
        Criterion(name="Correctness", description="", max_points=60),
        Criterion(name="Code quality", description="", max_points=40),
    ]
    result = grader.grade(criteria, _evidence())

    assert result.grader == "llm"
    assert result.criteria[0].score == 55
    assert result.criteria[1].score == 30
    assert client.messages.last_call_kwargs["tool_choice"]["name"] == "submit_grades"


def test_llm_grader_clamps_score_to_max_points():
    payload = {"criteria": [{"name": "Only", "score": 999, "justification": "way over"}]}
    client = _FakeAnthropicClient(payload)
    grader = LLMRubricGrader(client=client)
    result = grader.grade([Criterion(name="Only", max_points=10)], _evidence())
    assert result.criteria[0].score == 10


def test_llm_grader_handles_missing_criterion_in_response():
    payload = {"criteria": []}
    client = _FakeAnthropicClient(payload)
    grader = LLMRubricGrader(client=client)
    result = grader.grade([Criterion(name="Missing", max_points=10)], _evidence())
    assert result.criteria[0].score == 0.0
    assert "did not return" in result.criteria[0].justification


def test_llm_grader_without_client_raises_helpful_error():
    grader = LLMRubricGrader(client=None)
    with pytest.raises(RuntimeError, match="needs a client"):
        grader.grade([Criterion(name="X", max_points=10)], _evidence())


def test_build_default_grader_falls_back_to_heuristic_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    grader = build_default_grader()
    assert isinstance(grader, HeuristicRubricGrader)
