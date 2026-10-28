"""Run a submission's code against an assignment's test cases (HackerRank style).

Each test runs the student's program in its own throw-away Docker container:
the test's input goes to the program's standard input and the output is
compared with the expected output. Python and Ruby are supported.

Student code is untrusted, so every container has no network, a memory cap
(no swap), a CPU cap, a process cap, a read-only root filesystem, all Linux
capabilities dropped, an unprivileged user and a hard time limit. The code is
mounted read-only and copied to a small in-memory scratch folder first, so
programs that save and load files (common in assignments) still work, and
nothing one test writes is seen by the next.

Like code_execution.py there is deliberately no "just run it locally"
fallback: without Docker nothing runs. The command runner is injectable so the
logic is unit-tested without Docker.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .code_execution import DEFAULT_IMAGE, SandboxUnavailable

DEFAULT_TEST_TIMEOUT = int(os.environ.get("CODE_TEST_TIMEOUT", "10"))  # seconds per test
MEMORY_LIMIT = "256m"
MAX_CAPTURED_CHARS = 100_000  # output kept for comparing
MAX_SHOWN_CHARS = 5_000  # output kept for showing to a person

# runner(command, timeout_seconds, stdin_text) -> (returncode, stdout, stderr);
# may raise subprocess.TimeoutExpired.
Runner = Callable[[list, float, str], "tuple[int, str, str]"]


class CodeTestError(ValueError):
    """The tests cannot run on this submission (no code, no main file, unsupported language...)."""


@dataclass(frozen=True)
class Language:
    id: str
    extensions: tuple
    interpreter: str
    image: str


LANGUAGES: dict = {
    "python": Language("python", (".py",), "python", DEFAULT_IMAGE),
    "ruby": Language("ruby", (".rb",), "ruby", os.environ.get("CODE_SANDBOX_RUBY_IMAGE", "ruby:3.3-slim")),
}
_RUNNABLE = {ext: lang for lang in LANGUAGES.values() for ext in lang.extensions}
# Used to pick the main file when a submission has several and none is named.
_CONVENTIONAL_STEMS = ("main", "app", "run", "program", "index")


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class, despite the name

    test_id: int
    name: str
    visible: bool
    points: float
    match: str
    status: str  # passed | failed | error | timeout | skipped (no code was submitted for its question)
    passed: bool
    expected_output: str
    actual_output: str  # clipped for display
    stderr: str = ""
    question: int = 1  # the question of the code challenge the test belongs to


@dataclass
class TestRun:
    __test__ = False  # not a pytest test class, despite the name

    file: str  # the file that was run, relative to the code folder
    language: str
    results: list


@dataclass(frozen=True)
class TestScore:
    """The points a run earned: the sum of the points of the tests that passed."""

    __test__ = False  # not a pytest test class, despite the name

    earned: float
    total: float  # the points of every test in the run
    passed: int
    count: int

    def marks(self, max_points: float) -> float:
        """The score scaled to `max_points`, e.g. 16 of 20 test points is 8 of 10 marks.
        Zero when the run has no points to earn."""
        return round(self.earned / self.total * max_points, 2) if self.total > 0 else 0.0


def score_run(results: list) -> TestScore:
    """Score a run's results: a test earns its points only when it passed
    (a wrong answer, a crash and a timeout all earn nothing)."""
    return TestScore(
        earned=round(sum(r.points for r in results if r.passed), 2),  # round: no 0.1 + 0.2 float noise
        total=round(sum(r.points for r in results), 2),
        passed=sum(1 for r in results if r.passed),
        count=len(results),
    )


# ---- comparing output -----------------------------------------------------


def _normalise(text: str) -> str:
    """Line endings unified, trailing spaces and surrounding blank lines dropped."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip("\n")


def outputs_match(expected: str, actual: str, mode: str) -> bool:
    """exact: the whole output equals the expected text; contains: the expected
    text appears in the output (for menu programs that print prompts)."""
    expected, actual = _normalise(expected), _normalise(actual)
    return expected in actual if mode == "contains" else expected == actual


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


# ---- choosing the file to run ---------------------------------------------


def _code_files(code_dir: Path) -> list:
    """Every file under code_dir except hidden folders and archive/cache clutter."""
    skip = {"__MACOSX", "__pycache__", "node_modules"}
    found = []
    for path in sorted(code_dir.rglob("*")):
        rel_parts = path.relative_to(code_dir).parts
        if path.is_file() and not any(p.startswith(".") or p in skip for p in rel_parts):
            found.append(path)
    return found


def pick_main_file(code_dir: Path, preferred: str = "") -> str:
    """The file to run, relative to code_dir, as a posix path.

    The instructor's `preferred` name wins (a path or just a file name).
    Otherwise a single Python/Ruby file is used, or a conventionally named one
    (main, app, run, program, index) when there are several."""
    code_dir = Path(code_dir).resolve()
    files = _code_files(code_dir)
    wanted = (preferred or "").strip().replace("\\", "/")
    if wanted:
        by_name = [p for p in files if p.name.lower() == PurePosixPath(wanted).name.lower()]
        exact = [p for p in by_name if p.relative_to(code_dir).as_posix().lower().endswith(wanted.lower())]
        matches = exact or by_name
        if not matches:
            raise CodeTestError(f"The main file '{wanted}' was not found in the submission.")
        return matches[0].relative_to(code_dir).as_posix()

    runnable = [p for p in files if p.suffix.lower() in _RUNNABLE]
    if not runnable:
        raise CodeTestError("No Python or Ruby file was found in the submission.")
    if len(runnable) == 1:
        return runnable[0].relative_to(code_dir).as_posix()
    conventional = [p for p in runnable if p.stem.lower() in _CONVENTIONAL_STEMS]
    if len(conventional) == 1:
        return conventional[0].relative_to(code_dir).as_posix()
    names = ", ".join(p.relative_to(code_dir).as_posix() for p in runnable[:6])
    raise CodeTestError(f"Several code files were found ({names}); set the main file name on the assignment.")


def language_of_file(relative_file: str) -> Language:
    lang = _RUNNABLE.get(PurePosixPath(relative_file).suffix.lower())
    if lang is None:
        raise CodeTestError(f"Tests can run Python and Ruby programs only; '{relative_file}' is neither.")
    return lang


# ---- running in Docker ----------------------------------------------------

# Inside the container: copy the read-only code to the scratch folder, go to
# the main file's folder, run it with a time limit. The folder, time limit,
# interpreter and file arrive as separate arguments ($1..$4), never spliced
# into the script, so odd file names cannot inject commands.
_SCRIPT = 'cp -r /code/. /run/ && cd "/run/$1" && exec timeout "$2" "$3" "$4"'


def build_test_command(name: str, code_dir: Path, relative_file: str, language: Language, timeout: int) -> list:
    rel = PurePosixPath(relative_file)
    return [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none",
        "--memory", MEMORY_LIMIT, "--memory-swap", MEMORY_LIMIT, "--cpus", "0.5", "--pids-limit", "64",
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/run:rw,size=64m,mode=1777",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{code_dir}:/code:ro",
        language.image,
        "sh", "-c", _SCRIPT, "sh", rel.parent.as_posix(), str(timeout), language.interpreter, rel.name,
    ]


def _docker_runner(command: list, timeout: float, stdin: str) -> tuple:
    # Bytes in and out: text mode would turn "\n" into "\r\n" on Windows.
    proc = subprocess.run(command, input=stdin.encode("utf-8"), capture_output=True, timeout=timeout)
    return (proc.returncode, proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"))


def _docker_ready(runner: Runner) -> bool:
    try:
        code, _out, _err = runner(["docker", "version", "--format", "{{.Server.Version}}"], 10, "")
    except Exception:
        return False
    return code == 0


def _stdin_for(test: dict) -> str:
    text = (test.get("input") or "").replace("\r\n", "\n")
    return text if not text or text.endswith("\n") else text + "\n"


def _run_one(test: dict, code_dir: Path, relative_file: str, language: Language, runner: Runner,
             timeout: int) -> TestResult:
    name = f"codetest-{uuid.uuid4().hex[:12]}"
    command = build_test_command(name, code_dir, relative_file, language, timeout)
    expected = test.get("expected_output", "")
    base = dict(test_id=test["id"], name=test["name"], visible=bool(test.get("visible")),
                points=test.get("points", 1), match=test.get("match", "exact"), expected_output=expected)
    try:
        code, out, err = runner(command, timeout + 30, _stdin_for(test))  # slack for container start-up
    except subprocess.TimeoutExpired:
        try:  # the CLI timed out, not necessarily the container: stop it
            runner(["docker", "kill", name], 10, "")
        except Exception:
            pass
        return TestResult(**base, status="timeout", passed=False, actual_output="",
                          stderr=f"No result within {timeout + 30} seconds.")

    out = out[:MAX_CAPTURED_CHARS]
    if code == 125:
        # `docker run` itself failed (the daemon refused, or the image is missing and cannot be downloaded):
        # that says nothing about the program, so it must not become a failed test and a saved mark of 0.
        reason = next((line for line in reversed(err.strip().splitlines()) if line.strip()), "no details")
        raise SandboxUnavailable(f"Docker could not start the test container: {reason.strip()[:300]}")
    if code == 124:  # coreutils `timeout`: the program hit its time limit
        return TestResult(**base, status="timeout", passed=False, actual_output=_clip(out, MAX_SHOWN_CHARS),
                          stderr=f"Time limit of {timeout} seconds exceeded.")
    if code != 0:
        note = "Killed: probably out of memory (limit 256 MB)." if code == 137 else ""
        return TestResult(**base, status="error", passed=False, actual_output=_clip(out, MAX_SHOWN_CHARS),
                          stderr=_clip("\n".join(s for s in (err, note) if s), MAX_SHOWN_CHARS))
    passed = outputs_match(expected, out, base["match"])
    return TestResult(**base, status="passed" if passed else "failed", passed=passed,
                      actual_output=_clip(out, MAX_SHOWN_CHARS), stderr=_clip(err, MAX_SHOWN_CHARS))


def run_tests(code_dir: Path, tests: list, *, main_file: str = "", only_visible: bool = False,
              runner: Runner = _docker_runner, timeout: int = DEFAULT_TEST_TIMEOUT) -> TestRun:
    """Run `tests` (the assignment's test_cases) on the code in `code_dir`.

    Raises SandboxUnavailable (and runs nothing) when Docker cannot be used,
    and CodeTestError when the submission cannot be run. `only_visible` runs
    just the visible tests."""
    if not _docker_ready(runner):
        raise SandboxUnavailable("Docker is not available, so the tests were not run")
    code_dir = Path(code_dir).resolve()
    if not code_dir.is_dir():
        raise CodeTestError("This submission has no code.")
    relative_file = pick_main_file(code_dir, main_file)
    language = language_of_file(relative_file)
    chosen = [t for t in tests if t.get("visible")] if only_visible else list(tests)
    results = [_run_one(t, code_dir, relative_file, language, runner, timeout) for t in chosen]
    return TestRun(file=relative_file, language=language.id, results=results)


# ---- a challenge with several questions ----------------------------------------


@dataclass
class QuestionRun:
    """How one question of a code challenge was run on a submission."""

    question: int
    title: str
    answered: bool  # False: the submission has no code for this question, so none of its tests ran
    file: str  # the file that was run, "" when none was
    language: str  # "" when none was
    results: list  # a TestResult per test of the question ("skipped" ones when it was not answered)


def answer_filename(question_count: int, question: int, language: str) -> str:
    """The name a typed answer is saved under: main.py (or main.rb) for a challenge with one
    question, q1.py, q2.rb, ... for one with several."""
    stem = "main" if question_count == 1 else f"q{question}"
    return f"{stem}{LANGUAGES[language].extensions[0]}"


def answer_file(code_dir: Path, question: int) -> str:
    """The file that answers `question` in a submission of a challenge with several questions
    (q1.py, q2.rb, ...), or "" when the student wrote nothing for it."""
    for lang in LANGUAGES.values():
        for extension in lang.extensions:
            if (Path(code_dir) / f"q{question}{extension}").is_file():
                return f"q{question}{extension}"
    return ""


def _single_question_file(code_dir: Path, preferred: str) -> str:
    """The file to run for a challenge with one question: the instructor's main file when the submission
    has it, otherwise "" so run_tests picks it (a typed answer is the only file, main.py or main.rb)."""
    if preferred.strip():
        try:
            return pick_main_file(code_dir, preferred)
        except CodeTestError:
            pass
    return ""


def _skipped(test: dict, question: int) -> TestResult:
    return TestResult(
        test_id=test["id"], name=test["name"], visible=bool(test.get("visible")), points=test.get("points", 1),
        match=test.get("match", "exact"), status="skipped", passed=False,
        expected_output=test.get("expected_output", ""), actual_output="",
        stderr="No code was submitted for this question.", question=question)


def run_questions(code_dir: Path, questions: list, tests: list, *, main_file: str = "") -> list:
    """Run each question's tests on the code that answers it; returns a QuestionRun per question.

    A challenge with one question runs `main_file` (or the only code file), as run_tests does. With
    several, each question is answered by its own file (see answer_file): one without a file is not
    run and its tests earn nothing. Raises what run_tests raises, and runs nothing more after that."""
    code_dir = Path(code_dir)
    if not code_dir.is_dir():
        raise CodeTestError("This submission has no code.")
    runs = []
    for q in questions:
        mine = [t for t in tests if t.get("question", 1) == q["id"]]
        if len(questions) == 1:
            file = _single_question_file(code_dir, main_file)
        else:
            file = answer_file(code_dir, q["id"])
            if not file:
                runs.append(QuestionRun(q["id"], q["title"], False, "", "", [_skipped(t, q["id"]) for t in mine]))
                continue
        run = run_tests(code_dir, mine, main_file=file)
        for result in run.results:
            result.question = q["id"]
        runs.append(QuestionRun(q["id"], q["title"], True, run.file, run.language, run.results))
    return runs
