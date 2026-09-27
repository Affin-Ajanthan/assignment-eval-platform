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

class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    # criteria: [{"name": str, "description": str, "max_points": float}, ...]
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
    assignment_name = Column(String, nullable=False)
    code_path = Column(String, nullable=True)
    report_path = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    submitted_at = Column(DateTime, default=_utcnow)
    status = Column(String, default="submitted")  # submitted | graded

    grades = relationship("Grade", back_populates="submission")
    student = relationship("User")
    subject = relationship("Subject")

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
    created_at = Column(DateTime, default=_utcnow)
