"""The bookkeeping of a student's answers to a code challenge (app/code_answers.py): what a student may be
shown of a run, and how the submission's mark follows the answers handed in. No code is run and no
database is needed. The routes that use it are tested in test_student_runs.py."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import code_answers
from app.evaluator import code_testing as ct
from app.models import Assignment, Submission

NOW = datetime(2026, 10, 28, 12, 0)
QUESTIONS = [{"id": 1, "title": "One", "statement": ""}, {"id": 2, "title": "Two", "statement": ""}]
# Question 1 has two tests (2 + 1.5 points), question 2 has one (4 points): 7.5 points in all.
TESTS = [{"id": 1, "name": "a", "points": 2, "question": 1}, {"id": 2, "name": "b", "points": 1.5, "question": 1},
         {"id": 3, "name": "c", "points": 4, "question": 2}]


def _result(test_id, question, passed, *, visible=True, points=1, name="t", actual="", stderr=""):
    return ct.TestResult(test_id=test_id, name=name, visible=visible, points=points, match="exact",
                         status="passed" if passed else "failed", passed=passed, expected_output="want",
                         actual_output=actual, stderr=stderr, question=question)


def _run(question, results, *, answered=True, file=None):
    return ct.QuestionRun(question, QUESTIONS[question - 1]["title"], answered, file or f"q{question}.py", "python",
                          results)


def _challenge():
    return Assignment(assignment_type="code_challenge", test_cases=TESTS, code_questions=QUESTIONS)


def _first_marked(assignment=None):
    """A submission with both questions handed in; question 1 passed test 1 only, question 2 passed."""
    assignment = assignment or _challenge()
    submission = Submission(question_results=[])
    code_answers.add_answer(assignment, submission, 1, "q1.py", "python")
    code_answers.add_answer(assignment, submission, 2, "q2.py", "python")
    code_answers.record_runs(assignment, submission, [
        _run(1, [_result(1, 1, True, points=2), _result(2, 1, False, points=1.5)]),
        _run(2, [_result(3, 2, True, points=4)])], now=NOW)
    return assignment, submission


def test_a_report_counts_hidden_failures_and_describes_only_visible_ones():
    report = code_answers.student_report([
        _result(1, 1, True, name="seen and fine"),
        _result(2, 1, False, name="seen and wrong", actual="42", stderr="oops"),
        _result(3, 1, False, visible=False, name="SECRET-NAME", actual="SECRET-OUT")], "python")
    assert report == {
        "language": "python", "all_passed": False, "passed": 1, "total": 3, "hidden_failed": 1,
        "failures": [{"sample": 2, "name": "seen and wrong", "status": "failed", "input": "",
                      "expected_output": "want",
                      "actual_output": "42", "error": ""}]}  # a wrong answer shows expected vs actual, not stderr
    assert "SECRET" not in json.dumps(report)                         # a hidden test is only counted

    everything = code_answers.student_report([_result(1, 1, True), _result(2, 1, True, visible=False)], "ruby")
    assert (everything["all_passed"], everything["failures"], everything["hidden_failed"]) == (True, [], 0)


def test_a_wrong_answer_shows_its_input_expected_and_actual_but_a_hidden_input_never_leaves():
    def result(name, visible, status, stderr=""):
        return ct.TestResult(test_id=1, name=name, visible=visible, points=1, match="exact", status=status,
                             passed=False, expected_output="want", actual_output="got", stderr=stderr,
                             input=f"input of {name}")

    report = code_answers.student_report([
        result("shown wrong", True, "failed"), result("shown crash", True, "error", 'File "/run/main.py", line 7'),
        result("hidden", False, "failed")], "python")
    wrong, crash = report["failures"]
    assert (wrong["input"], wrong["expected_output"], wrong["actual_output"], wrong["error"]) == (
        "input of shown wrong", "want", "got", "")
    assert (crash["status"], crash["error"]) == ("error", "Compiler error. Error on line 7.")
    assert "input of hidden" not in json.dumps(report) and report["hidden_failed"] == 1


def test_an_answer_handed_in_is_remembered_in_question_order_without_a_result():
    assignment, submission = _challenge(), Submission(question_results=[])
    code_answers.add_answer(assignment, submission, 2, "q2.rb", "ruby")
    code_answers.add_answer(assignment, submission, 1, "q1.py", "python")
    assert submission.question_results == [
        {"question": 1, "file": "q1.py", "language": "python", "marked": False, "earned": None, "total": None, "report": None},
        {"question": 2, "file": "q2.rb", "language": "ruby", "marked": False, "earned": None, "total": None, "report": None}]
    assert code_answers.answer_count(assignment, submission) == 2
    assert code_answers.answers_of(assignment, None) == []

    copy = code_answers.answers_of(assignment, submission)
    copy[0]["file"] = "changed.py"
    assert submission.question_results[0]["file"] == "q1.py"          # what is returned is a copy


def test_the_mark_adds_up_every_marked_answer_out_of_the_points_of_all_the_questions():
    assignment, submission = _first_marked()
    assert (submission.test_earned, submission.test_total, submission.status, submission.tests_run_at) == (
        6, 7.5, "graded", NOW)
    assert [(a["question"], a["marked"], a["earned"], a["total"]) for a in submission.question_results] == [
        (1, True, 2, 3.5), (2, True, 4, 4)]
    report = submission.question_results[0]["report"]                  # what the student was shown for question 1
    assert (report["passed"], report["total"], report["hidden_failed"], [f["sample"] for f in report["failures"]]) == (
        1, 2, 0, [2])


def test_marking_a_question_again_replaces_its_result_and_the_mark_follows():
    assignment, submission = _first_marked()
    code_answers.record_runs(assignment, submission, [
        _run(1, [_result(1, 1, True, points=2), _result(2, 1, True, points=1.5)])], now=NOW)
    assert (submission.test_earned, submission.test_total) == (7.5, 7.5)
    assert [(a["question"], a["earned"]) for a in submission.question_results] == [(1, 3.5), (2, 4)]


def test_a_question_that_was_not_answered_is_left_alone_and_earns_nothing():
    assignment, submission = _challenge(), Submission(question_results=[])
    code_answers.add_answer(assignment, submission, 2, "q2.py", "python")
    skipped = [_result(1, 1, False, points=2), _result(2, 1, False, points=1.5)]
    code_answers.record_runs(assignment, submission, [
        _run(1, skipped, answered=False), _run(2, [_result(3, 2, True, points=4)])], now=NOW)
    assert [a["question"] for a in submission.question_results] == [2]  # nothing was recorded for question 1
    assert (submission.test_earned, submission.test_total) == (4, 7.5)  # but its points are in the total

    nothing = Submission(question_results=[])
    code_answers.record_runs(assignment, nothing, [_run(1, skipped, answered=False)], now=NOW)
    assert (nothing.test_earned, nothing.test_total, nothing.status) == (None, None, None)  # no mark without an answer


def test_an_answer_without_a_result_adds_nothing_to_the_mark():
    assignment, submission = _challenge(), Submission(question_results=[])
    code_answers.add_answer(assignment, submission, 1, "q1.py", "python")  # handed in, tests not run
    code_answers.add_answer(assignment, submission, 2, "q2.py", "python")
    code_answers.record_runs(assignment, submission, [_run(2, [_result(3, 2, True, points=4)])], now=NOW)
    assert [(a["question"], a["marked"]) for a in submission.question_results] == [(1, False), (2, True)]
    assert (submission.test_earned, submission.test_total) == (4, 7.5)


def test_points_are_added_without_float_noise():
    assert code_answers.points_of([{"points": 0.1}, {"points": 0.2}]) == 0.3
    assert code_answers.points_of([{}, {}]) == 2                      # a test without points is worth one
    assignment = Assignment(assignment_type="code_challenge", code_questions=QUESTIONS[:1],
                            test_cases=[{"id": 1, "points": 0.1}, {"id": 2, "points": 0.2}])
    submission = Submission(question_results=[])
    code_answers.record_runs(assignment, submission, [
        _run(1, [_result(1, 1, True, points=0.1), _result(2, 1, True, points=0.2)])], now=NOW)
    assert (submission.test_earned, submission.test_total) == (0.3, 0.3)
