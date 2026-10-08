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
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    subject = relationship("Subject")
    rubric = relationship("Rubric")

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
    comments = Column(String, nullable=True)
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
    grader = Column(String, nullable=False)  # "heuristic" | "llm"
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
