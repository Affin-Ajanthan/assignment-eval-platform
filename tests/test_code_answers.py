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


# --------------------------------------------------------------------------
# The compiler error a student sees, per language
# --------------------------------------------------------------------------

JAVA_DOES_NOT_COMPILE = """\
main.java:7: error: ';' expected
        System.out.println("hi")
                                ^
1 error
error: compilation failed
"""

JAVA_EXCEPTION = """\
NOTE: Picked up JDK_JAVA_OPTIONS: -XX:+UseSerialGC -Xmx128m
Exception in thread "main" java.lang.NumberFormatException: For input string: "x"
\tat java.base/java.lang.NumberFormatException.forInputString(NumberFormatException.java:67)
\tat java.base/java.lang.Integer.parseInt(Integer.java:661)
\tat Main.main(main.java:6)
\tat java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)
\tat jdk.compiler/com.sun.tools.javac.launcher.Main.execute(Main.java:484)
"""

NODE_SYNTAX_ERROR = """\
/run/main.js:2
let y = ;
        ^

SyntaxError: Unexpected token ';'
    at wrapSafe (node:internal/modules/cjs/loader:1469:18)
"""

NODE_EXCEPTION = """\
/run/sub/main.js:5
  throw new Error("boom");
  ^

Error: boom
    at Object.<anonymous> (/run/sub/main.js:5:9)
    at Module._compile (node:internal/modules/cjs/loader:1554:14)
"""


def test_java_is_told_the_line_of_the_compile_error_or_of_its_own_frame_in_a_crash():
    assert code_answers.compiler_error(JAVA_DOES_NOT_COMPILE, "java") == "Compiler error. Error on line 7."
    # The JDK's own frames (java.base/..., jdk.compiler/...) are skipped: the line is the student's.
    assert code_answers.compiler_error(JAVA_EXCEPTION, "java") == "Compiler error. Error on line 6."
    assert code_answers.compiler_error("Exception in thread \"main\" java.lang.Error", "java") == "Compiler error."
    assert code_answers.compiler_error("java.lang.OutOfMemoryError: Java heap space", "java") == (
        "The program ran out of memory.")


def test_javascript_is_told_the_line_node_names_in_the_students_own_file():
    assert code_answers.compiler_error(NODE_SYNTAX_ERROR, "javascript") == "Compiler error. Error on line 2."
    assert code_answers.compiler_error(NODE_EXCEPTION, "javascript") == "Compiler error. Error on line 5."
    only_node = "Error: x\n    at Module._compile (node:internal/modules/cjs/loader.js:1554:14)\n"
    assert code_answers.compiler_error(only_node, "javascript") == "Compiler error."
    assert code_answers.compiler_error("FATAL ERROR: JavaScript heap out of memory", "javascript") == (
        "The program ran out of memory.")


def test_a_java_crash_in_a_visible_test_shows_only_the_compiler_error_and_its_line():
    crash = ct.TestResult(test_id=1, name="t", visible=True, points=1, match="exact", status="error", passed=False,
                          expected_output="want", actual_output="partial", stderr=JAVA_EXCEPTION, input="x")
    report = code_answers.student_report([crash], "java")
    assert report["language"] == "java"
    assert report["failures"] == [{"sample": 1, "name": "t", "status": "error", "input": "x",
                                   "expected_output": "want", "actual_output": "",
                                   "error": "Compiler error. Error on line 6."}]
    assert "java.base" not in json.dumps(report) and "NumberFormatException" not in json.dumps(report)


GCC_DOES_NOT_COMPILE = """\
main.c: In function 'main':
main.c:3:5: warning: implicit declaration of function 'foo' [-Wimplicit-function-declaration]
main.c:4:13: error: 'undefined_name' undeclared (first use in this function)
main.c:4:13: note: each undeclared identifier is reported only once
"""

GCC_MISSING_HEADER = "main.cpp:1:10: fatal error: nothing.h: No such file or directory\ncompilation terminated.\n"

GCC_LINKER_ERROR = """\
/usr/bin/ld: /tmp/ccAbC123.o: in function `main':
main.c:(.text+0x9): undefined reference to `missing'
collect2: error: ld returned 1 exit status
"""


def test_c_and_cpp_are_told_the_line_of_the_first_compiler_error_never_a_warning():
    assert code_answers.compiler_error(GCC_DOES_NOT_COMPILE, "c") == "Compiler error. Error on line 4."
    assert code_answers.compiler_error(GCC_MISSING_HEADER, "cpp") == "Compiler error. Error on line 1."
    # A linker error, a crash with no message and a compile that only warned have no line of the student's.
    assert code_answers.compiler_error(GCC_LINKER_ERROR, "c") == "Compiler error."
    assert code_answers.compiler_error("", "cpp") == "Compiler error."
    assert code_answers.compiler_error("main.c:3:5: warning: unused variable 'x'\n", "c") == "Compiler error."
    assert code_answers.compiler_error("terminate called after throwing an instance of 'int'", "cpp") == (
        "Compiler error.")
