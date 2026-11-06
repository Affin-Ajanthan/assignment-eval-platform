"""
SQLAlchemy models for the whole app: accounts + subject-wise access
control (User, Subject, InstructorAssignment, Enrollment, AuthSession)
and the assignment/grading data (Rubric, Submission, Grade,
SimilarityFlag, AutoEvaluation, BatchJob).

Access control shape:
- Every account -- admin, instructor, student -- is created by an
  admin (see the /admin/* endpoints in app/main.py). There is no
  self-registration.
- An instructor is assigned to zero or more subjects (InstructorAssignment)
  and only ever sees/manages rubrics, submissions and grading for those
  subjects.
- A student is enrolled in zero or more subjects (Enrollment) and can
  only submit to, and see their own work in, subjects they're enrolled in.
- Rubrics and Submissions each belong to exactly one Subject, which is
  how every scoping check in app/main.py is enforced.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Accounts + subject-wise access control
# --------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin" | "instructor" | "student"
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    # A student's batch (e.g. "2022-2026") and register number, both optional and unused for other roles.
    # No two students share a register number; the API checks that (existing rows have none).
    batch = Column(String, nullable=True)
    register_number = Column(String, nullable=True)

    instructor_assignments = relationship(
        "InstructorAssignment",
        back_populates="instructor",
        cascade="all, delete-orphan",
        foreign_keys="InstructorAssignment.instructor_id",
    )
    enrollments = relationship(
        "Enrollment",
        back_populates="student",
        cascade="all, delete-orphan",
        foreign_keys="Enrollment.student_id",
    )


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    # Not unique on its own: every batch has the same subjects with the same codes, so a subject is told apart by
    # its code and batch together ("" when it has no batch).
    code = Column(String, nullable=False, index=True)
    batch = Column(String, nullable=False, default="", server_default="")
    # Student access: the admin gives a subject to instructors only. When an instructor opens it, every student
    # can see it and join it (an Enrollment) by entering join_password. Kept as typed, because the instructor
    # reads it back to share it.
    open_to_students = Column(Boolean, nullable=False, default=False, server_default="0")
    join_password = Column(String, nullable=True)
    # When set, registration closes at this time (naive UTC) even though open_to_students is still on. The
    # instructor opens it again by saving a later date (or none).
    registration_ends_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class InstructorAssignment(Base):
    """Which subjects an instructor is allowed to see and manage."""

    __tablename__ = "instructor_assignments"
    __table_args__ = (UniqueConstraint("instructor_id", "subject_id", name="uq_instructor_subject"),)

    id = Column(Integer, primary_key=True, index=True)
    instructor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)

    instructor = relationship("User", back_populates="instructor_assignments", foreign_keys=[instructor_id])
    subject = relationship("Subject")


class Enrollment(Base):
    """Which subjects a student is enrolled in, and can submit to."""

    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "subject_id", name="uq_student_subject"),)

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)

    student = relationship("User", back_populates="enrollments", foreign_keys=[student_id])
    subject = relationship("Subject")


class AuthSession(Base):
    """One opaque bearer token per login (see app/auth.py). The
    frontend sends this back as `Authorization: Bearer <token>`."""

    __tablename__ = "auth_sessions"

    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


# --------------------------------------------------------------------------
# Assignments + grading
# --------------------------------------------------------------------------

# The file kinds a student can submit. An assignment accepts any subset.
SUBMISSION_TYPES = ("code", "report", "video")


class Assignment(Base):
    """One piece of coursework in a subject: what students see and submit to.

    Times are stored as naive UTC (like every other timestamp here) and the
    submission window -- ``available_from <= now <= deadline`` -- is enforced
    by the API, not just the UI. Deleting an assignment never deletes
    submissions: they keep their ``assignment_name`` and are detached."""

    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    available_from = Column(DateTime, nullable=False)
    deadline = Column(DateTime, nullable=False)
    rubric_id = Column(Integer, ForeignKey("rubrics.id"), nullable=True)
    # Subset of SUBMISSION_TYPES; NULL (assignments made before this option
    # existed) accepts every type.
    submission_types = Column(JSON, nullable=True)
    # Optional code handed out to every student. Its Winnowing fingerprints
    # are excluded from the token similarity check (files with the same
    # extension as starter_code_filename only). Instructor-only.
    starter_code = Column(String, nullable=True)
    starter_code_filename = Column(String, nullable=True)
    # Optional template PDF (question paper / report template). Only its
    # extracted text is kept; that text is cut out of every student report
    # before the report similarity check. Instructor-only.
    report_template_text = Column(String, nullable=True)
    report_template_filename = Column(String, nullable=True)
    # Optional: the only programming languages students may submit code in
    # (ids from app/code_languages.py). NULL accepts every supported language.
    code_languages = Column(JSON, nullable=True)
    # Student self-checks while the assignment is open (POST
    # /submissions/{id}/self-checks). On by default; the instructor can switch
    # either off at any time. Enforced by the API, not just the UI.
    student_similarity_check = Column(Boolean, nullable=False, default=True, server_default="1")
    student_ai_check = Column(Boolean, nullable=False, default=True, server_default="1")
    # Code similarity (instructor check and student self-check) ignores code
    # most of the class shares -- menu loops, input helpers, file saving. On by
    # default, existing assignments included.
    ignore_common_code = Column(Boolean, nullable=False, default=True, server_default="1")
    # Optional (naive UTC): students see no marks or feedback for this
    # assignment before this time, so a whole class can be published at once.
    # NULL shows each mark as soon as it is saved. Enforced by the API.
    marks_release_at = Column(DateTime, nullable=True)
    # Late submissions, set by the instructor (see `accept_until` and `lateness_at`). A grace period after the
    # deadline in which work still counts as on time; then, until `late_until` (naive UTC; NULL: never), work is
    # accepted but marked Late, and loses `late_penalty_percent` of its mark for every day (or part of a day) it is
    # late, at most `late_penalty_max_percent`. The defaults change nothing: no grace, no late work, no penalty.
    late_grace_minutes = Column(Integer, nullable=False, default=0, server_default="0")
    late_until = Column(DateTime, nullable=True)
    late_penalty_percent = Column(Float, nullable=False, default=0, server_default="0")
    late_penalty_max_percent = Column(Float, nullable=False, default=100, server_default="100")
    # The penalty can be in percent (the two columns above) or in marks (the two below): `late_penalty_unit` says
    # which one counts. In marks it is `late_penalty_marks` off the mark for every day (or part of a day) late, at
    # most `late_penalty_max_marks` (NULL: no limit but the mark itself).
    late_penalty_unit = Column(String, nullable=False, default="percent", server_default="percent")
    late_penalty_marks = Column(Float, nullable=False, default=0, server_default="0")
    late_penalty_max_marks = Column(Float, nullable=True)
    # Optional test cases for submitted code (HackerRank style):
    # [{"id", "name", "input", "expected_output", "match": "exact" | "contains",
    #   "visible": bool, "points": float}, ...]. "input" is fed to the program's
    # standard input; hidden tests (visible=False) are never shown to students.
    # A code challenge can have several tasks (called questions in the API and the database), each with
    # its own tests: a test says which one it belongs to ("question": 1, 2, ...; a test saved without it
    # belongs to task 1).
    test_cases = Column(JSON, nullable=True)
    # The tasks of a code challenge: [{"id": 1, "title": str, "statement": str, "starter_code": str}, ...]
    # in the order students see them ("statement" is the task's question text, "starter_code" the code
    # their editor starts with; older rows have no such key). NULL: one task without a title
    # (every challenge made before tasks existed). Read it through `questions`. A task may also have
    # "time_limit_seconds" (absent or 0: no limit): how long a student has from opening it (see TaskStart).
    code_questions = Column(JSON, nullable=True)
    # The file the tests run, e.g. "student_management.rb" (a name or a path
    # inside the submission). NULL: the only runnable (Python, Ruby, Java, JavaScript, C, C++) file, or a main.* one.
    # Only used by a challenge with a single task.
    test_main_file = Column(String, nullable=True)
    # A code challenge's access password: students must enter it (POST /assignments/{id}/unlock-tasks) before
    # they are shown the questions or can run or submit code. Kept as typed, because the instructor reads it
    # back to share it with the class; never sent to students. NULL: no password (every challenge made before this).
    task_password = Column(String, nullable=True)
    # A code challenge whose tasks must be handed in in order: task 2 can be run or submitted only once task 1
    # is handed in, and so on. Enforced by the API.
    tasks_in_order = Column(Boolean, nullable=False, default=False, server_default="0")
    # "submission": students upload code, a report and/or a video, graded with a
    # rubric. "code_challenge": students submit code only, and it is run against
    # test_cases (HackerRank style). Chosen when the assignment is created and
    # never changed. Read it through `kind`, which also covers older rows.
    assignment_type = Column(String, nullable=False, default="submission", server_default="submission")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    subject = relationship("Subject")
    rubric = relationship("Rubric")

    def accepted_types(self) -> list[str]:
        """File kinds students may submit, in the canonical order."""
        if not self.submission_types:
            return list(SUBMISSION_TYPES)
        return [t for t in SUBMISSION_TYPES if t in self.submission_types]

    @property
    def kind(self) -> str:
        """"code_challenge" or "submission". An assignment that already has test
        cases counts as a code challenge even if it was saved before the type existed."""
        return "code_challenge" if self.assignment_type == "code_challenge" or self.test_cases else "submission"

    @property
    def questions(self) -> list[dict]:
        """The tasks of a code challenge, each {"id", "title", "statement", "starter_code"}, ids 1, 2, ...
        in order (a task saved before starting code existed has no "starter_code" key).
        A challenge saved without any has the one untitled task that all its tests belong to.
        Empty for any other assignment."""
        if self.kind != "code_challenge":
            return []
        return list(self.code_questions or [{"id": 1, "title": "", "statement": "", "starter_code": ""}])

    @property
    def is_timed(self) -> bool:
        """Whether any task of a code challenge has a time limit."""
        return any((q.get("time_limit_seconds") or 0) > 0 for q in self.questions)

    @property
    def requires_password(self) -> bool:
        """Whether students must enter the task password before they can see or do the tasks."""
        return self.kind == "code_challenge" and bool((self.task_password or "").strip())

    def tests_of(self, question_id: int) -> list[dict]:
        """The test cases of one task, in order."""
        return [t for t in self.test_cases or [] if t.get("question", 1) == question_id]

    def marks_released_at(self, now: datetime) -> bool:
        """Whether students may see marks and feedback at a naive-UTC ``now``."""
        return self.marks_release_at is None or now >= self.marks_release_at

    @property
    def grace_ends_at(self) -> datetime:
        """Until then work counts as on time: the deadline plus the grace period."""
        return self.deadline + timedelta(minutes=self.late_grace_minutes or 0)

    @property
    def accept_until(self) -> datetime:
        """The last moment work is taken: the end of the grace period, or the accept-late-until date if later."""
        return max(self.grace_ends_at, self.late_until) if self.late_until else self.grace_ends_at

    def accepts_at(self, now: datetime) -> bool:
        """Whether work is taken at a naive-UTC ``now``: from the start date until `accept_until`."""
        return self.available_from <= now <= self.accept_until

    def lateness_at(self, at: datetime) -> tuple[int | None, float, float]:
        """For work handed in at ``at``: (seconds after the deadline, percent of the mark lost, marks lost). Work
        inside the grace period is on time: (None, 0, 0). The penalty is, for every day or part of a day after the
        grace period, `late_penalty_percent` (at most `late_penalty_max_percent`) when the unit is percent, or
        `late_penalty_marks` (at most `late_penalty_max_marks`) when it is marks. Only one of the two is not 0."""
        if at <= self.grace_ends_at:
            return None, 0.0, 0.0
        days = math.ceil((at - self.grace_ends_at).total_seconds() / 86400)
        late_seconds = int((at - self.deadline).total_seconds())
        if self.late_penalty_unit == "marks":
            marks = days * (self.late_penalty_marks or 0.0)
            if self.late_penalty_max_marks is not None:
                marks = min(marks, self.late_penalty_max_marks)
            return late_seconds, 0.0, round(max(marks, 0.0), 2)
        cap = min(self.late_penalty_max_percent if self.late_penalty_max_percent is not None else 100.0, 100.0)
        percent = min(days * (self.late_penalty_percent or 0.0), cap)
        return late_seconds, round(max(percent, 0.0), 2), 0.0

    def status_at(self, now: datetime) -> str:
        """'upcoming' | 'open' | 'closed' for a naive-UTC ``now``."""
        if now < self.available_from:
            return "upcoming"
        if now > self.deadline:
            return "closed"
        return "open"


class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    # One rubric holds ALL its criteria:
    # [{"id": int, "name": str, "description": str, "max_points": float}, ...]
    # `id` is stable within the rubric (used by the per-criterion endpoints);
    # grades key their scores by criterion `name`.
    criteria = Column(JSON, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    grades = relationship("Grade", back_populates="rubric")
    subject = relationship("Subject")

    @property
    def max_total(self) -> float:
        return sum(c["max_points"] for c in self.criteria)

    @property
    def subject_name(self) -> str:
        return self.subject.name if self.subject else ""


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    # Kept on every submission (and kept in sync on rename) so legacy
    # submissions made before assignments existed, and submissions to a
    # deleted assignment, still show which assignment they were for.
    assignment_name = Column(String, nullable=False)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=True, index=True)
    code_path = Column(String, nullable=True)
    report_path = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    submitted_at = Column(DateTime, default=_utcnow)
    status = Column(String, default="submitted")  # submitted | graded
    # A code challenge is marked by its tests, not a rubric: when the instructor
    # runs them as the mark, the points of the tests passed (test_earned) out of
    # all the tests' points (test_total) are saved here, and `final_mark` /
    # `max_mark` use them. NULL until then.
    test_earned = Column(Float, nullable=True)
    test_total = Column(Float, nullable=True)
    tests_run_at = Column(DateTime, nullable=True)
    # A code challenge is answered one task at a time, all in this one submission. This holds
    # what was handed in for each task: [{"question", "file", "language", "marked", "earned",
    # "total", "report"}, ...] (see app/code_answers.py, which reads and writes it). NULL for a
    # submission made before that, or uploaded as files: its answers are worked out from its files.
    question_results = Column(JSON, nullable=True)
    # Work handed in after the deadline and its grace period: how many seconds after the deadline it was
    # (NULL: on time) and the percent of the mark it loses for that (see Assignment.lateness_at). Fixed when the
    # work is handed in (a code challenge: when its latest task is), so later changes to the assignment's late
    # rules do not move it.
    late_seconds = Column(Integer, nullable=True)
    late_penalty_percent = Column(Float, nullable=False, default=0, server_default="0")
    late_penalty_marks = Column(Float, nullable=False, default=0, server_default="0")  # or marks lost, if so set

    # Oldest first; re-grading adds a row, so the last one is the current grade.
    grades = relationship("Grade", back_populates="submission", order_by="Grade.id")
    student = relationship("User")
    subject = relationship("Subject")
    assignment = relationship("Assignment")

    @property
    def latest_grade(self) -> "Grade | None":
        return self.grades[-1] if self.grades else None

    @property
    def submitted_types(self) -> list[str]:
        """Which kinds of file were uploaded: any of code, report, video."""
        return [kind for kind, path in (("code", self.code_path), ("report", self.report_path),
                                        ("video", self.video_path)) if path]

    @property
    def marked_by_tests(self) -> bool:
        """A code challenge whose tests have been run as the mark."""
        return (self.test_total is not None and self.assignment is not None
                and self.assignment.kind == "code_challenge")

    def apply_lateness(self, assignment: "Assignment", at: datetime) -> None:
        """Record how late the work handed in at ``at`` is, and the penalty that costs."""
        self.late_seconds, self.late_penalty_percent, self.late_penalty_marks = assignment.lateness_at(at)

    @property
    def is_late(self) -> bool:
        return self.late_seconds is not None

    @property
    def raw_mark(self) -> float | None:
        """The mark before any late penalty: the tests' points, or the instructor's grade."""
        if self.marked_by_tests:
            return self.test_earned
        grade = self.latest_grade
        return grade.total_score if grade else None

    @property
    def final_mark(self) -> float | None:
        """The mark students and exports see: the raw mark less the late penalty, if any."""
        raw = self.raw_mark
        if raw is None or not (self.late_penalty_percent or self.late_penalty_marks):
            return raw
        marked = raw * (1 - (self.late_penalty_percent or 0) / 100) - (self.late_penalty_marks or 0)
        return round(max(marked, 0.0), 2)

    @property
    def max_mark(self) -> float | None:
        if self.marked_by_tests:
            return self.test_total
        grade = self.latest_grade
        return grade.rubric.max_total if grade and grade.rubric else None

    @property
    def student_name(self) -> str:
        return self.student.full_name if self.student else ""

    @property
    def student_email(self) -> str:
        return self.student.email if self.student else ""

    @property
    def subject_name(self) -> str:
        return self.subject.name if self.subject else ""


class Grade(Base):
    __tablename__ = "grades"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    rubric_id = Column(Integer, ForeignKey("rubrics.id"), nullable=False)
    # criterion_scores: {"<criterion name>": <points awarded>, ...}
    criterion_scores = Column(JSON, nullable=False)
    total_score = Column(Float, nullable=False)
    comments = Column(String, nullable=True)  # internal: instructors only, never shown to students
    # Written for the student; shown to them with their marks.
    feedback = Column(String, nullable=True)
    graded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    graded_by = Column(String, nullable=True)  # instructor's display name, denormalized
    graded_at = Column(DateTime, default=_utcnow)

    submission = relationship("Submission", back_populates="grades")
    rubric = relationship("Rubric", back_populates="grades")


class SimilarityFlag(Base):
    """One flagged pair from a similarity-check run across an
    assignment's submissions within one subject (see
    POST /subjects/{id}/assignments/{name}/check-similarity)."""

    __tablename__ = "similarity_flags"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    assignment_name = Column(String, nullable=False, index=True)
    submission_a_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    submission_b_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    jaccard = Column(Float, nullable=False)
    containment = Column(Float, nullable=False)
    # UniXcoder score; NULL when semantic analysis didn't run for this pair.
    semantic_similarity = Column(Float, nullable=True)
    # "high" = token/fingerprint overlap, "review" = semantic signal only.
    # NULL on rows written before semantic analysis existed (token-based).
    flag_level = Column(String, nullable=True)
    flag_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class AutoEvaluation(Base):
    """Automated pipeline output: one run against a submission + rubric
    (see POST /submissions/{id}/auto-evaluate). Instructors see this
    before manually grading/overriding (Grade, above)."""

    __tablename__ = "auto_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    rubric_id = Column(Integer, ForeignKey("rubrics.id"), nullable=False)
    recommended_score = Column(Float, nullable=False)
    recommended_max = Column(Float, nullable=False)
    review_flags = Column(JSON, nullable=False)
    # [{"name":.., "score":.., "max_points":.., "justification":..}, ...]
    criterion_breakdown = Column(JSON, nullable=False)
    grader = Column(String, nullable=False)  # "heuristic" | "ollama"
    model = Column(String, nullable=True)  # Ollama model name, e.g. "qwen3:8b"; NULL for the heuristic grader
    similarity_flagged = Column(Boolean, default=False)
    code_ai_flagged = Column(Boolean, default=False)
    report_ai_signal = Column(String, nullable=True)  # "low" | "medium" | "high"
    consistency_score = Column(Integer, nullable=True)
    # Cross-modal SEMANTIC consistency (app/evaluator/semantic_consistency.py):
    # {"code_report", "code_transcript", "report_transcript", "overall",
    #  "status", "reason", ...}; scores are null when not evaluated.
    cross_modal_consistency = Column(JSON, nullable=True)
    # {"report": {signal, score, method, reasons} | null, "code": {...} | null}
    ai_signals = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class SelfCheck(Base):
    """One self-check a student ran on their own submission before the
    deadline: code similarity, report similarity or AI-content detection.

    Kept apart from SimilarityFlag / AutoEvaluation: a self-check never
    changes what the instructor's own checks show. ``result`` keeps the full
    internal detail (exact scores, which submissions matched) for the
    instructor; the student endpoint returns only bands and the student's own
    matching passages."""

    __tablename__ = "self_checks"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=True, index=True)
    kind = Column(String, nullable=False)  # "code_similarity" | "report_similarity" | "ai_content"
    status = Column(String, nullable=False, default="running")  # "running" | "done" | "failed"
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    finished_at = Column(DateTime, nullable=True)


class TaskUnlock(Base):
    """A student who entered the right task password of a code challenge: from then on they are shown its
    questions and can run and submit code. One row per student and challenge (the password is not asked again)."""

    __tablename__ = "task_unlocks"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_task_unlock"),)

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    unlocked_at = Column(DateTime, default=_utcnow)


class TaskStart(Base):
    """The moment a student opened one task of a code challenge that has a time limit (the task's own
    ``time_limit_seconds``): its clock runs from here. One row per student and task. While the clock
    runs the page also keeps the code they have typed here (a draft), so that when the time is up the server
    can hand it in even if the student has closed the page. Naive UTC, like the deadlines."""

    __tablename__ = "task_starts"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", "question", name="uq_task_start"),)

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=False)
    draft_code = Column(String, nullable=True)
    draft_language = Column(String, nullable=True)


class BatchJob(Base):
    """One "Evaluate a whole assignment" run: which assignment and rubric,
    its options, and progress so far. Updated as each submission finishes,
    so the instructor can follow it (and see it again after leaving the page).

    ``results`` holds one entry per submission in submission order (the
    BatchEvaluationItemOut shape), ``null`` while that submission is still
    waiting or running."""

    __tablename__ = "batch_jobs"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    assignment_name = Column(String, nullable=False)
    rubric_id = Column(Integer, ForeignKey("rubrics.id"), nullable=False)
    # {"skip_already_evaluated", "use_rubric_model", "use_ai_detection"}
    options = Column(JSON, nullable=False)
    # "interrupted": the server stopped mid-run (marked at the next start); resume to finish it.
    status = Column(String, nullable=False, default="queued")  # "queued" | "running" | "done" | "failed" | "interrupted"
    total = Column(Integer, nullable=False, default=0)
    evaluated = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    results = Column(JSON, nullable=True)
    error = Column(String, nullable=True)  # why the whole job failed (one submission failing is not that)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    @property
    def done(self) -> int:
        """Submissions finished so far, whatever their outcome."""
        return (self.evaluated or 0) + (self.skipped or 0) + (self.failed or 0)
