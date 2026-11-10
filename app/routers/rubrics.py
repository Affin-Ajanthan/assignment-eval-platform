"""Rubrics and their criteria.

Moved out of app/main.py (Rubrics). Included in app/main.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import instructor_subject_ids, require_instructor
from ..common import norm_name as _norm_name
from ..db import get_db
from ..models import Assignment, AutoEvaluation, Grade, Rubric, User
from ..schemas import Criterion, CriterionUpdate, RubricCreate, RubricOut, RubricUpdate


router = APIRouter()


#
# One rubric holds all of its criteria (Rubric.criteria). Criteria are
# added, edited and removed through /rubrics/{id}/criteria -- never by
# creating another rubric -- and a second rubric with the same name in a
# subject is rejected. Grades store scores keyed by criterion name, so once
# a rubric has been used for grading its structure is locked: only
# descriptions can still be edited.

def _clean_name(name: Optional[str], what: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(400, f"{what} is required")
    return cleaned


def _instructor_rubric(db: Session, instructor: User, rubric_id: int) -> Rubric:
    rubric = db.get(Rubric, rubric_id)
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    if rubric.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    return rubric


def _rubric_graded_count(db: Session, rubric: Rubric) -> int:
    return db.query(Grade).filter(Grade.rubric_id == rubric.id).count()


def _require_unlocked(db: Session, rubric: Rubric, action: str) -> None:
    graded = _rubric_graded_count(db, rubric)
    if graded:
        raise HTTPException(
            409,
            f"Cannot {action}: this rubric has already been used to grade {graded} submission(s), and changing "
            "its criteria would change the meaning of those marks. Create a new rubric instead.",
        )


def _require_unique_rubric_name(db: Session, subject_id: int, name: str, exclude_id: Optional[int] = None) -> None:
    for other in db.query(Rubric).filter(Rubric.subject_id == subject_id).all():
        if other.id != exclude_id and _norm_name(other.name) == _norm_name(name):
            raise HTTPException(
                409, f"A rubric named '{other.name}' already exists in this subject -- add criteria to it instead."
            )


def _require_unique_criterion_names(criteria: list[dict]) -> None:
    seen: set[str] = set()
    for c in criteria:
        key = _norm_name(c["name"])
        if key in seen:
            raise HTTPException(400, f"Criterion names must be unique within a rubric ('{c['name']}' is repeated)")
        seen.add(key)


def _criterion_dict(cid: int, c: Criterion) -> dict:
    return {"id": cid, "name": _clean_name(c.name, "Criterion name"),
            "description": c.description.strip(), "max_points": c.max_points}


def _ensure_criterion_ids() -> None:
    """One-time upgrade for rubrics saved before criteria had ids."""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        changed = False
        for rubric in db.query(Rubric).all():
            if any("id" not in c for c in rubric.criteria):
                rubric.criteria = [{**c, "id": i} for i, c in enumerate(rubric.criteria, start=1)]
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def _rubric_out(db: Session, rubric: Rubric) -> RubricOut:
    graded = _rubric_graded_count(db, rubric)
    assignments = db.query(Assignment).filter(Assignment.rubric_id == rubric.id).order_by(Assignment.name).all()
    return RubricOut(
        id=rubric.id, name=rubric.name, subject_id=rubric.subject_id, subject_name=rubric.subject_name,
        criteria=rubric.criteria, max_total=rubric.max_total, created_at=rubric.created_at,
        graded_count=graded, locked=graded > 0, assignment_names=[a.name for a in assignments],
    )


@router.post("/rubrics", response_model=RubricOut)
def create_rubric(payload: RubricCreate, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    if payload.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    name = _clean_name(payload.name, "Rubric name")
    _require_unique_rubric_name(db, payload.subject_id, name)
    criteria = [_criterion_dict(i, c) for i, c in enumerate(payload.criteria, start=1)]
    _require_unique_criterion_names(criteria)
    rubric = Rubric(name=name, subject_id=payload.subject_id, criteria=criteria, created_by_id=instructor.id)
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return _rubric_out(db, rubric)


@router.get("/rubrics", response_model=list[RubricOut])
def list_rubrics(
    subject_id: Optional[int] = None, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    allowed = instructor_subject_ids(db, instructor)
    query = db.query(Rubric).filter(Rubric.subject_id.in_(allowed))
    if subject_id is not None:
        if subject_id not in allowed:
            raise HTTPException(403, "You are not assigned to this subject")
        query = query.filter(Rubric.subject_id == subject_id)
    return [_rubric_out(db, r) for r in query.order_by(Rubric.created_at.desc()).all()]


@router.get("/rubrics/{rubric_id}", response_model=RubricOut)
def get_rubric(rubric_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    return _rubric_out(db, _instructor_rubric(db, instructor, rubric_id))


@router.put("/rubrics/{rubric_id}", response_model=RubricOut)
def rename_rubric(
    rubric_id: int, payload: RubricUpdate, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    rubric = _instructor_rubric(db, instructor, rubric_id)
    name = _clean_name(payload.name, "Rubric name")
    if name != rubric.name:
        _require_unlocked(db, rubric, "rename this rubric")
        _require_unique_rubric_name(db, rubric.subject_id, name, exclude_id=rubric.id)
        rubric.name = name
        db.commit()
    return _rubric_out(db, rubric)


@router.delete("/rubrics/{rubric_id}")
def delete_rubric(rubric_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Refused while grades use the rubric (academic records). Otherwise the
    rubric is removed, assignments using it are left without a rubric, and
    automated evaluations run against it (re-runnable) are discarded."""
    rubric = _instructor_rubric(db, instructor, rubric_id)
    graded = _rubric_graded_count(db, rubric)
    if graded:
        raise HTTPException(
            409, f"This rubric can't be deleted: {graded} submission(s) have been graded with it. "
                 "Those marks must keep their rubric."
        )
    detached = db.query(Assignment).filter(Assignment.rubric_id == rubric.id).update({Assignment.rubric_id: None})
    removed_evals = db.query(AutoEvaluation).filter(AutoEvaluation.rubric_id == rubric.id).delete()
    db.delete(rubric)
    db.commit()
    return {"status": "deleted", "assignments_detached": detached, "auto_evaluations_removed": removed_evals}


@router.post("/rubrics/{rubric_id}/criteria", response_model=RubricOut)
def add_criterion(
    rubric_id: int, payload: Criterion, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Adds one more criterion to an EXISTING rubric (no new rubric record)."""
    rubric = _instructor_rubric(db, instructor, rubric_id)
    _require_unlocked(db, rubric, "add a criterion")
    next_id = max((c["id"] for c in rubric.criteria), default=0) + 1
    criteria = [*rubric.criteria, _criterion_dict(next_id, payload)]
    _require_unique_criterion_names(criteria)
    rubric.criteria = criteria  # reassign so SQLAlchemy sees the JSON change
    db.commit()
    return _rubric_out(db, rubric)


@router.put("/rubrics/{rubric_id}/criteria/{criterion_id}", response_model=RubricOut)
def update_criterion(
    rubric_id: int, criterion_id: int, payload: CriterionUpdate,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    rubric = _instructor_rubric(db, instructor, rubric_id)
    current = next((c for c in rubric.criteria if c["id"] == criterion_id), None)
    if current is None:
        raise HTTPException(404, "Criterion not found in this rubric")
    updated = dict(current)
    if payload.name is not None:
        updated["name"] = _clean_name(payload.name, "Criterion name")
    if payload.description is not None:
        updated["description"] = payload.description.strip()
    if payload.max_points is not None:
        updated["max_points"] = payload.max_points
    if updated["name"] != current["name"] or updated["max_points"] != current["max_points"]:
        _require_unlocked(db, rubric, "change a criterion's name or points")
    criteria = [updated if c["id"] == criterion_id else c for c in rubric.criteria]
    _require_unique_criterion_names(criteria)
    rubric.criteria = criteria
    db.commit()
    return _rubric_out(db, rubric)


@router.delete("/rubrics/{rubric_id}/criteria/{criterion_id}", response_model=RubricOut)
def delete_criterion(
    rubric_id: int, criterion_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    rubric = _instructor_rubric(db, instructor, rubric_id)
    if not any(c["id"] == criterion_id for c in rubric.criteria):
        raise HTTPException(404, "Criterion not found in this rubric")
    _require_unlocked(db, rubric, "delete a criterion")
    if len(rubric.criteria) == 1:
        raise HTTPException(400, "A rubric needs at least one criterion -- delete the rubric instead.")
    rubric.criteria = [c for c in rubric.criteria if c["id"] != criterion_id]
    db.commit()
    return _rubric_out(db, rubric)
