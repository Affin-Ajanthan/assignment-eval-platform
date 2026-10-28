"""A student's answers to a code challenge, one task at a time.

A challenge has one or more tasks (Assignment.questions: the pages say task, the API and the
database say question). The student hands them in one by one (POST /assignments/{id}/submit-code),
and each answer is final. They all go into the student's one submission for the assignment: every
answer is a file in its code folder (main.py for a challenge with a single task, q1.py, q2.rb, ...
for several) and is marked from its own tests as soon as it is handed in.

What the submission remembers about each answer is in Submission.question_results:

    [{"question": 1, "file": "q1.py", "language": "python", "marked": True,
      "earned": 3.0, "total": 5.0, "report": {...}}, ...]

`marked` is False for an answer whose tests could not be run yet (earned, total and report are
then None). `report` is what the student was shown after their code ran (student_report): the
counts, and expected vs actual output for a visible test that failed, never a hidden test.

The submission's own mark (Submission.test_earned / test_total) adds the tasks up: the points of
the tests passed, out of the points of ALL the tasks' tests. A task not handed in yet earns
nothing, but its points stay in the total.

A submission with no question_results was made before answers were kept one by one, or uploaded as
files. Its answers are worked out from its files (answers_of), and it cannot be added to.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .db import BASE_DIR
from .evaluator import code_testing
from .models import Assignment, Submission


def points_of(tests: list) -> float:
    """The points of every test in `tests`."""
    return round(sum(t.get("points", 1) for t in tests), 2)


def student_report(results: list, language: str) -> dict:
    """What a student may see of one question's run: how many test cases passed, and the expected and
    actual output of each VISIBLE test that failed. A HIDDEN test that failed is only counted: its name,
    input and expected output never leave the server. The keys are those of RunOut, bar `remaining_runs`."""
    failures: list[dict] = []
    visible_seen = hidden_failed = 0
    for r in results:
        if r.visible:
            visible_seen += 1
            if not r.passed:
                failures.append({"sample": visible_seen, "name": r.name, "status": r.status,
                                 "expected_output": r.expected_output, "actual_output": r.actual_output,
                                 "error": r.stderr})
        elif not r.passed:
            hidden_failed += 1  # counted, never described
    passed = sum(1 for r in results if r.passed)
    return {"language": language, "all_passed": passed == len(results), "passed": passed, "total": len(results),
            "hidden_failed": hidden_failed, "failures": failures}


def saved_file(assignment: Assignment, code_dir: Path, question: int) -> str:
    """The file of a saved submission that answers the question, relative to its code folder. "" when
    there is none or, for a challenge with a single question, when it cannot be told which file it is."""
    if len(assignment.questions) > 1:
        return code_testing.answer_file(code_dir, question)
    try:
        return code_testing.pick_main_file(code_dir, assignment.test_main_file or "")
    except code_testing.CodeTestError:
        return ""


def _answers_from_files(assignment: Assignment, submission: Submission) -> list[dict]:
    """The answers of a submission that has no question_results: a question is answered when its file is there."""
    code_dir = BASE_DIR / submission.code_path if submission.code_path else None
    if code_dir is None or not code_dir.is_dir():
        return []
    single = len(assignment.questions) == 1
    answers = []
    for q in assignment.questions:
        file = saved_file(assignment, code_dir, q["id"])
        if not file and not single:
            continue  # nothing was written for this question (a lone question is answered by whatever was uploaded)
        try:
            language = code_testing.language_of_file(file).id if file else None
        except code_testing.CodeTestError:
            language = None
        marked = submission.marked_by_tests
        # With one question the submission's mark is that question's. With several, how each did is not known.
        known = marked and single
        answers.append({"question": q["id"], "file": file, "language": language, "marked": marked,
                        "earned": submission.test_earned if known else None,
                        "total": submission.test_total if known else None, "report": None})
    return answers


def answers_of(assignment: Assignment, submission: Optional[Submission]) -> list[dict]:
    """The answers a submission holds, in question order: copies, safe to change. None: no submission yet."""
    if submission is None:
        return []
    if submission.question_results is None:
        return _answers_from_files(assignment, submission)
    return [dict(a) for a in sorted(submission.question_results, key=lambda a: a["question"])]


def answer_count(assignment: Assignment, submission: Submission) -> int:
    """How many questions the submission has an answer to."""
    if submission.question_results is None and len(assignment.questions) == 1:
        return 1 if submission.code_path else 0  # the one question: no need to look in the files
    return len(answers_of(assignment, submission))


def add_answer(assignment: Assignment, submission: Submission, question: int, file: str, language: str) -> None:
    """Remember that `file` was handed in as the answer to a question. It has no result yet."""
    answers = [a for a in answers_of(assignment, submission) if a["question"] != question]
    answers.append({"question": question, "file": file, "language": language, "marked": False,
                    "earned": None, "total": None, "report": None})
    submission.question_results = sorted(answers, key=lambda a: a["question"])


def record_runs(assignment: Assignment, submission: Submission, runs: list, *, now: datetime) -> None:
    """Save how the questions in `runs` (code_testing.QuestionRun) did on the submission, and its mark.

    A question that was not answered is left as it was. The mark is the points of the tests passed in
    every marked question, out of the points of all the questions' tests. The caller commits."""
    by_question = {a["question"]: a for a in answers_of(assignment, submission)}
    for run in runs:
        if not run.answered:
            continue
        mine = code_testing.score_run(run.results)
        before = by_question.get(run.question, {"question": run.question})
        by_question[run.question] = {
            **before, "file": run.file, "language": before.get("language") or run.language, "marked": True,
            "earned": mine.earned, "total": mine.total, "report": student_report(run.results, run.language)}
    answers = [by_question[q] for q in sorted(by_question)]
    submission.question_results = answers
    marked = [a for a in answers if a["marked"]]
    if marked:
        submission.test_earned = round(sum(a["earned"] or 0 for a in marked), 2)
        submission.test_total = points_of(assignment.test_cases or [])
        submission.tests_run_at = now
        submission.status = "graded"
