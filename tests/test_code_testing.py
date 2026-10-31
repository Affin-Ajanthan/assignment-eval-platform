"""Running a submission's code against an assignment's test cases (app/evaluator/code_testing.py).

The unit tests use a fake command runner, so they need no Docker. The tests
marked `slow` run the real Docker sandbox and skip when it is not available.
"""

import io
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import app.main as main
from app.evaluator import code_testing as ct
from app.evaluator.code_execution import SandboxUnavailable
from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, setup_subject_with_users, submit

client = TestClient(fastapi_app)


def _test(test_id, expected, *, input="", match="exact", visible=False, points=1, name=None):
    return {"id": test_id, "name": name or f"Test {test_id}", "input": input, "expected_output": expected,
            "match": match, "visible": visible, "points": points}


class FakeDocker:
    """Answers `docker version`, and each test run by its stdin."""

    def __init__(self, by_input=None, version_ok=True):
        self.by_input = by_input or {}
        self.version_ok = version_ok
        self.calls = []  # (command, timeout, stdin) of the test runs

    def __call__(self, command, timeout, stdin):
        if command[:2] == ["docker", "version"]:
            return (0 if self.version_ok else 1), "29.0", ""
        if command[:2] == ["docker", "kill"]:
            return 0, "", ""
        self.calls.append((command, timeout, stdin))
        outcome = self.by_input.get(stdin, (0, "", ""))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --------------------------------------------------------------------------
# Comparing output
# --------------------------------------------------------------------------


def test_exact_ignores_trailing_spaces_line_endings_and_surrounding_blank_lines():
    assert ct.outputs_match("1 2 3", "1 2 3\n", "exact")
    assert ct.outputs_match("a\nb", "\r\na  \r\nb\r\n\r\n", "exact")
    assert not ct.outputs_match("1 2 3", "1 2 3 4", "exact")
    assert not ct.outputs_match("a b", "a  b", "exact")  # inner spaces still count


def test_contains_finds_the_expected_text_inside_a_menu_programs_output():
    menu = "=== Menu ===\n1. Add\n2. Show\nEnter choice: Average: 75.00\nBye\n"
    assert ct.outputs_match("Average: 75.00", menu, "contains")
    assert not ct.outputs_match("Average: 80.00", menu, "contains")
    assert not ct.outputs_match("Average: 75.00", menu, "exact")


# --------------------------------------------------------------------------
# Choosing the file to run
# --------------------------------------------------------------------------


def _files(tmp_path, *names):
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print('x')\n")
    return tmp_path


def test_a_single_python_or_ruby_file_is_the_main_file_even_when_nested(tmp_path):
    _files(tmp_path, "Source/student_management.rb", "README.md")
    assert ct.pick_main_file(tmp_path) == "Source/student_management.rb"


def test_the_instructors_main_file_wins_by_name_or_path_case_insensitively(tmp_path):
    _files(tmp_path, "a/util.py", "b/Solution.py", "b/other.py")
    assert ct.pick_main_file(tmp_path, "solution.PY") == "b/Solution.py"
    assert ct.pick_main_file(tmp_path, "b\\other.py") == "b/other.py"
    with pytest.raises(ct.CodeTestError, match="'missing.py' was not found"):
        ct.pick_main_file(tmp_path, "missing.py")


def test_several_files_need_a_conventional_name_or_an_explicit_choice(tmp_path):
    _files(tmp_path, "a.py", "b.py")
    with pytest.raises(ct.CodeTestError, match="Several code files.*set the main file name"):
        ct.pick_main_file(tmp_path)
    _files(tmp_path, "main.py")
    assert ct.pick_main_file(tmp_path) == "main.py"


def test_no_runnable_file_and_hidden_or_cache_folders(tmp_path):
    _files(tmp_path, "Program.cs", "__MACOSX/x.py", ".hidden/y.py", "__pycache__/z.py")
    with pytest.raises(ct.CodeTestError, match=r"No Python, Ruby, Java, JavaScript, C or C\+\+ file"):
        ct.pick_main_file(tmp_path)
    with pytest.raises(ct.CodeTestError, match=r"Python, Ruby, Java, JavaScript, C or C\+\+ programs only"):
        ct.language_of_file("Program.cs")
    assert ct.language_of_file("a/b.rb").id == "ruby"


def test_java_and_javascript_files_are_runnable_and_found_like_the_others(tmp_path):
    assert ct.language_of_file("src/Main.java").id == "java"
    assert ct.language_of_file("app.JS").id == "javascript"
    assert (ct.language_of_file("a/main.c").id, ct.language_of_file("main.cpp").id, ct.language_of_file("x.cc").id) == (
        "c", "cpp", "cpp")
    with pytest.raises(ct.CodeTestError, match="none of them"):
        ct.language_of_file("util.h")                                  # a header is never the file to run
    _files(tmp_path, "sub/Main.java", "README.md")
    assert ct.pick_main_file(tmp_path) == "sub/Main.java"
    other = tmp_path / "two"
    _files(other, "a.js", "main.js")
    assert ct.pick_main_file(other) == "main.js"  # a conventional name wins among several


# --------------------------------------------------------------------------
# The Docker command
# --------------------------------------------------------------------------


def test_the_container_has_every_safety_limit_and_odd_file_names_stay_arguments(tmp_path):
    cmd = ct.build_test_command("n1", tmp_path, "My Dir/it's; rm -rf.py", ct.LANGUAGES["python"], 7)
    pairs = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
    assert pairs["--network"] == "none" and pairs["--memory"] == "256m" and pairs["--memory-swap"] == "256m"
    assert pairs["--cap-drop"] == "ALL" and pairs["--user"] == "65534" and "--read-only" in cmd
    assert f"{tmp_path}:/code:ro" in cmd  # the submission is mounted read-only
    # Folder, time limit, interpreter and file go after the script as separate arguments.
    assert cmd[-5:] == ["sh", "My Dir", "7", "python", "it's; rm -rf.py"]
    script = cmd[cmd.index("-c") + 1]
    assert "My Dir" not in script and "rm -rf" not in script
    assert pairs["--pids-limit"] == "64" and "JDK_JAVA_OPTIONS" not in " ".join(cmd)  # Python keeps the plain limits


def test_java_runs_with_the_source_launcher_a_bigger_process_cap_and_extra_start_up_time(tmp_path):
    java = ct.LANGUAGES["java"]
    cmd = ct.build_test_command("n1", tmp_path, "src/main.java", java, 7)
    pairs = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
    assert java.image in cmd and pairs["--pids-limit"] == "128" and pairs["--memory"] == "256m"
    assert cmd[-5:] == ["sh", "src", "12", "java", "main.java"]  # 7 seconds + 5 for the JVM to start and compile
    options = next(a for a in cmd if a.startswith("JDK_JAVA_OPTIONS="))
    assert "-Xmx128m" in options and "-XX:+UseSerialGC" in options
    assert cmd[cmd.index(options) - 1] == "-e"
    assert cmd.index(options) < cmd.index(java.image)  # an option of docker run, not of the program


@pytest.mark.parametrize("language_id,filename,compiler,standard", [
    ("c", "src/main.c", "gcc", "-std=c17"), ("cpp", "main.cpp", "g++", "-std=c++17")])
def test_c_and_cpp_are_compiled_in_the_container_then_run_with_the_time_limit(
        tmp_path, language_id, filename, compiler, standard):
    language = ct.LANGUAGES[language_id]
    cmd = ct.build_test_command("n1", tmp_path, filename, language, 7)
    pairs = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
    folder, _, name = filename.rpartition("/")
    # Folder, time limit, compiler, file and standard follow the script as separate arguments.
    assert cmd[-6:] == ["sh", folder or ".", "7", compiler, name, standard]
    script = cmd[cmd.index("-c") + 1]
    assert script == ct._COMPILED_SCRIPT and "-o /run/prog" in script and 'exec timeout "$2" /run/prog' in script
    assert name not in script and compiler not in script                # still only arguments, never spliced in
    assert language.image in cmd and pairs["--memory"] == "256m" and pairs["--network"] == "none"
    # The program is run from the scratch folder, so only there may programs be run.
    assert "/run:rw,size=64m,mode=1777,exec" in cmd and "/run:rw,size=64m,mode=1777" not in cmd
    plain = ct.build_test_command("n1", tmp_path, "main.py", ct.LANGUAGES["python"], 7)
    assert "/run:rw,size=64m,mode=1777" in plain and ",exec" not in " ".join(plain)


def test_javascript_runs_with_node_and_the_plain_limits(tmp_path):
    js = ct.LANGUAGES["javascript"]
    cmd = ct.build_test_command("n1", tmp_path, "main.js", js, 7)
    pairs = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
    assert js.image in cmd and pairs["--pids-limit"] == "64"
    assert cmd[-5:] == ["sh", ".", "7", "node", "main.js"]


# --------------------------------------------------------------------------
# Running the tests (fake Docker)
# --------------------------------------------------------------------------


def test_each_test_gets_its_input_and_is_marked_by_its_outcome(tmp_path):
    _files(tmp_path, "main.py")
    docker = FakeDocker({
        "21\n": (0, "42\n", ""),                       # passes
        "1\n": (0, "3\n", ""),                         # wrong output
        "boom\n": (1, "", "Traceback: boom"),          # crashes
        "slow\n": (124, "partial", ""),                # hits the program's time limit
        "kill\n": (137, "", ""),                       # killed (out of memory)
        "hang\n": subprocess.TimeoutExpired("docker", 40),  # docker itself never answers
    })
    tests = [_test(1, "42", input="21"), _test(2, "2", input="1"), _test(3, "x", input="boom"),
             _test(4, "x", input="slow"), _test(5, "x", input="kill"), _test(6, "x", input="hang"),
             _test(7, "", input="")]
    run = ct.run_tests(tmp_path, tests, runner=docker, timeout=5)

    assert (run.file, run.language) == ("main.py", "python")
    assert [(r.test_id, r.status, r.passed) for r in run.results] == [
        (1, "passed", True), (2, "failed", False), (3, "error", False), (4, "timeout", False),
        (5, "error", False), (6, "timeout", False), (7, "passed", True)]
    by_id = {r.test_id: r for r in run.results}
    assert by_id[2].actual_output == "3" and by_id[2].expected_output == "2"
    assert "boom" in by_id[3].stderr
    assert "Time limit of 5 seconds" in by_id[4].stderr and by_id[4].actual_output == "partial"
    assert "out of memory" in by_id[5].stderr
    assert "No result within 35 seconds" in by_id[6].stderr
    # Each test ran in its own container, with the stdin ending in a newline.
    assert [stdin for _cmd, _t, stdin in docker.calls][:2] == ["21\n", "1\n"]
    assert len({c[0][c[0].index("--name") + 1] for c in docker.calls}) == len(docker.calls)
    assert all(timeout == 35 for _cmd, timeout, _stdin in docker.calls)  # time limit + start-up slack


@pytest.mark.parametrize("filename,language", [
    ("main.java", "java"), ("main.js", "javascript"), ("main.c", "c"), ("main.cpp", "cpp")])
def test_java_javascript_c_and_cpp_tests_are_run_and_marked_like_python_ones(tmp_path, filename, language):
    _files(tmp_path, filename)
    docker = FakeDocker({"21\n": (0, "42\n", ""), "1\n": (0, "3\n", ""), "boom\n": (1, "", "boom")})
    tests = [_test(1, "42", input="21"), _test(2, "2", input="1"), _test(3, "x", input="boom")]
    run = ct.run_tests(tmp_path, tests, runner=docker, timeout=5)

    assert (run.file, run.language) == (filename, language)
    assert [(r.test_id, r.status) for r in run.results] == [(1, "passed"), (2, "failed"), (3, "error")]
    command = docker.calls[0][0]
    assert ct.LANGUAGES[language].image in command
    assert filename in command[-2:]  # the file is the last argument, or just before the compiler's standard


def test_docker_failing_to_start_a_container_is_not_a_failed_test(tmp_path):
    _files(tmp_path, "main.py")
    docker = FakeDocker({"21\n": (125, "", "Unable to find image 'python:3.12-slim' locally\n"
                                           "docker: Error response from daemon: no such host.\n")})
    with pytest.raises(SandboxUnavailable, match="could not start the test container.*no such host"):
        ct.run_tests(tmp_path, [_test(1, "42", input="21")], runner=docker)  # nothing is scored


def test_only_visible_runs_just_the_tests_students_may_see(tmp_path):
    _files(tmp_path, "main.py")
    docker = FakeDocker()
    tests = [_test(1, "", visible=True), _test(2, "", visible=False), _test(3, "", visible=True)]
    run = ct.run_tests(tmp_path, tests, runner=docker, only_visible=True)
    assert [r.test_id for r in run.results] == [1, 3] and len(docker.calls) == 2


def test_nothing_runs_without_docker_or_without_a_runnable_submission(tmp_path):
    _files(tmp_path, "main.py")
    with pytest.raises(SandboxUnavailable):
        ct.run_tests(tmp_path, [_test(1, "")], runner=FakeDocker(version_ok=False))

    def no_docker_at_all(command, timeout, stdin):
        raise FileNotFoundError("docker")

    with pytest.raises(SandboxUnavailable):
        ct.run_tests(tmp_path, [_test(1, "")], runner=no_docker_at_all)
    with pytest.raises(ct.CodeTestError, match="no code"):
        ct.run_tests(tmp_path / "missing", [_test(1, "")], runner=FakeDocker())


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _results(*outcomes):
    """TestResults from (points, passed) pairs."""
    return [ct.TestResult(test_id=i, name=f"Test {i}", visible=False, points=points, match="exact",
                          status="passed" if passed else "failed", passed=passed, expected_output="",
                          actual_output="") for i, (points, passed) in enumerate(outcomes, start=1)]


def test_eight_of_ten_tests_worth_two_points_each_earn_16_of_20():
    score = ct.score_run(_results(*[(2, True)] * 8, *[(2, False)] * 2))
    assert (score.earned, score.total, score.passed, score.count) == (16, 20, 8, 10)
    assert score.marks(20) == 16
    assert score.marks(10) == 8      # scaled to a criterion worth 10 marks
    assert score.marks(15) == 12


def test_tests_are_weighted_by_their_points_and_failures_of_every_kind_earn_nothing():
    results = _results((5, True), (3, False), (2, True))
    for result, status in zip(results[1:], ("error", "timeout")):
        result.status = status  # a crash and a timeout earn nothing, like a wrong answer
    results[2].passed = False
    score = ct.score_run(results)
    assert (score.earned, score.total, score.passed, score.count) == (5, 10, 1, 3)
    assert score.marks(40) == 20


def test_scores_have_no_float_noise_and_marks_round_to_two_places():
    score = ct.score_run(_results((0.1, True), (0.2, True), (0.3, False)))
    assert (score.earned, score.total) == (0.3, 0.6)  # not 0.30000000000000004
    assert ct.score_run(_results((1, True), (1, False), (1, False))).marks(10) == 3.33


def test_a_run_with_no_tests_or_no_points_scores_zero_without_dividing_by_zero():
    empty = ct.score_run([])
    assert (empty.earned, empty.total, empty.passed, empty.count, empty.marks(10)) == (0, 0, 0, 0, 0.0)
    assert ct.score_run(_results((1, True))).marks(0) == 0


# --------------------------------------------------------------------------
# A challenge with several tasks
# --------------------------------------------------------------------------

QUESTIONS = [{"id": 1, "title": "One", "statement": ""}, {"id": 2, "title": "Two", "statement": ""}]
# Question 1 has two tests (2 + 1 points) and question 2 has one (4 points); only the tests that expect "ok" pass.
TESTS = [dict(_test(1, "ok", points=2), question=1), dict(_test(2, "no", points=1), question=1),
         dict(_test(3, "ok", points=4), question=2)]


class RecordingRun:
    """Stands in for run_tests: records each call and passes the tests that expect "ok"."""

    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, code_dir, tests, *, main_file="", **kwargs):
        if self.error:
            raise self.error
        self.calls.append((Path(code_dir).name, main_file, [t["id"] for t in tests]))
        results = [ct.TestResult(test_id=t["id"], name=t["name"], visible=t["visible"], points=t["points"],
                                 match=t["match"], status="passed" if t["expected_output"] == "ok" else "failed",
                                 passed=t["expected_output"] == "ok", expected_output=t["expected_output"],
                                 actual_output="") for t in tests]
        return ct.TestRun(file=main_file or "main.py", language="ruby" if main_file.endswith(".rb") else "python",
                          results=results)


def test_a_typed_answer_is_saved_as_main_for_one_question_and_by_number_for_several():
    assert ct.answer_filename(1, 1, "python") == "main.py"
    assert ct.answer_filename(1, 1, "ruby") == "main.rb"
    assert ct.answer_filename(3, 2, "python") == "q2.py"
    assert ct.answer_filename(3, 3, "ruby") == "q3.rb"
    assert ct.answer_filename(1, 1, "java") == "main.java"
    assert ct.answer_filename(2, 2, "java") == "q2.java"
    assert ct.answer_filename(1, 1, "javascript") == "main.js"
    assert ct.answer_filename(2, 1, "javascript") == "q1.js"
    assert ct.answer_filename(1, 1, "c") == "main.c"
    assert ct.answer_filename(3, 3, "cpp") == "q3.cpp"


def test_the_file_that_answers_a_question_is_found_by_its_number(tmp_path):
    (tmp_path / "q1.py").write_text("print(1)")
    (tmp_path / "q2.rb").write_text("puts 2")
    (tmp_path / "q10.py").write_text("print(10)")
    (tmp_path / "q3.txt").write_text("not code")
    assert ct.answer_file(tmp_path, 1) == "q1.py"  # not q10.py
    assert ct.answer_file(tmp_path, 2) == "q2.rb"
    assert ct.answer_file(tmp_path, 10) == "q10.py"
    assert ct.answer_file(tmp_path, 3) == ""  # only files of a language tests can run answer a question
    assert ct.answer_file(tmp_path, 4) == ""
    (tmp_path / "q4.java").write_text("class Main {}")
    (tmp_path / "q5.js").write_text("console.log(5)")
    (tmp_path / "q6.go").write_text("package main")
    (tmp_path / "q7.c").write_text("int main(void) { return 0; }")
    (tmp_path / "q8.cpp").write_text("int main() { return 0; }")
    assert (ct.answer_file(tmp_path, 4), ct.answer_file(tmp_path, 5), ct.answer_file(tmp_path, 6)) == ("q4.java", "q5.js", "")
    assert (ct.answer_file(tmp_path, 7), ct.answer_file(tmp_path, 8)) == ("q7.c", "q8.cpp")


def test_each_question_runs_its_own_file_and_its_own_tests(tmp_path, monkeypatch):
    (tmp_path / "q1.py").write_text("print('ok')")
    (tmp_path / "q2.rb").write_text("puts 'ok'")
    fake = RecordingRun()
    monkeypatch.setattr(ct, "run_tests", fake)

    runs = ct.run_questions(tmp_path, QUESTIONS, TESTS)
    assert fake.calls == [(tmp_path.name, "q1.py", [1, 2]), (tmp_path.name, "q2.rb", [3])]
    assert [(q.question, q.title, q.answered, q.file, q.language) for q in runs] == [
        (1, "One", True, "q1.py", "python"), (2, "Two", True, "q2.rb", "ruby")]
    # Every result knows its question, and the points add up over both questions.
    assert [(r.test_id, r.question, r.passed) for q in runs for r in q.results] == [(1, 1, True), (2, 1, False), (3, 2, True)]
    score = ct.score_run([r for q in runs for r in q.results])
    assert (score.earned, score.total, score.passed, score.count) == (6, 7, 2, 3)


def test_one_question_is_run_on_the_file_it_is_given_with_only_its_own_tests(tmp_path, monkeypatch):
    (tmp_path / "q2.rb").write_text("puts 'ok'")
    fake = RecordingRun()
    monkeypatch.setattr(ct, "run_tests", fake)

    run = ct.run_question(tmp_path, QUESTIONS[1], TESTS, file="q2.rb")
    assert fake.calls == [(tmp_path.name, "q2.rb", [3])]
    assert (run.question, run.title, run.answered, run.file, run.language) == (2, "Two", True, "q2.rb", "ruby")
    assert [(r.test_id, r.question, r.passed) for r in run.results] == [(3, 2, True)]

    ct.run_question(tmp_path, {"id": 1, "title": "", "statement": ""}, [_test(1, "ok")])  # no file given: run_tests picks it
    assert fake.calls[-1][1:] == ("", [1])


def test_a_question_without_code_is_not_run_and_earns_nothing(tmp_path, monkeypatch):
    (tmp_path / "q2.py").write_text("print('ok')")
    fake = RecordingRun()
    monkeypatch.setattr(ct, "run_tests", fake)

    runs = ct.run_questions(tmp_path, QUESTIONS, TESTS)
    assert [call[1] for call in fake.calls] == ["q2.py"]  # nothing was run for question 1
    first = runs[0]
    assert (first.answered, first.file, first.language) == (False, "", "")
    assert [(r.test_id, r.status, r.passed, r.points, r.question) for r in first.results] == [
        (1, "skipped", False, 2, 1), (2, "skipped", False, 1, 1)]
    assert "No code was submitted" in first.results[0].stderr
    score = ct.score_run([r for q in runs for r in q.results])
    assert (score.earned, score.total) == (4, 7)  # question 1's points are still part of the total


def test_a_challenge_with_one_question_runs_the_main_file_or_the_only_file(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print('ok')")
    fake = RecordingRun()
    monkeypatch.setattr(ct, "run_tests", fake)
    one = [{"id": 1, "title": "", "statement": ""}]
    tests = [_test(1, "ok")]  # a test saved without a question belongs to question 1

    ct.run_questions(tmp_path, one, tests)
    ct.run_questions(tmp_path, one, tests, main_file="main.py")
    ct.run_questions(tmp_path, one, tests, main_file="student_management.rb")  # not in the submission: the only file
    assert [call[1] for call in fake.calls] == ["", "main.py", ""]


def test_a_failure_stops_the_run_and_a_missing_folder_is_an_error(tmp_path, monkeypatch):
    (tmp_path / "q1.py").write_text("x")
    (tmp_path / "q2.py").write_text("x")
    monkeypatch.setattr(ct, "run_tests", RecordingRun(error=SandboxUnavailable("Docker is not available")))
    with pytest.raises(SandboxUnavailable):
        ct.run_questions(tmp_path, QUESTIONS, TESTS)
    with pytest.raises(ct.CodeTestError, match="no code"):
        ct.run_questions(tmp_path / "missing", QUESTIONS, TESTS)


# --------------------------------------------------------------------------
# The instructor endpoint
# --------------------------------------------------------------------------


def _assignment_with_tests(subject, itok, name, tests, **extra):
    now = datetime.now(timezone.utc)
    r = client.post("/assignments", headers=auth_headers(itok), json={
        "subject_id": subject["id"], "name": name, "available_from": (now - timedelta(hours=1)).isoformat(),
        "deadline": (now + timedelta(days=7)).isoformat(), "test_cases": tests, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _submit_code(subject, name):
    r = submit(client, subject["id"], name, {"code": ("main.py", io.BytesIO(b"print('hi')\n"), "text/x-python")})
    assert r.status_code == 200, r.text
    return r.json()


API_TESTS = [{"expected_output": "42", "input": "21", "visible": True, "points": 2},
             {"expected_output": "SECRET", "match": "contains"}]


def test_the_main_file_setting_is_saved_and_can_be_changed():
    subject, itok, _ = setup_subject_with_users(client)
    a = _assignment_with_tests(subject, itok, "Main file", API_TESTS, test_main_file="  student_management.rb  ")
    assert a["test_main_file"] == "student_management.rb"  # trimmed
    put = lambda body: client.put(f"/assignments/{a['id']}", headers=auth_headers(itok), json=body).json()  # noqa: E731
    assert put({"description": "x"})["test_main_file"] == "student_management.rb"  # kept
    assert put({"test_main_file": "main.py"})["test_main_file"] == "main.py"
    assert put({"test_main_file": ""})["test_main_file"] == ""  # back to automatic


def test_running_tests_returns_every_test_for_the_instructor(monkeypatch):
    subject, itok, _ = setup_subject_with_users(client)
    _assignment_with_tests(subject, itok, "Run me", API_TESTS, test_main_file="main.py")
    sub = _submit_code(subject, "Run me")
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    seen = {}

    def fake_run_tests(code_dir, tests, *, main_file="", **kwargs):
        seen.update(code_dir=Path(code_dir), tests=tests, main_file=main_file)
        results = [ct.TestResult(test_id=t["id"], name=t["name"], visible=t["visible"], points=t["points"],
                                 match=t["match"], status="passed" if t["id"] == 1 else "failed",
                                 passed=t["id"] == 1, expected_output=t["expected_output"], actual_output="42")
                   for t in tests]
        return ct.TestRun(file="main.py", language="python", results=results)

    monkeypatch.setattr(main._code_testing, "run_tests", fake_run_tests)
    r = client.post(f"/submissions/{sub['id']}/run-tests", headers=auth_headers(itok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["submission_id"], body["file"], body["language"], body["passed"], body["total"]) == (
        sub["id"], "main.py", "python", 1, 2)
    # Test 1 is worth 2 points and passed; test 2 is worth the default 1 point and failed.
    assert (body["earned_points"], body["total_points"]) == (2, 3)
    assert [(t["test_id"], t["status"], t["visible"]) for t in body["results"]] == [(1, "passed", True),
                                                                                    (2, "failed", False)]
    assert body["results"][1]["expected_output"] == "SECRET"  # hidden tests are part of the instructor's view
    assert seen["main_file"] == "main.py" and [t["id"] for t in seen["tests"]] == [1, 2]
    assert seen["code_dir"].name == "code"  # the submission's code folder


def test_running_tests_checks_access_and_what_can_be_run(monkeypatch):
    from tests.auth_helpers import new_student

    subject, itok, _ = setup_subject_with_users(client)
    _assignment_with_tests(subject, itok, "Guards", API_TESTS)
    sub = _submit_code(subject, "Guards")
    plain = main._code_testing.run_tests
    url = f"/submissions/{sub['id']}/run-tests"
    run = lambda token=itok: client.post(url, headers=auth_headers(token))  # noqa: E731

    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    off = run()
    assert off.status_code == 503 and "CODE_SANDBOX=docker" in off.json()["detail"]  # off by default

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    _, other_itok, _ = setup_subject_with_users(client)
    assert run(other_itok).status_code == 403                            # another subject's instructor
    assert run(new_student(client, subject["id"])).status_code == 403    # a student
    assert client.post("/submissions/999999/run-tests", headers=auth_headers(itok)).status_code == 404

    def cannot_pick(*args, **kwargs):
        raise ct.CodeTestError("Several code files were found; set the main file name on the assignment.")

    monkeypatch.setattr(main._code_testing, "run_tests", cannot_pick)
    assert run().status_code == 400

    def no_docker(*args, **kwargs):
        raise SandboxUnavailable("Docker is not available, so the tests were not run")

    monkeypatch.setattr(main._code_testing, "run_tests", no_docker)
    assert run().status_code == 503

    # An assignment without test cases has nothing to run.
    _assignment_with_tests(subject, itok, "No tests", [])
    plain_sub = _submit_code(subject, "No tests")
    monkeypatch.setattr(main._code_testing, "run_tests", plain)
    r = client.post(f"/submissions/{plain_sub['id']}/run-tests", headers=auth_headers(itok))
    assert r.status_code == 400 and "no test cases" in r.json()["detail"]


# --------------------------------------------------------------------------
# The real Docker sandbox (slow: skipped when Docker is not available)
# --------------------------------------------------------------------------

PROGRAM = """\
cmd = input()
if cmd == "loop":
    while True:
        pass
elif cmd == "crash":
    raise SystemExit(3)
elif cmd == "write":
    open("out.txt", "w").write("saved")
    print(open("out.txt").read())
elif cmd == "net":
    import socket
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        print("connected")
    except OSError:
        print("no network")
else:
    print(int(cmd) * 2)
"""


@pytest.mark.slow
def test_real_docker_runs_python_tests_safely(tmp_path):
    if not ct._docker_ready(ct._docker_runner):
        pytest.skip("Docker is not available")
    (tmp_path / "main.py").write_text(PROGRAM)
    tests = [_test(1, "42", input="21"), _test(2, "99", input="1"), _test(3, "x", input="crash"),
             _test(4, "saved", input="write"), _test(5, "no network", input="net"), _test(6, "x", input="loop")]
    run = ct.run_tests(tmp_path, tests, timeout=3)
    assert [(r.test_id, r.status) for r in run.results] == [
        (1, "passed"), (2, "failed"), (3, "error"), (4, "passed"), (5, "passed"), (6, "timeout")]
    assert not (tmp_path / "out.txt").exists()  # the submission folder itself was never written to


@pytest.mark.slow
def test_real_docker_runs_a_ruby_menu_program(tmp_path):
    import shutil

    if not ct._docker_ready(ct._docker_runner):
        pytest.skip("Docker is not available")
    image = ct.LANGUAGES["ruby"].image
    if shutil.which("docker") is None or subprocess.run(["docker", "image", "inspect", image],
                                                         capture_output=True).returncode != 0:
        pytest.skip(f"the Ruby image is not pulled (docker pull {image})")
    (tmp_path / "Source").mkdir()
    (tmp_path / "Source" / "menu.rb").write_text(
        'puts "=== Menu ==="\nputs "1. Average"\nprint "Enter choice: "\nchoice = gets.chomp\n'
        'a = gets.to_f\nb = gets.to_f\nputs "Average: #{(a + b) / 2}" if choice == "1"\n')
    tests = [_test(1, "Average: 75.0", input="1\n80\n70", match="contains"),
             _test(2, "Average: 75.0", input="1\n80\n70", match="exact")]
    run = ct.run_tests(tmp_path, tests, main_file="menu.rb")
    assert run.file == "Source/menu.rb" and run.language == "ruby"
    assert [r.passed for r in run.results] == [True, False]  # exact fails: the menu text is part of the output


JAVA_PROGRAM = """\
import java.util.Scanner;

public class Main {
    public static void main(String[] args) {
        String cmd = new Scanner(System.in).nextLine();
        if (cmd.equals("loop")) {
            while (true) { }
        } else if (cmd.equals("crash")) {
            throw new IllegalStateException("boom");
        } else {
            System.out.println(Integer.parseInt(cmd) * 2);
        }
    }
}
"""

JAVASCRIPT_PROGRAM = """\
const cmd = require("fs").readFileSync(0, "utf8").trim();
if (cmd === "loop") {
  while (true) { }
} else if (cmd === "crash") {
  throw new Error("boom");
} else {
  console.log(Number(cmd) * 2);
}
"""


C_PROGRAM = """\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    char cmd[64];
    fgets(cmd, sizeof cmd, stdin);
    if (strncmp(cmd, "loop", 4) == 0) {
        for (;;) { }
    } else if (strncmp(cmd, "crash", 5) == 0) {
        int *p = NULL;
        return *p;
    }
    printf("%d\\n", atoi(cmd) * 2);
    return 0;
}
"""

CPP_PROGRAM = """\
#include <iostream>
#include <string>

int main() {
    std::string cmd;
    std::getline(std::cin, cmd);
    if (cmd == "loop") {
        for (;;) { }
    } else if (cmd == "crash") {
        throw 1;
    }
    std::cout << std::stoi(cmd) * 2 << std::endl;
    return 0;
}
"""


def _skip_without_image(language_id):
    """Skip a slow test when Docker is off or the language's image has not been pulled."""
    if not ct._docker_ready(ct._docker_runner):
        pytest.skip("Docker is not available")
    image = ct.LANGUAGES[language_id].image
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0:
        pytest.skip(f"the {language_id} image is not pulled (docker pull {image})")


@pytest.mark.slow
@pytest.mark.parametrize("language_id,filename,program,broken,crash_line,syntax_line", [
    ("java", "main.java", JAVA_PROGRAM, 'public class Main {\n    public static void main(String[] a) {\n'
                                        '        System.out.println("hi")\n    }\n}\n', 9, 3),
    ("javascript", "main.js", JAVASCRIPT_PROGRAM, "let x = 1;\nlet y = ;\n", 5, 2),
])
def test_real_docker_runs_java_and_javascript_and_reports_the_error_line(
        tmp_path, language_id, filename, program, broken, crash_line, syntax_line):
    from app import code_answers

    _skip_without_image(language_id)
    (tmp_path / filename).write_text(program)
    tests = [_test(1, "42", input="21"), _test(2, "99", input="1"), _test(3, "x", input="crash"),
             _test(4, "x", input="loop")]
    run = ct.run_tests(tmp_path, tests, timeout=3)
    assert run.language == language_id
    assert [(r.test_id, r.status) for r in run.results] == [
        (1, "passed"), (2, "failed"), (3, "error"), (4, "timeout")]
    assert code_answers.compiler_error(run.results[2].stderr, language_id) == f"Compiler error. Error on line {crash_line}."

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / filename).write_text(broken)
    result = ct.run_tests(bad, [_test(1, "hi")], timeout=3).results[0]
    assert result.status == "error"
    assert code_answers.compiler_error(result.stderr, language_id) == f"Compiler error. Error on line {syntax_line}."


@pytest.mark.slow
@pytest.mark.parametrize("language_id,filename,program,broken", [
    ("c", "main.c", C_PROGRAM, "int main(void) {\n    int x = undefined_name;\n    return x;\n}\n"),
    ("cpp", "main.cpp", CPP_PROGRAM, "int main() {\n    int x = undefined_name;\n    return x;\n}\n"),
])
def test_real_docker_compiles_and_runs_c_and_cpp_and_reports_the_error_line(
        tmp_path, language_id, filename, program, broken):
    from app import code_answers

    _skip_without_image(language_id)
    (tmp_path / filename).write_text(program)
    tests = [_test(1, "42", input="21"), _test(2, "99", input="1"), _test(3, "x", input="crash"),
             _test(4, "x", input="loop")]
    run = ct.run_tests(tmp_path, tests, timeout=3)
    assert run.language == language_id
    assert [(r.test_id, r.status) for r in run.results] == [
        (1, "passed"), (2, "failed"), (3, "error"), (4, "timeout")]
    assert run.results[0].actual_output == "42"        # the compiler's messages never reach stdout
    # A crash that compiled has no line of the student's to name.
    assert code_answers.compiler_error(run.results[2].stderr, language_id) == "Compiler error."

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / filename).write_text(broken)
    result = ct.run_tests(bad, [_test(1, "hi")], timeout=3).results[0]
    assert result.status == "error" and result.actual_output == ""
    assert code_answers.compiler_error(result.stderr, language_id) == "Compiler error. Error on line 2."


# --------------------------------------------------------------------------
# Marking a code challenge from its tests
# --------------------------------------------------------------------------


def _fake_run(passing_ids):
    """A run_tests that passes the tests whose ids are in `passing_ids`."""
    def run(code_dir, tests, *, main_file="", **kwargs):
        results = [ct.TestResult(test_id=t["id"], name=t["name"], visible=t["visible"], points=t["points"],
                                 match=t["match"], status="passed" if t["id"] in passing_ids else "failed",
                                 passed=t["id"] in passing_ids, expected_output=t["expected_output"],
                                 actual_output="") for t in tests]
        return ct.TestRun(file="main.py", language="python", results=results)
    return run


def _challenge_submission(name):
    """A challenge with API_TESTS (2 + 1 points) and one student's submission to it."""
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _assignment_with_tests(subject, itok, name, API_TESTS)
    r = submit(client, subject["id"], name, {"code": ("main.py", io.BytesIO(b"print(1)\n"), "text/x-python")},
               student_tok=stok)
    assert r.status_code == 200, r.text
    return subject, itok, stok, assignment, r.json()["id"]


def _mark(submission_id, itok):
    return client.post(f"/submissions/{submission_id}/mark-from-tests", headers=auth_headers(itok))


def test_marking_from_the_tests_saves_the_points_as_the_mark_the_student_sees(monkeypatch):
    subject, itok, stok, assignment, sub_id = _challenge_submission("Marked by tests")
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(main._code_testing, "run_tests", _fake_run({1}))  # test 1 (2 points) passes, test 2 (1 point) fails

    r = _mark(sub_id, itok)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["saved"], body["earned_points"], body["total_points"], body["passed"], body["total"]) == (
        True, 2, 3, 1, 2)

    mine = client.get(f"/submissions/{sub_id}", headers=auth_headers(itok)).json()
    assert (mine["status"], mine["final_mark"], mine["max_mark"]) == ("graded", 2, 3)
    seen = client.get("/assignments", headers=auth_headers(stok)).json()[0]["my_submission"]
    assert (seen["status"], seen["final_mark"], seen["max_mark"], seen["can_edit"]) == ("graded", 2, 3, False)
    assert (seen["criterion_marks"], seen["feedback"]) == ([], None)  # no rubric, so no per-criterion marks
    listed = client.get("/submissions", headers=auth_headers(stok)).json()
    assert [(s["final_mark"], s["max_mark"]) for s in listed] == [(2, 3)]

    # Running again replaces the mark.
    monkeypatch.setattr(main._code_testing, "run_tests", _fake_run({1, 2}))
    assert _mark(sub_id, itok).json()["earned_points"] == 3
    assert client.get(f"/submissions/{sub_id}", headers=auth_headers(itok)).json()["final_mark"] == 3


def test_just_running_the_tests_does_not_change_the_mark(monkeypatch):
    subject, itok, stok, assignment, sub_id = _challenge_submission("Run only")
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(main._code_testing, "run_tests", _fake_run({1, 2}))

    r = client.post(f"/submissions/{sub_id}/run-tests", headers=auth_headers(itok))
    assert r.status_code == 200 and r.json()["saved"] is False
    after = client.get(f"/submissions/{sub_id}", headers=auth_headers(itok)).json()
    assert (after["status"], after["final_mark"], after["max_mark"]) == ("submitted", None, None)


def test_a_tests_mark_is_held_back_until_the_release_date(monkeypatch):
    subject, itok, stok, assignment, sub_id = _challenge_submission("Held back")
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(main._code_testing, "run_tests", _fake_run({1}))
    put = lambda body: client.put(f"/assignments/{assignment['id']}", headers=auth_headers(itok), json=body)  # noqa: E731
    later = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert put({"marks_release_at": later}).status_code == 200
    assert _mark(sub_id, itok).status_code == 200

    hidden = client.get("/assignments", headers=auth_headers(stok)).json()[0]["my_submission"]
    assert (hidden["status"], hidden["final_mark"], hidden["max_mark"]) == ("submitted", None, None)
    assert client.get(f"/submissions/{sub_id}", headers=auth_headers(stok)).json()["final_mark"] is None

    assert put({"marks_release_at": None}).status_code == 200  # release: the same saved mark appears
    shown = client.get("/assignments", headers=auth_headers(stok)).json()[0]["my_submission"]
    assert (shown["status"], shown["final_mark"], shown["max_mark"]) == ("graded", 2, 3)


def test_marking_follows_the_same_access_rules_as_running_the_tests(monkeypatch):
    from tests.auth_helpers import new_student

    subject, itok, stok, assignment, sub_id = _challenge_submission("Mark access")
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(main._code_testing, "run_tests", _fake_run({1}))
    _, other_itok, _ = setup_subject_with_users(client)
    assert _mark(sub_id, other_itok).status_code == 403                       # another subject's instructor
    assert _mark(sub_id, new_student(client, subject["id"])).status_code == 403  # a student
    assert client.post("/submissions/999999/mark-from-tests", headers=auth_headers(itok)).status_code == 404
    monkeypatch.delenv("CODE_SANDBOX")
    assert _mark(sub_id, itok).status_code == 503                             # sandbox off: nothing is marked
    assert client.get(f"/submissions/{sub_id}", headers=auth_headers(itok)).json()["final_mark"] is None


def test_a_code_challenge_cannot_be_marked_with_a_rubric(monkeypatch):
    subject, itok, stok, assignment, sub_id = _challenge_submission("No rubric marking")
    rubric = client.post("/rubrics", headers=auth_headers(itok), json={
        "name": "R", "subject_id": subject["id"], "criteria": [{"name": "Only", "max_points": 10}]}).json()
    h = auth_headers(itok)

    grade = client.post(f"/submissions/{sub_id}/grade", headers=h,
                        json={"rubric_id": rubric["id"], "criterion_scores": {"Only": 5}})
    assert grade.status_code == 400 and "marked from its tests" in grade.json()["detail"]
    assert client.post(f"/submissions/{sub_id}/auto-evaluate", headers=h,
                       json={"rubric_id": rubric["id"]}).status_code == 400
    name = "No rubric marking"
    batch = client.post(f"/subjects/{subject['id']}/assignments/{name}/auto-evaluate/jobs", headers=h,
                        json={"rubric_id": rubric["id"]})
    assert batch.status_code == 400 and "marked from its tests" in batch.json()["detail"]
