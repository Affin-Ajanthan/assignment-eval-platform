"""Students run their own code against the visible tests of a code challenge.

POST /assignments/{id}/sample-run takes the code the student has typed (it is
not a submission yet), runs it in the Docker sandbox against the VISIBLE test
cases only, and returns each test's expected and actual output. It is practice:
it never creates a submission or changes a mark.

Hidden tests never take part: they are not run and not mentioned beyond how
many there are. Every rule below is enforced here, whatever the page shows.

Each run starts Docker containers, so runs are limited: one at a time per
student, a number per hour per student, and a cap on runs at once across the
server.
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
    """Keeps sample runs from overloading the server. In memory, so the counts
    start again when the server restarts (the limits are about load, not marks)."""

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
                    429, f"You can run sample tests {self.per_hour} times per hour. Try again in {minutes} minute(s).")
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


class SampleRunIn(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    # Left out: the assignment's language (its first one when it allows several).
    language: Optional[Literal["python", "ruby"]] = None


class SampleResultOut(BaseModel):
    """One visible test's outcome. Deliberately without ids or points: nothing
    here can hint at the hidden tests."""

    name: str
    input: str
    match: str
    expected_output: str
    status: str  # passed | failed | error | timeout
    passed: bool
    actual_output: str
    stderr: str = ""


class SampleRunOut(BaseModel):
    language: str
    passed: int  # visible tests passed
    total: int  # visible tests run
    hidden_test_count: int  # not run here; they are used when the work is marked
    remaining_runs: int  # sample runs left this hour
    results: list[SampleResultOut]


def _pick_language(requested: Optional[str], assignment: Assignment) -> str:
    supported = list(code_testing.LANGUAGES)
    allowed = [lang for lang in (assignment.code_languages or supported) if lang in supported]
    if not allowed:
        raise HTTPException(400, "Sample tests can run Python and Ruby code only.")
    if requested is None:
        return allowed[0]
    if requested not in allowed:
        raise HTTPException(400, f"This assignment doesn't accept {requested} code.")
    return requested


@router.post("/assignments/{assignment_id}/sample-run", response_model=SampleRunOut)
def run_sample_tests(
    assignment_id: int, payload: SampleRunIn,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Run the typed code against the assignment's visible tests."""
    assignment = db.get(Assignment, assignment_id)
    now = utcnow_naive()
    if (not assignment or assignment.subject_id not in student_subject_ids(db, student)
            or assignment.status_at(now) == "upcoming"):
        raise HTTPException(404, "Assignment not found")
    if assignment.kind != "code_challenge":
        raise HTTPException(400, "Sample tests are only for code challenges.")
    if assignment.status_at(now) != "open":
        raise HTTPException(400, "This assignment is closed.")
    tests = assignment.test_cases or []
    visible = [t for t in tests if t.get("visible")]
    if not visible:
        raise HTTPException(400, "This assignment has no sample tests to run.")
    language = _pick_language(payload.language, assignment)
    if not sandbox_enabled():
        raise HTTPException(503, "Running code is not available right now.")

    try:
        left = limiter.start(student.id)
    except RunLimitError as exc:
        raise HTTPException(exc.status, exc.detail)
    try:
        filename = f"main{code_testing.LANGUAGES[language].extensions[0]}"
        with tempfile.TemporaryDirectory(prefix="sample-run-") as folder:
            (Path(folder) / filename).write_bytes(payload.code.replace("\r\n", "\n").encode("utf-8"))
            # Visible tests only, twice over: filtered above and again by the runner.
            run = code_testing.run_tests(Path(folder), visible, main_file=filename, only_visible=True)
    except code_testing.CodeTestError as exc:
        raise HTTPException(400, str(exc))
    except SandboxUnavailable:
        raise HTTPException(503, "Running code is not available right now.")
    finally:
        limiter.finish(student.id)

    results = [
        SampleResultOut(name=r.name, input=next((t["input"] for t in visible if t["id"] == r.test_id), ""),
                        match=r.match, expected_output=r.expected_output, status=r.status, passed=r.passed,
                        actual_output=r.actual_output, stderr=r.stderr)
        for r in run.results
    ]
    return SampleRunOut(
        language=language, passed=sum(1 for r in results if r.passed), total=len(results),
        hidden_test_count=len(tests) - len(visible), remaining_runs=left, results=results,
    )
