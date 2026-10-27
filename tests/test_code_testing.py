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
    _files(tmp_path, "Program.java", "__MACOSX/x.py", ".hidden/y.py", "__pycache__/z.py")
    with pytest.raises(ct.CodeTestError, match="No Python or Ruby file"):
        ct.pick_main_file(tmp_path)
    with pytest.raises(ct.CodeTestError, match="Python and Ruby programs only"):
        ct.language_of_file("Program.java")
    assert ct.language_of_file("a/b.rb").id == "ruby"


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
