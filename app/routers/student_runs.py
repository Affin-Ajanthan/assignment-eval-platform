"""Students run their typed code against ALL of a code challenge's test cases, and submit it.

A challenge has one or more TASKS, each with its own question and its own test cases
(app/models.py: Assignment.questions; the pages say task, the API and the database say
question). The student answers them on the challenge's own page, one task at a time: Run
checks one task's code, Submit hands that task in.

POST /assignments/{id}/run-code takes the code the student has typed for one task
(it is not a submission yet), runs it in the Docker sandbox against every test case of
that task, visible and hidden, and tells the student only what they may know:

- how many test cases passed out of the total;
- a VISIBLE test failed: that test's expected output and actual output (plus the
  error message when the program crashed or ran out of time);
- a HIDDEN test failed: only how many did. Hidden tests' names, inputs and
  expected outputs never leave the server.

It is practice: it never creates a submission or changes a mark.

POST /assignments/{id}/submit-code hands in the code of ONE task, and it is final.
The code is saved in the student's submission (the first task handed in creates it,
the others add a file to it) and run against every test case of that task (the same
run and the same report as above). The points of the tests passed are saved with the
answer, and the submission's mark is the points of all the answers' tests passed out of
the points of ALL the tasks' tests: a task not handed in yet earns nothing for
now, but its points are in the total. A task can be handed in only once, and a code
challenge cannot be edited or deleted afterwards (app/main.py refuses PUT and DELETE
/submissions/{id} for it). Submitting uses none of the student's hourly runs, and when
the server is busy it waits for a free place instead of being refused. If the tests
cannot be run at all (sandbox off or down, an error) the code is still submitted,
unmarked. The student can then ask for the mark with POST /assignments/{id}/mark-my-code
(it runs the same marking on the saved code of every answer that has no result yet,
which cannot have changed), or the instructor can mark it with "Run and save as mark".

GET /assignments/{id}/my-code gives back what the student has handed in so far, task
by task (the code, and the report each answer got), so the page can be reopened,
also after the deadline. app/code_answers.py keeps this per-task bookkeeping.

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

from .. import code_answers
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
MAX_CODE_CHARS = 50_000  # per task
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


class AnswerIn(BaseModel):
    """The code a student typed for one task."""

    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    # Left out: the assignment's language (its first one when it allows several).
    language: Optional[Literal["python", "ruby"]] = None
    # The task it answers (1 is the first). Left out: the first, the only task of most challenges.
    question: int = Field(default=1, ge=1)


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


class QuestionResultOut(BaseModel):
    """The student's answer to one task, and how it did."""

    question: int  # the task's number, from 1
    title: str  # blank for the only task of a challenge made without titles
    submitted: bool  # False: not handed in (yet), so none of its test cases pass
    marked: bool = False  # its tests ran and its result is saved; False for an answer to be marked later
    language: Optional[str] = None
    code: Optional[str] = None  # the code that was handed in, to show it back
    run: Optional[RunOut] = None  # the same report Run gives; None when it is not marked
    # What the answer earned: the points of its tests passed out of the points of all its tests. None
    # before the assignment's marks release date, and when it is not marked.
    earned: Optional[float] = None
    total: Optional[float] = None


class CodeWorkOut(BaseModel):
    """What a student has handed in for a code challenge, task by task, and the mark so far."""

    submission_id: Optional[int] = None  # None until the first task is handed in
    marked: bool  # at least one answer is marked, so there is a mark
    complete: bool  # every task is handed in
    questions: list[QuestionResultOut]  # one per task, in order
    # The mark so far: the points of the tests passed out of the points of ALL the tasks' tests, so a
    # task not handed in yet earns nothing for now. None before the assignment's marks release date,
    # and when nothing is marked.
    earned: Optional[float] = None
    total: Optional[float] = None


def _visible_challenge(db: Session, student: User, assignment_id: int, what: str) -> Assignment:
    """The code challenge this student can see (it has opened, open or closed), or the HTTP error saying why not."""
    assignment = db.get(Assignment, assignment_id)
    if (not assignment or assignment.subject_id not in student_subject_ids(db, student)
            or assignment.status_at(utcnow_naive()) == "upcoming"):
        raise HTTPException(404, "Assignment not found")
    if assignment.kind != "code_challenge":
        raise HTTPException(400, f"{what} is only for code challenges.")
    return assignment


def _challenge_for(db: Session, student: User, assignment_id: int, what: str) -> Assignment:
    """The open code challenge this student may run or submit code to, or the HTTP error saying why not."""
    assignment = _visible_challenge(db, student, assignment_id, what)
    if assignment.status_at(utcnow_naive()) != "open":
        raise HTTPException(400, "This assignment is closed.")
    if not assignment.test_cases:
        raise HTTPException(400, "This assignment has no test cases to run.")
    return assignment


def _question_of(assignment: Assignment, number: int) -> dict:
    question = next((q for q in assignment.questions if q["id"] == number), None)
    if question is None:
        raise HTTPException(404, "Task not found")
    return question


@router.post("/assignments/{assignment_id}/run-code", response_model=RunOut)
def run_code(
    assignment_id: int, payload: AnswerIn,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Run the typed code against every test case of its task."""
    assignment = _challenge_for(db, student, assignment_id, "Running code")
    question = _question_of(assignment, payload.question)
    language = _pick_language(payload.language, assignment)
    if not sandbox_enabled():
        raise HTTPException(503, "Running code is not available right now.")

    try:
        left = limiter.start(student.id)
    except RunLimitError as exc:
        raise HTTPException(exc.status, exc.detail)
    try:
        filename = code_testing.answer_filename(len(assignment.questions), question["id"], language)
        with tempfile.TemporaryDirectory(prefix="student-run-") as folder:
            (Path(folder) / filename).write_bytes(payload.code.replace("\r\n", "\n").encode("utf-8"))
            run = code_testing.run_tests(Path(folder), assignment.tests_of(question["id"]), main_file=filename)
    except code_testing.CodeTestError as exc:
        raise HTTPException(400, str(exc))
    except SandboxUnavailable:
        raise HTTPException(503, "Running code is not available right now.")
    finally:
        limiter.finish(student.id)

    return RunOut(**code_answers.student_report(run.results, language), remaining_runs=left)


def _latest_submission(db: Session, student: User, assignment: Assignment) -> Optional[Submission]:
    """The student's submission to the assignment: the one every task they hand in goes into."""
    return (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id, Submission.student_id == student.id)
        .order_by(Submission.id.desc())
        .first()
    )


def _save_answer(db: Session, student: User, assignment: Assignment, submission: Optional[Submission],
                 question: int, filename: str, language: str, code: str) -> Submission:
    """Save the code as the answer to a task, laid out like an upload: uploads/<id>/code/<file>.
    The first answer creates the student's submission, the others add a file to its folder. The answer is
    remembered, with no result yet."""
    created = submission is None
    folder = UPLOAD_DIR / uuid.uuid4().hex[:8] / "code" if created else BASE_DIR / submission.code_path
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    try:
        path.write_bytes(code.encode("utf-8"))
        if created:
            submission = Submission(
                student_id=student.id, subject_id=assignment.subject_id, assignment_name=assignment.name,
                assignment_id=assignment.id, code_path=str(folder.relative_to(BASE_DIR)), question_results=[])
            db.add(submission)
        code_answers.add_answer(assignment, submission, question, filename, language)
        db.commit()
    except Exception:
        db.rollback()
        if created:
            shutil.rmtree(folder.parent, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        raise
    db.refresh(submission)
    return submission


def _mark_answers(db: Session, assignment: Assignment, submission: Submission, questions: list[dict]) -> bool:
    """Run the test cases of these questions on their saved answers and save how they did, and the new mark.
    Returns whether that worked. When the tests cannot be run now the answers stay handed in, without a
    result: the student can ask for it again (mark_my_code) or the instructor can mark the submission.
    Never raises, because the answers are already saved."""
    if not sandbox_enabled():
        log.warning("Submission %s was saved without a mark: the code sandbox is off", submission.id)
        return False
    files = {a["question"]: a["file"] or "" for a in code_answers.answers_of(assignment, submission)}
    try:
        with limiter.marking():
            runs = [code_testing.run_question(BASE_DIR / submission.code_path, q, assignment.test_cases,
                                              file=files.get(q["id"], ""))
                    for q in questions]
        code_answers.record_runs(assignment, submission, runs, now=utcnow_naive())
        db.commit()
    except (RunLimitError, SandboxUnavailable, code_testing.CodeTestError) as exc:
        log.warning("Submission %s was saved without a mark: %s", submission.id, exc)
        return False
    except Exception:
        db.rollback()
        log.exception("Submission %s was saved without a mark: the tests failed unexpectedly", submission.id)
        return False
    return True


def _read_code(submission: Submission, file: Optional[str]) -> Optional[str]:
    """The text of a saved answer, or None when its file is not there."""
    if not file or not submission.code_path:
        return None
    root = (BASE_DIR / submission.code_path).resolve()
    path = (root / file).resolve()
    if root not in path.parents or not path.is_file():
        return None
    with path.open(encoding="utf-8", errors="replace") as handle:
        return handle.read(MAX_CODE_CHARS)


def _work_out(student: User, assignment: Assignment, submission: Optional[Submission]) -> CodeWorkOut:
    """What the student has handed in for the challenge, with each answer's report and the mark so far.
    A mark (a task's or the whole) is left out before the assignment's marks release date; the
    report of a task's test cases is not."""
    released = assignment.marks_released_at(utcnow_naive())
    runs_left = limiter.remaining(student.id)
    answers = {a["question"]: a for a in code_answers.answers_of(assignment, submission)}
    questions = []
    for q in assignment.questions:
        answer = answers.get(q["id"])
        if answer is None:
            questions.append(QuestionResultOut(question=q["id"], title=q["title"], submitted=False))
            continue
        marked = bool(answer["marked"])
        questions.append(QuestionResultOut(
            question=q["id"], title=q["title"], submitted=True, marked=marked, language=answer.get("language"),
            code=_read_code(submission, answer.get("file")),
            run=RunOut(**answer["report"], remaining_runs=runs_left) if marked and answer.get("report") else None,
            earned=answer.get("earned") if marked and released else None,
            total=answer.get("total") if marked and released else None))
    marked_any = submission is not None and submission.marked_by_tests
    return CodeWorkOut(
        submission_id=submission.id if submission else None, marked=marked_any,
        complete=all(q.submitted for q in questions), questions=questions,
        earned=submission.test_earned if marked_any and released else None,
        total=submission.test_total if marked_any and released else None)


@router.get("/assignments/{assignment_id}/my-code", response_model=CodeWorkOut)
def my_code(
    assignment_id: int,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """What the student has handed in so far for a code challenge, task by task, with the
    report each answer got and the mark so far. It works after the deadline too."""
    assignment = _visible_challenge(db, student, assignment_id, "Your code answers are")
    return _work_out(student, assignment, _latest_submission(db, student, assignment))


@router.post("/assignments/{assignment_id}/submit-code", response_model=CodeWorkOut)
def submit_code(
    assignment_id: int, payload: AnswerIn,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Hand in the code of ONE task. It is final: the code is saved as the student's answer to that
    task, run against every test case of the task, and the points of the tests passed are saved
    with it. Returns what the student has handed in so far, this answer's report included. It uses none
    of the student's hourly runs. The other tasks can be handed in afterwards, each once."""
    assignment = _challenge_for(db, student, assignment_id, "Submitting code")
    question = _question_of(assignment, payload.question)
    language = _pick_language(payload.language, assignment)
    submission = _latest_submission(db, student, assignment)
    if submission is not None:
        if submission.question_results is None:
            # Made before answers were kept one by one, or uploaded as files: it is complete as it stands.
            raise HTTPException(409, "You have already submitted this code challenge. A submission can't be changed.")
        if any(a["question"] == question["id"] for a in submission.question_results):
            raise HTTPException(409, (
                f"You have already submitted task {question['id']}. A submission can't be changed."
                if len(assignment.questions) > 1 else
                "You have already submitted this code challenge. A submission can't be changed."))
    filename = code_testing.answer_filename(len(assignment.questions), question["id"], language)
    submission = _save_answer(db, student, assignment, submission, question["id"], filename, language,
                              payload.code.replace("\r\n", "\n"))
    _mark_answers(db, assignment, submission, [question])
    return _work_out(student, assignment, submission)


@router.post("/assignments/{assignment_id}/mark-my-code", response_model=CodeWorkOut)
def mark_my_code(
    assignment_id: int,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Mark the student's own handed-in answers that have no result yet, now: the tests could not be run
    when they handed them in (Docker was off, the server was busy), or the submission was made before code
    was marked at once. The code cannot have changed since (a code challenge is final), so this gives the
    result that Submit would have. It does not matter whether the deadline has passed. Returns what the
    student has handed in, as my_code does: an answer whose tests still could not run has no result."""
    assignment = _visible_challenge(db, student, assignment_id, "Getting marks")
    if not assignment.test_cases:
        raise HTTPException(400, "This assignment has no test cases to run.")
    submission = _latest_submission(db, student, assignment)
    if submission is None or not submission.code_path:
        raise HTTPException(404, "You have not submitted code for this assignment.")
    waiting = {a["question"] for a in code_answers.answers_of(assignment, submission) if not a["marked"]}
    if not waiting:
        raise HTTPException(409, "Your code is already marked.")
    _mark_answers(db, assignment, submission, [q for q in assignment.questions if q["id"] in waiting])
    return _work_out(student, assignment, submission)
