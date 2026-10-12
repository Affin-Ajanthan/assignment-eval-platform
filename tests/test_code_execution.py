"""Sandboxed execution of student code: command safety, result handling,
the prompt, and the pipeline wiring. Uses a fake runner, so no Docker is
needed (one live test runs only when a Docker engine is up)."""

import subprocess

import pytest

from app.evaluator import code_execution as ce
from app.evaluator import rubric_grading
from app.evaluator.code_execution import (
    ExecutionResult,
    SandboxUnavailable,
    build_command,
    format_for_prompt,
    run_python_files,
    sandbox_enabled,
)
from app.evaluator.pipeline import evaluate_submission
from app.evaluator.rubric_grading import Criterion, Evidence, GradingResult, CriterionResult, RubricGrader


class FakeRunner:
    """Pretends to be Docker: `version` succeeds, `run` returns what we script."""

    def __init__(self, run_reply=(0, "", ""), docker_up=True, raise_on_run=None):
        self.run_reply, self.docker_up, self.raise_on_run = run_reply, docker_up, raise_on_run
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append(command)
        if command[:2] == ["docker", "version"]:
            return (0, "29.0", "") if self.docker_up else (1, "", "daemon not running")
        if command[:2] == ["docker", "run"] and self.raise_on_run:
            raise self.raise_on_run
        return self.run_reply if command[:2] == ["docker", "run"] else (0, "", "")

    @property
    def run_commands(self):
        return [c for c in self.commands if c[:2] == ["docker", "run"]]


@pytest.fixture
def code_dir(tmp_path):
    (tmp_path / "solution.py").write_text("print('hi')\n")
    return tmp_path


# ---- safety ---------------------------------------------------------------


def test_sandbox_is_off_by_default(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    assert sandbox_enabled() is False
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    assert sandbox_enabled() is True


def test_container_is_locked_down(tmp_path):
    cmd = build_command("sandbox-x", tmp_path, "solution.py", 10, "python:3.12-slim")
    joined = " ".join(cmd)
    assert cmd[:2] == ["docker", "run"] and "--rm" in cmd
    assert "--network none" in joined            # no network
    assert "--read-only" in cmd                  # read-only root filesystem
    assert "--cap-drop ALL" in joined            # no Linux capabilities
    assert "no-new-privileges" in joined
    assert "--user 65534" in joined              # unprivileged user
    assert "--memory 256m" in joined and "--pids-limit 64" in joined and "--cpus 0.5" in joined
    assert f"{tmp_path}:/work:ro" in joined      # student code mounted read-only
    assert cmd[-4:] == ["timeout", "10", "python", "solution.py"]


def test_never_runs_code_without_docker(code_dir):
    runner = FakeRunner(docker_up=False)
    with pytest.raises(SandboxUnavailable):
        run_python_files(code_dir, runner=runner)
    assert runner.run_commands == []             # nothing was executed


# ---- results --------------------------------------------------------------


def test_successful_run_is_captured(code_dir):
    runner = FakeRunner(run_reply=(0, "[1, 2, 5]\n", ""))
    [r] = run_python_files(code_dir, runner=runner)
    assert (r.filename, r.status, r.exit_code, r.stdout) == ("solution.py", "ok", 0, "[1, 2, 5]")


def test_crash_and_program_timeout_are_distinguished(code_dir):
    [crash] = run_python_files(code_dir, runner=FakeRunner(run_reply=(1, "", "NameError: x")))
    assert (crash.status, crash.exit_code, crash.stderr) == ("error", 1, "NameError: x")
    [slow] = run_python_files(code_dir, runner=FakeRunner(run_reply=(124, "", "")))  # coreutils `timeout`
    assert slow.status == "timeout"


def test_hung_container_is_killed(code_dir):
    runner = FakeRunner(raise_on_run=subprocess.TimeoutExpired(cmd="docker", timeout=40))
    [r] = run_python_files(code_dir, runner=runner)
    assert r.status == "timeout"
    assert any(c[:2] == ["docker", "kill"] for c in runner.commands)  # container was stopped


def test_long_output_is_truncated(code_dir):
    [r] = run_python_files(code_dir, runner=FakeRunner(run_reply=(0, "x" * 5000, "")))
    assert len(r.stdout) < 1100 and r.stdout.endswith("[truncated]")


def test_at_most_three_files_are_run(tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.py").write_text("pass\n")
    runner = FakeRunner()
    assert len(run_python_files(tmp_path, runner=runner)) == 3
    assert len(runner.run_commands) == 3


# ---- the prompt -----------------------------------------------------------


def test_prompt_says_not_executed_when_no_run_exists():
    prompt = rubric_grading._build_prompt([Criterion("X", max_points=1)], Evidence())
    assert "EXECUTION RESULT" in prompt
    assert "no run available -- judge the code by reading it" in prompt


def test_prompt_contains_the_real_run_and_lets_the_model_cite_only_that():
    evidence = Evidence(code_execution=[ExecutionResult("solution.py", "ok", 0, "[1, 2, 5]", "")])
    prompt = rubric_grading._build_prompt([Criterion("X", max_points=1)], evidence)
    assert "solution.py: ran without errors" in prompt and "[1, 2, 5]" in prompt
    assert "no run available" not in prompt
    # the "cannot run code" rule is still there, with the one allowed exception
    assert "you cannot run, execute or test any code" in prompt
    assert "may only cite the EXECUTION RESULT section" in prompt


def test_format_for_prompt_describes_crashes():
    text = format_for_prompt([ExecutionResult("a.py", "error", 1, "", "ZeroDivisionError")])
    assert "crashed (exit code 1)" in text and "ZeroDivisionError" in text


# ---- pipeline wiring ------------------------------------------------------


class _CapturingGrader(RubricGrader):
    name = "capture"

    def __init__(self):
        self.evidence = None

    def grade(self, criteria, evidence):
        self.evidence = evidence
        return GradingResult([CriterionResult(c.name, 0.0, c.max_points, "") for c in criteria], self.name)


def _evaluate(code_dir, grader):
    return evaluate_submission(code_dir=code_dir, criteria=[Criterion("Correctness", max_points=10)], grader=grader)


def test_pipeline_does_not_run_code_when_sandbox_is_off(code_dir, monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    monkeypatch.setattr(ce, "run_python_files", lambda *a, **k: pytest.fail("code must not be executed"))
    grader = _CapturingGrader()
    _evaluate(code_dir, grader)
    assert grader.evidence.code_execution == []


def test_pipeline_passes_real_run_to_grader_and_flags_a_crash(code_dir, monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    from app.evaluator import pipeline
    monkeypatch.setattr(pipeline, "run_python_files",
                        lambda d: [ExecutionResult("solution.py", "error", 1, "", "NameError: y")])
    grader = _CapturingGrader()
    result = _evaluate(code_dir, grader)
    assert grader.evidence.code_execution[0].status == "error"
    assert any("sandbox: solution.py crashed (exit code 1)" in f for f in result.review_flags)


def test_pipeline_survives_missing_docker_and_says_so(code_dir, monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    from app.evaluator import pipeline

    def no_docker(_dir):
        raise SandboxUnavailable("Docker is not available, so the code was not executed")

    monkeypatch.setattr(pipeline, "run_python_files", no_docker)
    grader = _CapturingGrader()
    result = _evaluate(code_dir, grader)  # must not raise
    assert grader.evidence.code_execution == []
    assert any("sandbox is unavailable" in f for f in result.review_flags)


# ---- live (only when a Docker engine is running) --------------------------


@pytest.mark.slow
def test_real_docker_runs_code_and_blocks_the_network(tmp_path):
    if not ce.docker_available():
        pytest.skip("Docker engine not running")
    (tmp_path / "ok.py").write_text("print('hello from the sandbox')\n")
    (tmp_path / "net.py").write_text(
        "import socket\n"
        "try:\n    socket.create_connection(('example.com', 80), timeout=3)\n    print('NETWORK OPEN')\n"
        "except OSError:\n    print('network blocked')\n"
    )
    results = {r.filename: r for r in run_python_files(tmp_path)}
    assert results["ok.py"].status == "ok" and "hello from the sandbox" in results["ok.py"].stdout
    assert "network blocked" in results["net.py"].stdout
