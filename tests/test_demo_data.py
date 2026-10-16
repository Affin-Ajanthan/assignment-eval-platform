"""Local demo accounts: read from a JSON file, created once, usable for login.

The tests write their own temporary JSON file, so no real demo details live
in the repository."""

import json

import app.demo_data as demo
from app.auth import verify_password
from app.db import SessionLocal
from app.models import Enrollment, InstructorAssignment, Subject, User


def _demo_file(tmp_path, monkeypatch):
    data = {
        "password": "test-pass",
        "subject": {"name": "Subject One", "code": "SUB1"},
        "instructor": {"email": "teacher@example.test", "name": "Teacher"},
        "students": [{"email": f"pupil{i}@example.test", "name": f"Pupil {i}"} for i in range(1, 4)],
    }
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("DEMO_DATA_FILE", str(path))
    return data


def test_seed_creates_accounts_once(tmp_path, monkeypatch):
    data = _demo_file(tmp_path, monkeypatch)
    db = SessionLocal()
    try:
        demo.seed_demo_data(db)
        demo.seed_demo_data(db)  # running it again must change nothing

        subject = db.query(Subject).filter(Subject.code == "SUB1").one()
        instructor = db.query(User).filter(User.email == "teacher@example.test").one()
        assert instructor.role == "instructor"
        assert verify_password(data["password"], instructor.password_hash, instructor.password_salt)
        assert db.query(InstructorAssignment).filter_by(instructor_id=instructor.id, subject_id=subject.id).count() == 1

        for i in range(1, 4):
            student = db.query(User).filter(User.email == f"pupil{i}@example.test").one()
            assert student.role == "student"
            assert verify_password(data["password"], student.password_hash, student.password_salt)
            assert db.query(Enrollment).filter_by(student_id=student.id, subject_id=subject.id).count() == 1
    finally:
        db.close()


def test_missing_file_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DATA_FILE", str(tmp_path / "absent.json"))
    db = SessionLocal()
    try:
        before = db.query(User).count()
        demo.seed_demo_data(db)
        assert db.query(User).count() == before
    finally:
        db.close()


def test_demo_data_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("DEMO_DATA", "off")
    assert not demo.demo_data_enabled()
    monkeypatch.delenv("DEMO_DATA", raising=False)
    assert demo.demo_data_enabled()
