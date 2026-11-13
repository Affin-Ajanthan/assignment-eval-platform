"""A rubric belongs to one subject: its code comes with it, and the form can ask who teaches that subject."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import admin_token, auth_headers, create_instructor, create_student, create_subject

client = TestClient(fastapi_app)
H = auth_headers

CRITERIA = [{"name": "Correctness", "description": "Works", "max_points": 10}]


def _two_subjects():
    """Subject A taught by Ann and Ben, subject B taught by Ben and Cy (Ben teaches both)."""
    admin = admin_token(client)
    a = create_subject(client, admin)
    b = create_subject(client, admin)
    _, ann = create_instructor(client, admin, [a["id"]], full_name="Ann Example")
    _, ben = create_instructor(client, admin, [a["id"], b["id"]], full_name="Ben Example")
    _, cy = create_instructor(client, admin, [b["id"]], full_name="Cy Example")
    return admin, a, b, ann, ben, cy


def test_a_rubric_carries_the_code_of_its_own_subject():
    _, a, b, ann, ben, cy = _two_subjects()
    r = client.post("/rubrics", headers=H(ben), json={"name": "Essay", "subject_id": b["id"], "criteria": CRITERIA})
    assert r.status_code == 200, r.text
    assert (r.json()["subject_name"], r.json()["subject_code"]) == (b["name"], b["code"])
    listed = client.get("/rubrics", headers=H(ben)).json()
    assert {(x["name"], x["subject_code"]) for x in listed if x["name"] == "Essay"} == {("Essay", b["code"])}


def test_a_rubric_is_for_the_instructors_of_its_subject_only():
    _, a, b, ann, ben, cy = _two_subjects()
    client.post("/rubrics", headers=H(ann), json={"name": "Only for A", "subject_id": a["id"], "criteria": CRITERIA})
    names = lambda tok: {x["name"] for x in client.get("/rubrics", headers=H(tok)).json()}
    assert "Only for A" in names(ann) and "Only for A" in names(ben)  # both teach A
    assert "Only for A" not in names(cy)  # Cy teaches only B
    # ...and Ann cannot make a rubric in a subject she does not teach.
    refused = client.post("/rubrics", headers=H(ann), json={"name": "Nope", "subject_id": b["id"], "criteria": CRITERIA})
    assert refused.status_code == 403


def test_the_instructors_of_a_subject_are_listed_for_its_own_instructors_only():
    admin, a, b, ann, ben, cy = _two_subjects()
    rows = client.get(f"/instructor/subjects/{a['id']}/instructors", headers=H(ann)).json()
    assert [r["name"] for r in rows] == ["Ann Example", "Ben Example"]  # not Cy, who only teaches B
    assert all(set(r) == {"id", "name", "email"} for r in rows)  # nothing about their other subjects

    rows_b = client.get(f"/instructor/subjects/{b['id']}/instructors", headers=H(ben)).json()
    assert [r["name"] for r in rows_b] == ["Ben Example", "Cy Example"]

    assert client.get(f"/instructor/subjects/{a['id']}/instructors", headers=H(cy)).status_code == 403
    _, student = create_student(client, admin, [a["id"]])
    assert client.get(f"/instructor/subjects/{a['id']}/instructors", headers=H(student)).status_code == 403
    assert client.get(f"/instructor/subjects/{a['id']}/instructors").status_code in (401, 403)
