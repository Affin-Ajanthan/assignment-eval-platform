"""
SQLAlchemy models for the whole app: accounts + subject-wise access
control (User, Subject, InstructorAssignment, Enrollment, AuthSession)
and the assignment/grading data (Rubric, Submission, Grade,
SimilarityFlag, AutoEvaluation).

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

from datetime import datetime, timezone

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
    code = Column(String, nullable=False, unique=True, index=True)
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

    def marks_released_at(self, now: datetime) -> bool:
        """Whether students may see marks and feedback at a naive-UTC ``now``."""
        return self.marks_release_at is None or now >= self.marks_release_at

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
    def final_mark(self) -> float | None:
        grade = self.latest_grade
        return grade.total_score if grade else None

    @property
    def max_mark(self) -> float | None:
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
