"""Students run their typed code against ALL of a code challenge's test cases, and submit it.

POST /assignments/{id}/run-code takes the code the student has typed (it is not
a submission yet), runs it in the Docker sandbox against every test case of the
challenge, visible and hidden, and tells the student only what they may know:

- how many test cases passed out of the total;
- a VISIBLE test failed: that test's expected output and actual output (plus the
  error message when the program crashed or ran out of time);
- a HIDDEN test failed: only how many did. Hidden tests' names, inputs and
  expected outputs never leave the server.

It is practice: it never creates a submission or changes a mark.

POST /assignments/{id}/submit-code hands the code in, and it is final. The code
is saved as the student's submission, run against every test case (the same run
and the same report as above), and the points of the tests passed are saved as
the mark. A code challenge cannot be edited or deleted afterwards (app/main.py
refuses PUT and DELETE /submissions/{id} for it). Submitting uses none of the
student's hourly runs, and when the server is busy it waits for a free place
instead of being refused. If the tests cannot be run at all (sandbox off or
down, an error) the code is still submitted, unmarked. The student can then ask
for the mark with POST /assignments/{id}/mark-my-code (it runs the same marking
on their saved code, which cannot have changed), or the instructor can mark it
with "Run and save as mark".

Every rule below is enforced here, whatever the page shows.

Each run starts Docker containers (one per test), so practice runs are limited:
one at a time per student, a number per hour per student, and a cap on runs at
once across the server. A submission's marking run counts towards that cap too,
and goes before new practice runs.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_student, student_subject_ids
from ..common import utcnow_naive
from ..db import BASE_DIR, UPLOAD_DIR, get_db
from ..evaluator import code_testing
from ..evaluator.code_execution import SandboxUnavailable, sandbox_enabled
from ..models import Assignment, Submission, User

router = APIRouter()
log = logging.getLogger(__name__)

RUNS_PER_HOUR = int(os.environ.get("CODE_SAMPLE_RUNS_PER_HOUR", "10"))
MAX_PARALLEL_RUNS = int(os.environ.get("CODE_SAMPLE_MAX_PARALLEL", "2"))
MAX_CODE_CHARS = 50_000
# How long a submission waits for a free place to be marked before it is left unmarked.
SUBMIT_WAIT_SECONDS = 120
_HOUR = 3600


class RunLimitError(Exception):
    """A run is refused: `status` is the HTTP status and `detail` is shown to the student."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class RunLimiter:
    """Keeps runs from overloading the server. In memory, so the counts start
    again when the server restarts (the limits are about load, not marks).

    A practice run is refused when a limit is reached. A submission's marking
    run (`marking`) is not: it uses none of the student's hourly runs and waits
    for a free place, because it happens once and the student cannot redo it."""

    def __init__(self, per_hour: int = RUNS_PER_HOUR, max_parallel: int = MAX_PARALLEL_RUNS,
                 clock: Callable[[], float] = time.monotonic, marking_wait: float = SUBMIT_WAIT_SECONDS):
        self.per_hour, self.max_parallel, self._clock = per_hour, max_parallel, clock
        self.marking_wait = marking_wait
        self._lock = threading.Condition()  # a lock that can also wake the submissions waiting for a place
        self._starts: dict[int, deque] = {}  # student id -> start times within the last hour
        self._active: set[int] = set()  # students with a practice run going
        self._marking = 0  # submissions being marked now
        self._waiting = 0  # submissions waiting for a place: they go before new practice runs

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
            if len(self._active) + self._marking + self._waiting >= self.max_parallel:
                raise RunLimitError(503, "The server is busy running other students' code. Try again in a moment.")
            starts.append(self._clock())
            self._active.add(student_id)
            return self.per_hour - len(starts)

    def finish(self, student_id: int) -> None:
        with self._lock:
            self._active.discard(student_id)
            self._lock.notify_all()

    @contextmanager
    def marking(self):
        """A place for a submission's marking run. Waits up to `marking_wait`
        seconds for one and raises RunLimitError if none frees up. Uses none of
        the student's hourly runs, and the one-run-at-a-time rule per student
        does not apply to it (the server-wide cap does)."""
        with self._lock:
            self._waiting += 1
            try:
                got_place = self._lock.wait_for(
                    lambda: len(self._active) + self._marking < self.max_parallel, timeout=self.marking_wait)
            finally:
                self._waiting = max(0, self._waiting - 1)
            if not got_place:
                raise RunLimitError(503, "The server is busy running other students' code. Try again in a moment.")
            self._marking += 1
        try:
            yield
        finally:
            with self._lock:
                self._marking = max(0, self._marking - 1)
                self._lock.notify_all()

    def remaining(self, student_id: int) -> int:
        with self._lock:
            return max(0, self.per_hour - len(self._recent(student_id)))

    def reset(self) -> None:
        with self._lock:
            self._starts.clear()
            self._active.clear()
            self._marking = self._waiting = 0
            self._lock.notify_all()


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


class SubmitOut(BaseModel):
    """What a student gets back from handing code in: the same report Run gives, and the mark."""

    submission_id: int
    marked: bool  # the tests ran and the mark is saved; False: submitted, to be marked later
    run: Optional[RunOut] = None  # None when the tests could not be run now
    # The mark: the points of the tests passed out of all the points. None before
    # the assignment's marks release date, and when the code was not marked.
    earned: Optional[float] = None
    total: Optional[float] = None


def _challenge_for(db: Session, student: User, assignment_id: int, what: str) -> Assignment:
    """The open code challenge this student may run or submit code to, or the HTTP error saying why not."""
    assignment = db.get(Assignment, assignment_id)
    now = utcnow_naive()
    if (not assignment or assignment.subject_id not in student_subject_ids(db, student)
            or assignment.status_at(now) == "upcoming"):
        raise HTTPException(404, "Assignment not found")
    if assignment.kind != "code_challenge":
        raise HTTPException(400, f"{what} is only for code challenges.")
    if assignment.status_at(now) != "open":
        raise HTTPException(400, "This assignment is closed.")
    if not assignment.test_cases:
        raise HTTPException(400, "This assignment has no test cases to run.")
    return assignment


def _main_filename(language: str) -> str:
    return f"main{code_testing.LANGUAGES[language].extensions[0]}"


@router.post("/assignments/{assignment_id}/run-code", response_model=RunOut)
def run_code(
    assignment_id: int, payload: RunIn,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Run the typed code against every test case of the assignment."""
    assignment = _challenge_for(db, student, assignment_id, "Running code")
    language = _pick_language(payload.language, assignment)
    if not sandbox_enabled():
        raise HTTPException(503, "Running code is not available right now.")

    try:
        left = limiter.start(student.id)
    except RunLimitError as exc:
        raise HTTPException(exc.status, exc.detail)
    try:
        filename = _main_filename(language)
        with tempfile.TemporaryDirectory(prefix="student-run-") as folder:
            (Path(folder) / filename).write_bytes(payload.code.replace("\r\n", "\n").encode("utf-8"))
            run = code_testing.run_tests(Path(folder), assignment.test_cases, main_file=filename)
    except code_testing.CodeTestError as exc:
        raise HTTPException(400, str(exc))
    except SandboxUnavailable:
        raise HTTPException(503, "Running code is not available right now.")
    finally:
        limiter.finish(student.id)

    return _report(run.results, language, left)


def _save_submission(db: Session, student: User, assignment: Assignment, filename: str, code: str) -> Submission:
    """Save the typed code as the student's submission, laid out like an upload: uploads/<id>/code/<file>."""
    folder = UPLOAD_DIR / uuid.uuid4().hex[:8] / "code"
    folder.mkdir(parents=True)
    try:
        (folder / filename).write_bytes(code.encode("utf-8"))
        submission = Submission(
            student_id=student.id, subject_id=assignment.subject_id, assignment_name=assignment.name,
            assignment_id=assignment.id, code_path=str(folder.relative_to(BASE_DIR)))
        db.add(submission)
        db.commit()
    except Exception:
        db.rollback()
        shutil.rmtree(folder.parent, ignore_errors=True)
        raise
    db.refresh(submission)
    return submission


def _mark(db: Session, student: User, assignment: Assignment, submission: Submission, main_file: str) -> SubmitOut:
    """Run every test case on the saved code (`main_file` is the file to run, "" to pick it) and save
    the points of the tests passed as the mark. When the tests cannot be run now the code stays
    submitted, without a mark: the student can ask for it again (mark_my_code) or the instructor can
    mark it. Never raises, because the submission is already saved."""
    unmarked = SubmitOut(submission_id=submission.id, marked=False)
    if not sandbox_enabled():
        log.warning("Submission %s was saved without a mark: the code sandbox is off", submission.id)
        return unmarked
    try:
        with limiter.marking():
            run = code_testing.run_tests(BASE_DIR / submission.code_path, assignment.test_cases, main_file=main_file)
        score = code_testing.score_run(run.results)
        submission.test_earned, submission.test_total = score.earned, score.total
        submission.tests_run_at = utcnow_naive()
        submission.status = "graded"
        db.commit()
    except (RunLimitError, SandboxUnavailable, code_testing.CodeTestError) as exc:
        log.warning("Submission %s was saved without a mark: %s", submission.id, exc)
        return unmarked
    except Exception:
        db.rollback()
        log.exception("Submission %s was saved without a mark: the tests failed unexpectedly", submission.id)
        return unmarked

    released = assignment.marks_released_at(utcnow_naive())
    return SubmitOut(
        submission_id=submission.id, marked=True, run=_report(run.results, run.language, limiter.remaining(student.id)),
        earned=score.earned if released else None, total=score.total if released else None)


@router.post("/assignments/{assignment_id}/submit-code", response_model=SubmitOut)
def submit_code(
    assignment_id: int, payload: RunIn,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Hand in the typed code. It is final: the code is saved as the student's
    submission, run against every test case, and the points of the tests passed
    are saved as the mark. It uses none of the student's hourly runs."""
    assignment = _challenge_for(db, student, assignment_id, "Submitting code")
    language = _pick_language(payload.language, assignment)
    already = db.query(Submission.id).filter(
        Submission.assignment_id == assignment.id, Submission.student_id == student.id).first()
    if already:
        raise HTTPException(409, "You have already submitted this code challenge. A submission can't be changed.")
    filename = _main_filename(language)
    submission = _save_submission(db, student, assignment, filename, payload.code.replace("\r\n", "\n"))
    return _mark(db, student, assignment, submission, filename)


@router.post("/assignments/{assignment_id}/mark-my-code", response_model=SubmitOut)
def mark_my_code(
    assignment_id: int,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Mark the student's own submitted code now, when it has no mark yet: the tests could not be run
    when they submitted it (Docker was off, the server was busy), or it was submitted before code was
    marked at once. The code cannot have changed since (a code challenge is final), so this gives the
    mark that Submit would have. It does not matter whether the deadline has passed."""
    assignment = db.get(Assignment, assignment_id)
    if (not assignment or assignment.subject_id not in student_subject_ids(db, student)
            or assignment.status_at(utcnow_naive()) == "upcoming"):
        raise HTTPException(404, "Assignment not found")
    if assignment.kind != "code_challenge":
        raise HTTPException(400, "Only a code challenge is marked from its tests.")
    if not assignment.test_cases:
        raise HTTPException(400, "This assignment has no test cases to run.")
    submission = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id, Submission.student_id == student.id)
        .order_by(Submission.id.desc())
        .first()
    )
    if submission is None or not submission.code_path:
        raise HTTPException(404, "You have not submitted code for this assignment.")
    if submission.marked_by_tests:
        raise HTTPException(409, "Your code is already marked.")
    return _mark(db, student, assignment, submission, assignment.test_main_file or "")
