"""
"Coming soon" for students (GET /upcoming-assignments): the not-yet-open
assignments of their own subjects, with only the name and the dates.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, create_assignment, setup_subject_with_users

client = TestClient(fastapi_app)


def test_students_see_upcoming_assignments_of_their_subjects_with_only_name_and_dates():
    subject, itok, stok = setup_subject_with_users(client)
    later = create_assignment(client, itok, subject["id"], "Opens next week", opens_in=timedelta(days=7),
                              closes_in=timedelta(days=14), description="SECRET brief still being written")
    create_assignment(client, itok, subject["id"], "Opens tomorrow", opens_in=timedelta(days=1),
                      closes_in=timedelta(days=8))
    create_assignment(client, itok, subject["id"], "Already open")  # opened an hour ago
    other_subject, other_itok, _ = setup_subject_with_users(client)
    create_assignment(client, other_itok, other_subject["id"], "Not my subject", opens_in=timedelta(days=2))

    r = client.get("/upcoming-assignments", headers=auth_headers(stok))
    assert r.status_code == 200, r.text
    upcoming = r.json()
    assert [a["name"] for a in upcoming] == ["Opens tomorrow", "Opens next week"]  # soonest first, own subject only
    assert set(upcoming[1]) == {"name", "subject_id", "subject_name", "assignment_type", "available_from", "deadline"}
    assert upcoming[1]["subject_name"] == subject["name"]
    assert datetime.fromisoformat(upcoming[1]["available_from"].replace("Z", "+00:00")) == datetime.fromisoformat(
        later["available_from"].replace("Z", "+00:00"))
    assert "SECRET" not in r.text

    # Nothing else changes: the list of assignments and the assignment itself stay closed to the student.
    assert "Opens next week" not in [a["name"] for a in client.get("/assignments", headers=auth_headers(stok)).json()]
    assert client.get(f"/assignments/{later['id']}", headers=auth_headers(stok)).status_code == 404


def test_upcoming_assignments_are_for_students():
    _, itok, _ = setup_subject_with_users(client)
    assert client.get("/upcoming-assignments", headers=auth_headers(itok)).status_code == 403
    assert client.get("/upcoming-assignments").status_code == 401
