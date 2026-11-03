"""
Late submissions: the instructor's grace period, accept-late-until date and penalty; work handed in after the
deadline is taken, marked Late (with how late) and loses part of its mark, all enforced by the API.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import Assignment, Submission
from tests.auth_helpers import auth_headers, new_student, setup_subject_with_users

client = TestClient(app)
H = auth_headers

CRITERIA = [{"name": "Work", "description": "All of it", "max_points": 40}]


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _assignment(itok, subject, name, *, deadline=timedelta(days=7), **late):
    """An assignment that opened long ago, with the given late rules (none: work after the deadline is refused)."""
    body = {"subject_id": subject["id"], "name": name, "available_from": _iso(timedelta(days=-30)),
            "deadline": _iso(deadline), **late}
    r = client.post("/assignments", json=body, headers=H(itok))
    assert r.status_code == 200, r.text
    return r.json()


def _submit(tok, assignment):
    files = {"code": ("solution.py", io.BytesIO(b"print('hi')\n"), "text/x-python")}
    return client.post("/submissions", data={"subject_id": assignment["subject_id"], "assignment_id": assignment["id"]},
                       files=files, headers=H(tok))


def _grade(itok, subject, submission, points=34):
    rubric = client.post("/rubrics", json={"name": f"R{submission['id']}", "subject_id": subject["id"],
                                           "criteria": CRITERIA}, headers=H(itok)).json()
    r = client.post(f"/submissions/{submission['id']}/grade", headers=H(itok),
                    json={"rubric_id": rubric["id"], "total_score": points})
    assert r.status_code == 200, r.text


def _mine(tok, assignment):
    rows = client.get("/assignments", headers=H(tok)).json()
    return next(a for a in rows if a["id"] == assignment["id"])


def _listed(itok, submission_id):
    return next(s for s in client.get("/submissions", headers=H(itok)).json() if s["id"] == submission_id)


# --------------------------------------------------------------------------
# The rules themselves
# --------------------------------------------------------------------------


def _rules(**kwargs):
    deadline = datetime(2030, 1, 10, 12, 0)
    base = dict(deadline=deadline, available_from=datetime(2030, 1, 1), late_grace_minutes=0, late_until=None,
                late_penalty_percent=0.0, late_penalty_max_percent=100.0, late_penalty_unit="percent",
                late_penalty_marks=0.0, late_penalty_max_marks=None)
    return Assignment(**{**base, **kwargs})


def test_work_on_time_or_inside_the_grace_period_is_not_late():
    a = _rules(late_grace_minutes=30, late_penalty_percent=10.0, late_until=datetime(2030, 1, 20))
    assert a.lateness_at(datetime(2030, 1, 10, 11, 0)) == (None, 0.0, 0.0)
    assert a.lateness_at(datetime(2030, 1, 10, 12, 30)) == (None, 0.0, 0.0)  # the last minute of the grace period
    assert a.grace_ends_at == datetime(2030, 1, 10, 12, 30)


def test_late_work_loses_the_penalty_for_every_day_or_part_of_a_day_up_to_the_maximum():
    a = _rules(late_grace_minutes=60, late_penalty_percent=10.0, late_penalty_max_percent=25.0,
               late_until=datetime(2030, 1, 20))
    seconds, percent, marks = a.lateness_at(datetime(2030, 1, 10, 13, 1))  # a minute after the grace period
    assert (seconds, percent, marks) == (3660, 10.0, 0.0)
    assert a.lateness_at(datetime(2030, 1, 11, 13, 0))[1] == 10.0  # exactly one day after it
    assert a.lateness_at(datetime(2030, 1, 11, 13, 1))[1] == 20.0  # one minute into the second day
    assert a.lateness_at(datetime(2030, 1, 14, 0, 0))[1] == 25.0   # capped at the maximum


def test_a_penalty_in_marks_takes_marks_per_day_up_to_the_maximum_and_not_a_percent():
    a = _rules(late_penalty_unit="marks", late_penalty_marks=3.0, late_penalty_max_marks=7.0,
               late_penalty_percent=50.0, late_until=datetime(2030, 1, 20))  # the percent is ignored in marks mode
    assert a.lateness_at(datetime(2030, 1, 10, 12, 1))[1:] == (0.0, 3.0)
    assert a.lateness_at(datetime(2030, 1, 11, 12, 1))[1:] == (0.0, 6.0)
    assert a.lateness_at(datetime(2030, 1, 12, 12, 1))[1:] == (0.0, 7.0)  # 9 capped at the maximum
    no_cap = _rules(late_penalty_unit="marks", late_penalty_marks=3.0, late_until=datetime(2030, 1, 20))
    assert no_cap.lateness_at(datetime(2030, 1, 12, 12, 1))[1:] == (0.0, 9.0)


def test_the_marks_penalty_never_takes_the_mark_below_zero():
    s = Submission(late_seconds=90_000, late_penalty_percent=0.0, late_penalty_marks=10.0, test_total=40, test_earned=6)
    s.assignment = Assignment(assignment_type="code_challenge")
    assert s.raw_mark == 6 and s.final_mark == 0
    s.test_earned = 34
    assert s.final_mark == 24


def test_work_is_accepted_until_the_later_of_the_grace_period_and_the_late_date():
    none = _rules()
    assert none.accept_until == none.deadline
    grace = _rules(late_grace_minutes=15)
    assert grace.accept_until == datetime(2030, 1, 10, 12, 15)
    later = _rules(late_grace_minutes=15, late_until=datetime(2030, 1, 12))
    assert later.accept_until == datetime(2030, 1, 12)
    assert later.accepts_at(datetime(2030, 1, 11)) and not later.accepts_at(datetime(2030, 1, 12, 0, 1))
    assert not later.accepts_at(datetime(2029, 12, 31))  # before it opens


def test_the_final_mark_is_the_raw_mark_less_the_penalty():
    s = Submission(late_seconds=90_000, late_penalty_percent=10.0)
    s.assignment = None
    assert s.is_late and s.late_penalty_percent == 10.0
    # No grade yet: no mark at all, with or without a penalty.
    assert s.raw_mark is None and s.final_mark is None


# --------------------------------------------------------------------------
# Through the API
# --------------------------------------------------------------------------


def test_work_on_time_is_not_late_and_keeps_its_whole_mark():
    subject, itok, stok = setup_subject_with_users(client)
    a = _assignment(itok, subject, "On time", late_penalty_percent=10, late_until=_iso(timedelta(days=10)))
    sub = _submit(stok, a).json()
    assert (sub["late_seconds"], sub["late_penalty_percent"]) == (None, 0)
    _grade(itok, subject, sub)
    mine = _mine(stok, a)["my_submission"]
    assert (mine["final_mark"], mine["raw_mark"], mine["late_seconds"]) == (34, 34, None)
    assert _mine(stok, a)["past_deadline"] is False


def test_work_inside_the_grace_period_is_taken_and_is_not_late():
    subject, itok, stok = setup_subject_with_users(client)
    a = _assignment(itok, subject, "Grace", deadline=timedelta(minutes=-10), late_grace_minutes=30,
                    late_penalty_percent=10)
    seen = _mine(stok, a)
    assert seen["status"] == "open" and seen["past_deadline"] is True and seen["penalty_now_percent"] == 0
    assert seen["late_grace_minutes"] == 30 and seen["accept_until"] is not None
    sub = _submit(stok, a)
    assert sub.status_code == 200 and sub.json()["late_seconds"] is None


def test_late_work_is_marked_late_with_how_late_and_loses_part_of_its_mark():
    subject, itok, stok = setup_subject_with_users(client)
    a = _assignment(itok, subject, "Late", deadline=timedelta(hours=-30), late_until=_iso(timedelta(days=3)),
                    late_penalty_percent=10, late_penalty_max_percent=100)
    seen = _mine(stok, a)
    assert seen["status"] == "open" and seen["past_deadline"] is True and seen["penalty_now_percent"] == 20

    sub = _submit(stok, a)
    assert sub.status_code == 200
    sub = sub.json()
    assert 30 * 3600 <= sub["late_seconds"] < 30 * 3600 + 120 and sub["late_penalty_percent"] == 20
    _grade(itok, subject, sub, points=34)

    mine = _mine(stok, a)["my_submission"]
    assert (mine["raw_mark"], mine["final_mark"], mine["max_mark"]) == (34, 27.2, 40)  # 34 -> 27.2 (late -20%)
    assert mine["late_penalty_percent"] == 20 and mine["late_seconds"] >= 30 * 3600

    row = _listed(itok, sub["id"])  # the instructor's table: the late flag, how late, and the marks
    assert row["late_seconds"] >= 30 * 3600 and (row["raw_mark"], row["final_mark"]) == (34, 27.2)
    assert next(x for x in client.get("/assignments", headers=H(itok)).json() if x["id"] == a["id"])["late_count"] == 1


def test_the_penalty_stops_at_the_maximum():
    subject, itok, stok = setup_subject_with_users(client)
    a = _assignment(itok, subject, "Capped", deadline=timedelta(hours=-30), late_until=_iso(timedelta(days=3)),
                    late_penalty_percent=10, late_penalty_max_percent=15)
    sub = _submit(stok, a).json()
    assert sub["late_penalty_percent"] == 15
    _grade(itok, subject, sub, points=40)
    assert _mine(stok, a)["my_submission"]["final_mark"] == 34


def test_a_penalty_in_marks_is_taken_off_the_mark_not_a_percent():
    subject, itok, stok = setup_subject_with_users(client)
    a = _assignment(itok, subject, "Marks", deadline=timedelta(hours=-30), late_until=_iso(timedelta(days=3)),
                    late_penalty_unit="marks", late_penalty_marks=5, late_penalty_percent=50)
    assert (a["late_penalty_unit"], a["late_penalty_marks"], a["late_penalty_max_marks"]) == ("marks", 5, None)
    seen = _mine(stok, a)
    assert seen["penalty_now_marks"] == 10 and seen["penalty_now_percent"] == 0 and seen["late_penalty_unit"] == "marks"

    sub = _submit(stok, a).json()  # 30 hours late: two days or part of a day, 5 marks each
    assert (sub["late_penalty_marks"], sub["late_penalty_percent"]) == (10, 0)
    _grade(itok, subject, sub, points=34)
    mine = _mine(stok, a)["my_submission"]
    assert (mine["raw_mark"], mine["final_mark"], mine["late_penalty_marks"]) == (34, 24, 10)  # 34 -> 24 (late -10)
    row = _listed(itok, sub["id"])
    assert (row["raw_mark"], row["final_mark"], row["late_penalty_marks"]) == (34, 24, 10)


def test_the_marks_penalty_stops_at_its_maximum_and_can_be_switched_back_to_percent():
    subject, itok, stok = setup_subject_with_users(client)
    a = _assignment(itok, subject, "Marks cap", deadline=timedelta(hours=-30), late_until=_iso(timedelta(days=3)),
                    late_penalty_unit="marks", late_penalty_marks=5, late_penalty_max_marks=7)
    sub = _submit(stok, a).json()
    assert sub["late_penalty_marks"] == 7
    _grade(itok, subject, sub, points=40)
    assert _mine(stok, a)["my_submission"]["final_mark"] == 33

    put = lambda **body: client.put(f"/assignments/{a['id']}", headers=H(itok), json=body)
    out = put(late_penalty_unit="percent", late_penalty_percent=10).json()
    assert (out["late_penalty_unit"], out["late_penalty_max_marks"]) == ("percent", 7)  # the marks rules are kept
    assert put(late_penalty_max_marks=None).json()["late_penalty_max_marks"] is None   # null: no limit
    later = _submit(new_student(client, subject["id"]), a).json()
    assert (later["late_penalty_percent"], later["late_penalty_marks"]) == (20, 0)  # two days at 10%


def test_work_after_the_late_window_is_refused():
    subject, itok, stok = setup_subject_with_users(client)
    plain = _assignment(itok, subject, "No late work", deadline=timedelta(hours=-1))
    refused = _submit(stok, plain)
    assert refused.status_code == 403 and "deadline" in refused.json()["detail"]
    seen = _mine(stok, plain)
    assert seen["status"] == "closed" and seen["past_deadline"] is True and seen["accept_until"] is None

    over = _assignment(itok, subject, "Window over", deadline=timedelta(hours=-30), late_until=_iso(timedelta(hours=-2)),
                       late_penalty_percent=10)
    assert _submit(new_student(client, subject["id"]), over).status_code == 403
    assert _mine(stok, over)["status"] == "closed"


def test_late_rules_are_checked_and_can_be_changed_later():
    subject, itok, stok = setup_subject_with_users(client)
    body = {"subject_id": subject["id"], "name": "Bad", "available_from": _iso(timedelta(days=-3)),
            "deadline": _iso(timedelta(days=1)), "late_until": _iso(timedelta(hours=1))}
    before = client.post("/assignments", json=body, headers=H(itok))
    assert before.status_code == 400 and "after the deadline" in before.json()["detail"]
    for bad in ({"late_penalty_percent": 101}, {"late_penalty_percent": -1}, {"late_grace_minutes": -5},
                {"late_penalty_max_percent": 150}, {"late_penalty_unit": "points"}, {"late_penalty_marks": -2},
                {"late_penalty_max_marks": -1}):
        assert client.post("/assignments", json={**body, "late_until": None, "name": "Bad2", **bad},
                           headers=H(itok)).status_code == 422

    a = _assignment(itok, subject, "Later", deadline=timedelta(hours=-30))
    assert _submit(stok, a).status_code == 403  # no late work yet
    changed = client.put(f"/assignments/{a['id']}", headers=H(itok),
                         json={"late_until": _iso(timedelta(days=2)), "late_penalty_percent": 5,
                               "late_grace_minutes": 10})
    assert changed.status_code == 200
    out = changed.json()
    assert (out["late_penalty_percent"], out["late_grace_minutes"]) == (5, 10) and out["late_until"] is not None
    assert _submit(stok, a).json()["late_penalty_percent"] == 10  # two days (or part of) at 5%
    stop = client.put(f"/assignments/{a['id']}", headers=H(itok), json={"late_until": None})
    assert stop.json()["late_until"] is None
