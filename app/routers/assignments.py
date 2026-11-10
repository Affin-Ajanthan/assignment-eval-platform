"""Assignments: creating, editing and listing them, starter code and report templates.

Moved out of app/main.py (Assignments). Included in app/main.py."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import code_answers as _code_answers, code_languages as _langs
from ..auth import get_current_user, instructor_subject_ids, require_instructor, require_student, student_subject_ids
from ..common import (
    CODE_EXTENSIONS as _CODE_EXTENSIONS,
    as_utc as _as_utc,
    instructor_assignment as _instructor_assignment,
    norm_name as _norm_name,
    on_flag as _on,
    utcnow_naive as _utcnow_naive,
)
from ..db import get_db
from ..evaluator.document_extraction import report_max_bytes
from ..models import (
    Assignment,
    Grade,
    Rubric,
    SimilarityFlag,
    Subject,
    Submission,
    SUBMISSION_TYPES,
    TaskStart,
    TaskUnlock,
    User,
)
from ..route_helpers import _clean_name, _marks_released
from ..schemas import (
    AssignmentIn,
    AssignmentOut,
    AssignmentUpdate,
    CriterionMarkOut,
    MySubmissionOut,
    QuestionIn,
    QuestionOut,
    StudentAssignmentOut,
    TestCaseIn,
    TestCaseOut,
    UpcomingAssignmentOut,
)
from ..similarity import report_similarity as _report_sim


router = APIRouter()


#
# Times are stored as naive UTC, like every other timestamp in this app, and
# returned with an explicit UTC offset so browsers show them in local time.
# The submission window is enforced here, in the API:
#   now < available_from  -> not available (students don't even see it)
#   available_from <= now <= deadline -> submissions allowed
#   now > deadline -> submissions, edits and deletions rejected

def _to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _validate_window(available_from: datetime, deadline: datetime) -> None:
    if deadline <= available_from:
        raise HTTPException(400, "The submission deadline must be later than the available-from date and time.")


def _clean_late_until(late_until: Optional[datetime], deadline: datetime) -> Optional[datetime]:
    """The date until which late work is taken, as naive UTC, or None. It can't be before the deadline."""
    if late_until is None:
        return None
    until = _to_naive_utc(late_until)
    if until < deadline:
        raise HTTPException(400, "Accept late submissions until a date after the deadline.")
    return until


def _check_assignment_rubric(db: Session, subject_id: int, rubric_id: Optional[int]) -> None:
    if rubric_id is None:
        return
    rubric = db.get(Rubric, rubric_id)
    if not rubric or rubric.subject_id != subject_id:
        raise HTTPException(400, "That rubric doesn't belong to this assignment's subject")


def _require_unique_assignment_name(db: Session, subject_id: int, name: str, exclude_id: Optional[int] = None) -> None:
    for other in db.query(Assignment).filter(Assignment.subject_id == subject_id).all():
        if other.id != exclude_id and _norm_name(other.name) == _norm_name(name):
            raise HTTPException(409, f"An assignment named '{other.name}' already exists in this subject")


def _assignment_out(db: Session, a: Assignment) -> AssignmentOut:
    subs = db.query(Submission).filter(Submission.assignment_id == a.id).all()
    return AssignmentOut(
        id=a.id, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
        name=a.name, description=a.description or "",
        available_from=_as_utc(a.available_from), deadline=_as_utc(a.deadline),
        status=a.status_at(_utcnow_naive()),
        rubric_id=a.rubric_id, rubric_name=a.rubric.name if a.rubric else None,
        max_points=a.rubric.max_total if a.rubric else None,
        submission_types=a.accepted_types(),
        submission_count=len(subs), graded_count=sum(1 for s in subs if s.status == "graded"),
        created_at=_as_utc(a.created_at), updated_at=_as_utc(a.updated_at),
        starter_code=a.starter_code or "", starter_code_filename=a.starter_code_filename or "",
        report_template_filename=a.report_template_filename or "",
        report_template_words=len((a.report_template_text or "").split()),
        code_languages=a.code_languages or [],
        student_similarity_check=_on(a.student_similarity_check),
        student_ai_check=_on(a.student_ai_check),
        ignore_common_code=_on(a.ignore_common_code),
        marks_release_at=_as_utc(a.marks_release_at),
        marks_released=a.marks_released_at(_utcnow_naive()),
        test_cases=[TestCaseOut(**t) for t in a.test_cases or []],
        questions=[QuestionOut(**q) for q in a.questions],
        test_main_file=a.test_main_file or "",
        assignment_type=a.kind,
        task_password=(a.task_password or "") if a.kind == "code_challenge" else "",
        tasks_in_order=_on(a.tasks_in_order) if a.kind == "code_challenge" else False,
        late_grace_minutes=a.late_grace_minutes or 0, late_until=_as_utc(a.late_until),
        late_penalty_percent=a.late_penalty_percent or 0,
        late_penalty_max_percent=100 if a.late_penalty_max_percent is None else a.late_penalty_max_percent,
        late_penalty_unit=a.late_penalty_unit or "percent", late_penalty_marks=a.late_penalty_marks or 0,
        late_penalty_max_marks=a.late_penalty_max_marks,
        late_count=sum(1 for s in subs if s.late_seconds is not None),
    )


def _assignment_kind(payload: AssignmentIn) -> str:
    """The type of a new assignment, checked against its other fields. A code
    challenge accepts code only and needs at least one test case; test cases
    belong to code challenges only. Without an explicit type, test cases make
    it a code challenge."""
    kind = payload.assignment_type or ("code_challenge" if payload.test_cases else "submission")
    if kind == "code_challenge":
        if payload.rubric_id is not None:
            raise HTTPException(400, "A code challenge is marked by its test cases, not by a rubric.")
        if "submission_types" in payload.model_fields_set and list(set(payload.submission_types)) != ["code"]:
            raise HTTPException(400, "A code challenge accepts code submissions only.")
        if not payload.test_cases:
            raise HTTPException(400, "A code challenge needs at least one test case.")
    elif payload.test_cases or payload.questions:
        raise HTTPException(400, "Test cases and tasks belong to code challenges: choose the code challenge type.")
    return kind


def _clean_questions(questions: list[QuestionIn]) -> Optional[list[dict]]:
    """Number the tasks 1, 2, ... and title blank ones "Task N" (a lone task keeps a blank title, as a
    challenge made without tasks has). None when there are no tasks."""
    if not questions:
        return None
    return [
        {"id": n, "title": q.title.strip() or (f"Task {n}" if len(questions) > 1 else ""),
         "statement": q.statement.strip(), "starter_code": q.starter_code if q.starter_code.strip() else "",
         "time_limit_seconds": q.time_limit_seconds}
        for n, q in enumerate(questions, start=1)
    ]


def _number_tests(tests: list[TestCaseIn]) -> list[dict]:
    """Number the tests 1, 2, ... question by question (the order inside a question is kept) and
    name blank ones "Test N", N counting within the question."""
    counts: dict[int, int] = {}
    numbered = []
    for n, t in enumerate(sorted(tests, key=lambda test: test.question), start=1):
        counts[t.question] = counts.get(t.question, 0) + 1
        numbered.append({**t.model_dump(), "id": n, "name": t.name.strip() or f"Test {counts[t.question]}"})
    return numbered


def _check_question_tests(tests: list[dict], question_count: int) -> None:
    """Every test belongs to a task that exists, and every task has a test."""
    for t in tests:
        if t.get("question", 1) > question_count:
            raise HTTPException(
                400, f"The test case '{t['name']}' belongs to task {t['question']}, but this assignment "
                     f"has only {question_count} task{'' if question_count == 1 else 's'}.")
    for q in range(1, question_count + 1):
        if not any(t.get("question", 1) == q for t in tests):
            raise HTTPException(400, f"Task {q} needs at least one test case.")


def _clean_test_cases(tests: list[TestCaseIn], accepted_types: list[str], question_count: int = 1) -> Optional[list[dict]]:
    """Number the tests and check them against the challenge's questions. Tests run on
    submitted code, so they need an assignment that accepts code. None when
    there are no tests."""
    if not tests:
        return None
    if "code" not in accepted_types:
        raise HTTPException(400, "Test cases need an assignment that accepts code submissions.")
    numbered = _number_tests(tests)
    _check_question_tests(numbered, question_count)
    return numbered


def _update_questions_and_tests(db: Session, assignment: Assignment, payload: AssignmentUpdate) -> None:
    """Apply new questions and/or test cases to a code challenge, keeping the two consistent: the tests
    are checked against the questions that will exist afterwards, whichever of the two was sent."""
    if payload.test_cases is not None and not payload.test_cases:
        raise HTTPException(400, "A code challenge needs at least one test case.")
    questions = _clean_questions(payload.questions) if payload.questions is not None else assignment.code_questions
    count = len(questions or [1])
    if count != len(assignment.questions):
        # A submission keeps one file per task, so tasks can't be added or removed afterwards.
        if db.query(Submission.id).filter(Submission.assignment_id == assignment.id).first():
            raise HTTPException(
                409, "The number of tasks can't be changed after students have submitted to this assignment.")
    if payload.test_cases is not None:
        tests = _clean_test_cases(payload.test_cases, assignment.accepted_types(), count)
    else:
        tests = assignment.test_cases or []
        _check_question_tests(tests, count)
    assignment.code_questions, assignment.test_cases = questions, tests


def _clean_starter_code(code: str, filename: str) -> tuple[Optional[str], Optional[str]]:
    """Blank code means no starter code. Otherwise the file name must carry
    a code extension the similarity check reads, since that's what decides
    which submitted files the starter is subtracted from."""
    if not code.strip():
        return None, None
    filename = Path(filename.strip()).name
    if Path(filename).suffix.lower() not in _CODE_EXTENSIONS:
        raise HTTPException(
            400, "Starter code needs a file name ending in a code extension "
                 f"({', '.join(sorted(_CODE_EXTENSIONS))}), e.g. starter.py",
        )
    return code, filename


def _criterion_marks(grade: Grade | None) -> list[CriterionMarkOut]:
    """The grade's per-criterion marks in the rubric's order; empty for a
    "Final mark only" grade (it has no per-criterion marks)."""
    if grade is None or not grade.criterion_scores or grade.rubric is None:
        return []
    return [
        CriterionMarkOut(name=c["name"], score=grade.criterion_scores[c["name"]], max_points=c["max_points"])
        for c in grade.rubric.criteria
        if c["name"] in grade.criterion_scores
    ]


def _is_code_challenge(submission: Submission) -> bool:
    return submission.assignment is not None and submission.assignment.kind == "code_challenge"


def _my_submission_out(submission: Submission, assignment_open: bool, now: datetime) -> MySubmissionOut:
    # The code of a code challenge cannot be replaced once handed in (it is marked from its tests at once), but
    # the whole submission can be deleted while the assignment is open, unless the instructor graded it.
    # Other work can be changed or deleted until the deadline or until it is graded.
    challenge = _is_code_challenge(submission)
    can_edit = assignment_open and submission.status != "graded" and not challenge
    # A challenge with time limits is final: doing it again would start every clock over.
    can_delete = assignment_open and (
        submission.latest_grade is None and not submission.assignment.is_timed if challenge
        else submission.status != "graded")
    common = dict(
        id=submission.id, submitted_at=_as_utc(submission.submitted_at),
        has_code=bool(submission.code_path), has_report=bool(submission.report_path),
        has_video=bool(submission.video_path), can_edit=can_edit, can_delete=can_delete,
        questions_submitted=_code_answers.answer_count(submission.assignment, submission)
        if _is_code_challenge(submission) else 0,
        late_seconds=submission.late_seconds, late_penalty_percent=submission.late_penalty_percent or 0,
        late_penalty_marks=submission.late_penalty_marks or 0,
    )
    if not _marks_released(submission, now):
        return MySubmissionOut(**common, status="submitted", final_mark=None, max_mark=None)
    grade = submission.latest_grade
    return MySubmissionOut(
        **common, status=submission.status,
        final_mark=submission.final_mark, max_mark=submission.max_mark, raw_mark=submission.raw_mark,
        criterion_marks=_criterion_marks(grade),
        feedback=grade.feedback if grade else None,
    )


def _student_assignment_out(db: Session, student: User, a: Assignment, now: datetime) -> StudentAssignmentOut:
    status = a.status_at(now)
    past_deadline = status == "closed"
    if past_deadline and a.accepts_at(now):
        status = "open"  # late work is still taken: the page treats the assignment as open (see `past_deadline`)
    mine = (
        db.query(Submission)
        .filter(Submission.assignment_id == a.id, Submission.student_id == student.id)
        .order_by(Submission.id.desc())
        .first()
    )
    unlocked = _code_answers.tasks_unlocked(db, student.id, a)
    return StudentAssignmentOut(
        id=a.id, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
        name=a.name, description=a.description or "",
        available_from=_as_utc(a.available_from), deadline=_as_utc(a.deadline), status=status,
        assignment_type=a.kind,
        submission_types=a.accepted_types(),
        code_languages=a.code_languages or [],
        student_similarity_check=_on(a.student_similarity_check),
        student_ai_check=_on(a.student_ai_check),
        marks_release_at=None if a.marks_released_at(now) else _as_utc(a.marks_release_at),
        # Behind the password only the titles are shown: the questions and starting code come after it is entered.
        questions=[QuestionOut(**(q if unlocked else {**q, "statement": "", "starter_code": ""})) for q in a.questions],
        has_task_password=a.requires_password,
        tasks_unlocked=unlocked,
        tasks_in_order=_on(a.tasks_in_order) if a.kind == "code_challenge" else False,
        past_deadline=past_deadline,
        accept_until=_as_utc(a.accept_until) if a.accept_until > a.deadline else None,
        late_grace_minutes=a.late_grace_minutes or 0,
        late_penalty_percent=a.late_penalty_percent or 0,
        late_penalty_max_percent=100 if a.late_penalty_max_percent is None else a.late_penalty_max_percent,
        late_penalty_unit=a.late_penalty_unit or "percent", late_penalty_marks=a.late_penalty_marks or 0,
        late_penalty_max_marks=a.late_penalty_max_marks,
        penalty_now_percent=a.lateness_at(now)[1], penalty_now_marks=a.lateness_at(now)[2],
        my_submission=_my_submission_out(mine, status == "open", now) if mine else None,
    )


@router.post("/assignments", response_model=AssignmentOut)
def create_assignment(payload: AssignmentIn, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    if payload.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    name = _clean_name(payload.name, "Assignment name")
    available_from, deadline = _to_naive_utc(payload.available_from), _to_naive_utc(payload.deadline)
    _validate_window(available_from, deadline)
    _require_unique_assignment_name(db, payload.subject_id, name)
    _check_assignment_rubric(db, payload.subject_id, payload.rubric_id)
    starter_code, starter_filename = _clean_starter_code(payload.starter_code, payload.starter_code_filename)
    kind = _assignment_kind(payload)
    types = ["code"] if kind == "code_challenge" else _normalise_submission_types(payload.submission_types)
    questions = _clean_questions(payload.questions)
    assignment = Assignment(
        assignment_type=kind,
        subject_id=payload.subject_id, name=name, description=payload.description.strip(),
        available_from=available_from, deadline=deadline, rubric_id=payload.rubric_id,
        submission_types=types, starter_code=starter_code, starter_code_filename=starter_filename,
        code_languages=_langs.normalise_languages(payload.code_languages),
        student_similarity_check=payload.student_similarity_check,
        student_ai_check=payload.student_ai_check,
        ignore_common_code=payload.ignore_common_code,
        marks_release_at=_to_naive_utc(payload.marks_release_at) if payload.marks_release_at else None,
        test_cases=_clean_test_cases(payload.test_cases, types, len(questions or [1])),
        code_questions=questions,
        test_main_file=payload.test_main_file.strip() or None,
        task_password=(payload.task_password.strip() or None) if kind == "code_challenge" else None,
        tasks_in_order=payload.tasks_in_order and kind == "code_challenge",
        late_grace_minutes=payload.late_grace_minutes, late_until=_clean_late_until(payload.late_until, deadline),
        late_penalty_percent=payload.late_penalty_percent, late_penalty_max_percent=payload.late_penalty_max_percent,
        late_penalty_unit=payload.late_penalty_unit, late_penalty_marks=payload.late_penalty_marks,
        late_penalty_max_marks=payload.late_penalty_max_marks,
        created_by_id=instructor.id,
    )
    db.add(assignment)
    db.flush()
    # Submissions made before assignments existed were free-text names; ones
    # matching this assignment in this subject are linked to it.
    for legacy in db.query(Submission).filter(Submission.subject_id == payload.subject_id,
                                              Submission.assignment_id.is_(None)).all():
        if _norm_name(legacy.assignment_name) == _norm_name(name):
            legacy.assignment_id = assignment.id
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@router.get("/assignments")
def list_assignments(
    subject_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Instructors: every assignment in their subjects (AssignmentOut).
    Students: assignments in their enrolled subjects that have opened --
    open and closed, never upcoming -- with only their own submission and
    final mark (StudentAssignmentOut)."""
    if user.role == "student":
        allowed = student_subject_ids(db, user)
    elif user.role == "instructor":
        allowed = instructor_subject_ids(db, user)
    else:
        allowed = {s.id for s in db.query(Subject).all()}
    if subject_id is not None:
        if subject_id not in allowed:
            raise HTTPException(403, "You don't have access to this subject")
        allowed = {subject_id}
    query = db.query(Assignment).filter(Assignment.subject_id.in_(allowed)).order_by(Assignment.deadline)
    now = _utcnow_naive()
    if user.role == "student":
        visible = query.filter(Assignment.available_from <= now).all()
        return [_student_assignment_out(db, user, a, now) for a in visible]
    return [_assignment_out(db, a) for a in query.all()]


@router.get("/upcoming-assignments", response_model=list[UpcomingAssignmentOut])
def list_upcoming_assignments(student: User = Depends(require_student), db: Session = Depends(get_db)):
    """The not-yet-open assignments of the student's subjects, soonest first. GET /assignments still lists
    only opened ones, and an upcoming assignment's own page stays 404 until it opens."""
    now = _utcnow_naive()
    upcoming = (db.query(Assignment)
                .filter(Assignment.subject_id.in_(student_subject_ids(db, student)), Assignment.available_from > now)
                .order_by(Assignment.available_from).all())
    return [UpcomingAssignmentOut(name=a.name, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
                                  assignment_type=a.kind, available_from=_as_utc(a.available_from),
                                  deadline=_as_utc(a.deadline))
            for a in upcoming]


@router.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = db.get(Assignment, assignment_id)
    now = _utcnow_naive()
    if user.role == "student":
        if (not assignment or assignment.subject_id not in student_subject_ids(db, user)
                or assignment.status_at(now) == "upcoming"):
            raise HTTPException(404, "Assignment not found")
        return _student_assignment_out(db, user, assignment, now)
    if user.role == "instructor":
        return _assignment_out(db, _instructor_assignment(db, user, assignment_id))
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return _assignment_out(db, assignment)


@router.put("/assignments/{assignment_id}", response_model=AssignmentOut)
def update_assignment(
    assignment_id: int, payload: AssignmentUpdate,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    assignment = _instructor_assignment(db, instructor, assignment_id)
    if payload.name is not None:
        name = _clean_name(payload.name, "Assignment name")
        _require_unique_assignment_name(db, assignment.subject_id, name, exclude_id=assignment.id)
    else:
        name = assignment.name
    available_from = _to_naive_utc(payload.available_from) if payload.available_from else assignment.available_from
    deadline = _to_naive_utc(payload.deadline) if payload.deadline else assignment.deadline
    _validate_window(available_from, deadline)
    if "rubric_id" in payload.model_fields_set:
        if assignment.kind == "code_challenge" and payload.rubric_id is not None:
            raise HTTPException(400, "A code challenge is marked by its test cases, not by a rubric.")
        _check_assignment_rubric(db, assignment.subject_id, payload.rubric_id)
        assignment.rubric_id = payload.rubric_id
    if payload.submission_types is not None:
        types = _normalise_submission_types(payload.submission_types)
        if assignment.kind == "code_challenge" and types != ["code"]:
            raise HTTPException(400, "A code challenge accepts code submissions only.")
        if types != assignment.accepted_types():
            has_submissions = db.query(Submission.id).filter(Submission.assignment_id == assignment.id).first()
            if has_submissions:
                raise HTTPException(
                    409, "The accepted submission types can't be changed after students have submitted to this assignment.")
            assignment.submission_types = types
    # The self-check switches never lock: the instructor may turn them on or
    # off at any time (e.g. off for the last day before the deadline).
    if payload.student_similarity_check is not None:
        assignment.student_similarity_check = payload.student_similarity_check
    if payload.student_ai_check is not None:
        assignment.student_ai_check = payload.student_ai_check
    if payload.ignore_common_code is not None:
        assignment.ignore_common_code = payload.ignore_common_code
    # Like the self-check switches, the release date can change at any time;
    # an explicit null releases the marks straight away.
    if "marks_release_at" in payload.model_fields_set:
        release = payload.marks_release_at
        assignment.marks_release_at = _to_naive_utc(release) if release else None
    # Tests can be changed at any time (e.g. to fix an expected output); the
    # list is replaced as a whole. Checked against the types as saved above.
    if payload.test_main_file is not None:
        assignment.test_main_file = payload.test_main_file.strip() or None
    # The password and the order can change at any time (a student who has entered the password stays in).
    if assignment.kind == "code_challenge":
        if payload.task_password is not None:
            assignment.task_password = payload.task_password.strip() or None
        if payload.tasks_in_order is not None:
            assignment.tasks_in_order = payload.tasks_in_order
    if payload.test_cases is not None or payload.questions is not None:
        if assignment.kind == "code_challenge":
            _update_questions_and_tests(db, assignment, payload)
        elif payload.test_cases or payload.questions:
            raise HTTPException(400, "Test cases and tasks belong to code challenges: choose the code challenge type.")
    if payload.code_languages is not None:
        languages = _langs.normalise_languages(payload.code_languages)
        if languages != (assignment.code_languages or None):
            has_submissions = db.query(Submission.id).filter(Submission.assignment_id == assignment.id).first()
            if has_submissions:
                raise HTTPException(
                    409, "The required programming language can't be changed after students have submitted "
                         "to this assignment.")
            assignment.code_languages = languages

    if name != assignment.name:
        # Keep linked submissions and stored similarity results under the new
        # name, so the similarity check still groups them together.
        db.query(Submission).filter(Submission.assignment_id == assignment.id).update(
            {Submission.assignment_name: name})
        db.query(SimilarityFlag).filter(
            SimilarityFlag.subject_id == assignment.subject_id, SimilarityFlag.assignment_name == assignment.name
        ).update({SimilarityFlag.assignment_name: name})
        assignment.name = name
    if payload.description is not None:
        assignment.description = payload.description.strip()
    if payload.starter_code is not None or payload.starter_code_filename is not None:
        # Either field may be sent alone; the other keeps its stored value.
        code = payload.starter_code if payload.starter_code is not None else (assignment.starter_code or "")
        filename = (payload.starter_code_filename if payload.starter_code_filename is not None
                    else (assignment.starter_code_filename or ""))
        assignment.starter_code, assignment.starter_code_filename = _clean_starter_code(code, filename)
    # The late rules can change at any time; work already handed in keeps the penalty it got.
    if payload.late_grace_minutes is not None:
        assignment.late_grace_minutes = payload.late_grace_minutes
    if payload.late_penalty_percent is not None:
        assignment.late_penalty_percent = payload.late_penalty_percent
    if payload.late_penalty_max_percent is not None:
        assignment.late_penalty_max_percent = payload.late_penalty_max_percent
    if payload.late_penalty_unit is not None:
        assignment.late_penalty_unit = payload.late_penalty_unit
    if payload.late_penalty_marks is not None:
        assignment.late_penalty_marks = payload.late_penalty_marks
    if "late_penalty_max_marks" in payload.model_fields_set:
        assignment.late_penalty_max_marks = payload.late_penalty_max_marks  # null: no limit
    if "late_until" in payload.model_fields_set:
        assignment.late_until = _clean_late_until(payload.late_until, deadline)
    elif assignment.late_until is not None and assignment.late_until < deadline:
        assignment.late_until = deadline  # the deadline moved past the old date
    assignment.available_from, assignment.deadline = available_from, deadline
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


_TEMPLATE_MIN_WORDS = 20


@router.post("/assignments/{assignment_id}/report-template", response_model=AssignmentOut)
def upload_report_template(
    assignment_id: int, file: UploadFile = File(...),
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Attach the assignment's template PDF (question paper / report
    template). Its text is cut out of every student report before the
    report similarity check, so pasted questions can't make reports look
    copied. Replaces an earlier template; only the extracted text is kept."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "The template must be a PDF file")
    data = file.file.read(report_max_bytes() + 1)
    if len(data) > report_max_bytes():
        raise HTTPException(400, f"The template PDF is larger than {report_max_bytes() // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a valid PDF")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "template.pdf"
        path.write_bytes(data)
        try:
            text = _report_sim.clean_report_pages(_report_sim.extract_pdf_pages(path))
        except Exception as exc:
            raise HTTPException(400, f"Could not read the PDF ({exc.__class__.__name__})") from None
    if len(text.split()) < _TEMPLATE_MIN_WORDS:
        raise HTTPException(400, "The PDF has almost no text to read (a scanned PDF has no text layer)")
    assignment.report_template_text = text
    assignment.report_template_filename = filename[:200]
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@router.delete("/assignments/{assignment_id}/report-template", response_model=AssignmentOut)
def delete_report_template(
    assignment_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Remove the assignment's template PDF."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    assignment.report_template_text = None
    assignment.report_template_filename = None
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Removes the assignment (students stop seeing it). Its submissions and
    grades are academic records and are kept: they're detached and keep
    their assignment name."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    kept = db.query(Submission).filter(Submission.assignment_id == assignment.id).update(
        {Submission.assignment_id: None})
    db.query(TaskUnlock).filter(TaskUnlock.assignment_id == assignment.id).delete(synchronize_session=False)
    db.query(TaskStart).filter(TaskStart.assignment_id == assignment.id).delete(synchronize_session=False)
    db.delete(assignment)
    db.commit()
    return {"status": "deleted", "submissions_kept": kept}


def _normalise_submission_types(types: list[str]) -> list[str]:
    chosen = [t for t in SUBMISSION_TYPES if t in set(types)]
    if not chosen:
        raise HTTPException(400, "Choose at least one submission type (code, report or video).")
    return chosen
