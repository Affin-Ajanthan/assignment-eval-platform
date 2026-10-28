"""Students run their typed code against ALL of a code challenge's test cases.

POST /assignments/{id}/run-code takes the code the student has typed (it is not
a submission yet), runs it in the Docker sandbox against every test case of the
challenge, visible and hidden, and tells the student only what they may know:

- every test passed: ``all_passed`` and the counts;
- a VISIBLE test failed: that test's expected output and actual output (plus the
  error message when the program crashed or ran out of time);
- a HIDDEN test failed: only how many did. Hidden tests' names, inputs and
  expected outputs never leave the server.

It is practice: it never creates a submission or changes a mark. Every rule
below is enforced here, whatever the page shows.

Each run starts Docker containers (one per test), so runs are limited: one at a
time per student, a number per hour per student, and a cap on runs at once
across the server.
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_student, student_subject_ids
from ..common import utcnow_naive
from ..db import get_db
from ..evaluator import code_testing
from ..evaluator.code_execution import SandboxUnavailable, sandbox_enabled
from ..models import Assignment, User

router = APIRouter()

RUNS_PER_HOUR = int(os.environ.get("CODE_SAMPLE_RUNS_PER_HOUR", "10"))
MAX_PARALLEL_RUNS = int(os.environ.get("CODE_SAMPLE_MAX_PARALLEL", "2"))
MAX_CODE_CHARS = 50_000
_HOUR = 3600


class RunLimitError(Exception):
    """A run is refused: `status` is the HTTP status and `detail` is shown to the student."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class RunLimiter:
    """Keeps runs from overloading the server. In memory, so the counts start
    again when the server restarts (the limits are about load, not marks)."""

    def __init__(self, per_hour: int = RUNS_PER_HOUR, max_parallel: int = MAX_PARALLEL_RUNS,
                 clock: Callable[[], float] = time.monotonic):
        self.per_hour, self.max_parallel, self._clock = per_hour, max_parallel, clock
        self._lock = threading.Lock()
        self._starts: dict[int, deque] = {}  # student id -> start times within the last hour
        self._active: set[int] = set()  # students with a run going

    def _recent(self, student_id: int) -> deque:
        starts = self._starts.setdefault(student_id, deque())
        now = self._clock()
        while starts and now - starts[0] >= _HOUR:
            starts.popleft()
        return starts

    def start(self, student_id: int) -> int:
        """Take a run for the student; returns how many they have left this hour.
        Raises RunLimitError, and uses up nothing, when the run is refused."""
        with self._lock:
            if student_id in self._active:
                raise RunLimitError(429, "Your previous run is still going. Wait for it to finish.")
            starts = self._recent(student_id)
            if len(starts) >= self.per_hour:
                minutes = max(1, math.ceil((_HOUR - (self._clock() - starts[0])) / 60))
                raise RunLimitError(
                    429, f"You can run your code {self.per_hour} times per hour. Try again in {minutes} minute(s).")
            if len(self._active) >= self.max_parallel:
                raise RunLimitError(503, "The server is busy running other students' code. Try again in a moment.")
            starts.append(self._clock())
            self._active.add(student_id)
            return self.per_hour - len(starts)

    def finish(self, student_id: int) -> None:
        with self._lock:
            self._active.discard(student_id)

    def remaining(self, student_id: int) -> int:
        with self._lock:
            return max(0, self.per_hour - len(self._recent(student_id)))

    def reset(self) -> None:
        with self._lock:
            self._starts.clear()
            self._active.clear()


limiter = RunLimiter()


class RunIn(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    # Left out: the assignment's language (its first one when it allows several).
    language: Optional[Literal["python", "ruby"]] = None


class RunFailureOut(BaseModel):
    """A VISIBLE test that did not pass: what was expected and what the program
    printed. Deliberately without ids, points or the input."""

    sample: int  # its place among the visible tests, from 1
    name: str
    status: str  # failed | error | timeout
    expected_output: str
    actual_output: str
    error: str = ""  # the crash message, or the time-limit note


class RunOut(BaseModel):
    language: str
    all_passed: bool  # every test case, hidden ones included
    passed: int  # test cases passed
    total: int  # test cases run
    hidden_failed: int  # hidden test cases that did not pass: nothing more is said about them
    remaining_runs: int  # runs left this hour
    failures: list[RunFailureOut]  # the visible tests that did not pass


def _pick_language(requested: Optional[str], assignment: Assignment) -> str:
    supported = list(code_testing.LANGUAGES)
    allowed = [lang for lang in (assignment.code_languages or supported) if lang in supported]
    if not allowed:
        raise HTTPException(400, "This can run Python and Ruby code only.")
    if requested is None:
        return allowed[0]
    if requested not in allowed:
        raise HTTPException(400, f"This assignment doesn't accept {requested} code.")
    return requested


def _report(results: list, language: str, runs_left: int) -> RunOut:
    """What a student may see of a run: counts, plus expected vs actual for the visible tests that failed."""
    failures: list[RunFailureOut] = []
    visible_seen = hidden_failed = 0
    for r in results:
        if r.visible:
            visible_seen += 1
            if not r.passed:
                failures.append(RunFailureOut(
                    sample=visible_seen, name=r.name, status=r.status, expected_output=r.expected_output,
                    actual_output=r.actual_output, error=r.stderr))
        elif not r.passed:
            hidden_failed += 1  # counted, never described
    passed = sum(1 for r in results if r.passed)
    return RunOut(language=language, all_passed=passed == len(results), passed=passed, total=len(results),
                  hidden_failed=hidden_failed, remaining_runs=runs_left, failures=failures)


@router.post("/assignments/{assignment_id}/run-code", response_model=RunOut)
def run_code(
    assignment_id: int, payload: RunIn,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Run the typed code against every test case of the assignment."""
    assignment = db.get(Assignment, assignment_id)
    now = utcnow_naive()
    if (not assignment or assignment.subject_id not in student_subject_ids(db, student)
            or assignment.status_at(now) == "upcoming"):
        raise HTTPException(404, "Assignment not found")
    if assignment.kind != "code_challenge":
        raise HTTPException(400, "Running code is only for code challenges.")
    if assignment.status_at(now) != "open":
        raise HTTPException(400, "This assignment is closed.")
    tests = assignment.test_cases or []
    if not tests:
        raise HTTPException(400, "This assignment has no test cases to run.")
    language = _pick_language(payload.language, assignment)
    if not sandbox_enabled():
        raise HTTPException(503, "Running code is not available right now.")

    try:
        left = limiter.start(student.id)
    except RunLimitError as exc:
        raise HTTPException(exc.status, exc.detail)
    try:
        filename = f"main{code_testing.LANGUAGES[language].extensions[0]}"
        with tempfile.TemporaryDirectory(prefix="student-run-") as folder:
            (Path(folder) / filename).write_bytes(payload.code.replace("\r\n", "\n").encode("utf-8"))
            run = code_testing.run_tests(Path(folder), tests, main_file=filename)
    except code_testing.CodeTestError as exc:
        raise HTTPException(400, str(exc))
    except SandboxUnavailable:
        raise HTTPException(503, "Running code is not available right now.")
    finally:
        limiter.finish(student.id)

    return _report(run.results, language, left)
