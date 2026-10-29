"""Students running their typed code against all of a code challenge's test cases
(POST /assignments/{id}/run-code), handing it in one question at a time
(POST /assignments/{id}/submit-code) and reading back what they handed in
(GET /assignments/{id}/my-code), all in app/routers/student_runs.py.

The runner is faked, so these tests need no Docker.
"""

import io
import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.db import BASE_DIR, SessionLocal
from app.evaluator import code_testing as ct
from app.evaluator.code_execution import SandboxUnavailable
from app.main import app as fastapi_app
from app.models import Submission
from app.routers import student_runs as sr
from tests.auth_helpers import auth_headers, new_student, setup_subject_with_users

client = TestClient(fastapi_app)

TESTS = [
    {"name": "Doubles", "input": "21", "expected_output": "42", "visible": True, "points": 2},
    {"name": "HIDDEN-NAME", "input": "HIDDEN-IN", "expected_output": "HIDDEN-OUT", "points": 5},
    {"name": "Wrong on purpose", "input": "1", "expected_output": "99", "visible": True, "points": 1},
]


@pytest.fixture(autouse=True)
def _sandbox_on_and_fresh_limits(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(sr, "limiter", sr.RunLimiter(per_hour=10, max_parallel=2))


def _challenge(itok, subject, name, tests=None, *, hours_open=(-1, 168), **extra):
    now = datetime.now(timezone.utc)
    body = {"subject_id": subject["id"], "name": name,
            "available_from": (now + timedelta(hours=hours_open[0])).isoformat(),
            "deadline": (now + timedelta(hours=hours_open[1])).isoformat(), **extra}
    if tests is not None:
        body["assignment_type"] = "code_challenge"
        body["test_cases"] = tests
    r = client.post("/assignments", headers=auth_headers(itok), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _run(assignment, token, code="print(int(input()) * 2)", **extra):
    return client.post(f"/assignments/{assignment['id']}/run-code", headers=auth_headers(token),
                       json={"code": code, **extra})


class FakeRunTests:
    """Stands in for code_testing.run_tests: records what it was given and answers per test.

    By default a test passes when it expects "42" (as if the program printed 42) and
    fails otherwise; `outcomes` overrides a test by name with (status, actual_output, stderr)."""

    def __init__(self, outcomes=None, error=None):
        self.calls, self.outcomes, self.error = [], outcomes or {}, error

    def __call__(self, code_dir, tests, *, main_file="", only_visible=False, **kwargs):
        if self.error:
            raise self.error
        code = (Path(code_dir) / main_file).read_text(encoding="utf-8") if main_file else ""  # "" = pick the file
        self.calls.append({"file": main_file, "code": code,
                           "names": [t["name"] for t in tests], "only_visible": only_visible})
        results = []
        for t in tests:
            if only_visible and not t["visible"]:
                continue
            default = ("passed", "42", "") if t["expected_output"] == "42" else ("failed", "42", "")
            status, actual, stderr = self.outcomes.get(t["name"], default)
            results.append(ct.TestResult(
                test_id=t["id"], name=t["name"], visible=t["visible"], points=t["points"], match=t["match"],
                status=status, passed=status == "passed", expected_output=t["expected_output"],
                actual_output=actual, stderr=stderr))
        return ct.TestRun(file=main_file, language="python", results=results)


@pytest.fixture
def fake(monkeypatch):
    runner = FakeRunTests()
    monkeypatch.setattr(sr.code_testing, "run_tests", runner)
    return runner


def _use(monkeypatch, runner):
    monkeypatch.setattr(sr.code_testing, "run_tests", runner)
    return runner


# --------------------------------------------------------------------------
# The limiter
# --------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_limiter_allows_a_number_of_runs_per_hour_and_slides_the_window():
    clock = Clock()
    limiter = sr.RunLimiter(per_hour=2, max_parallel=5, clock=clock)
    assert limiter.start(1) == 1
    limiter.finish(1)
    clock.now += 600
    assert limiter.start(1) == 0
    limiter.finish(1)
    with pytest.raises(sr.RunLimitError) as refused:
        limiter.start(1)
    assert refused.value.status == 429 and "2 times per hour" in refused.value.detail
    assert "Try again in 50 minute" in refused.value.detail  # the first run was 10 minutes ago
    assert limiter.remaining(1) == 0
    assert limiter.start(2) == 1  # another student is not affected
    limiter.finish(2)

    clock.now += 3000  # an hour after the first run: it no longer counts
    assert limiter.remaining(1) == 1
    assert limiter.start(1) == 0


def test_the_limiter_allows_one_run_at_a_time_per_student_and_a_server_wide_cap():
    limiter = sr.RunLimiter(per_hour=10, max_parallel=2)
    limiter.start(1)
    with pytest.raises(sr.RunLimitError, match="still going"):
        limiter.start(1)
    limiter.start(2)
    with pytest.raises(sr.RunLimitError) as busy:
        limiter.start(3)
    assert busy.value.status == 503 and "busy" in busy.value.detail
    assert limiter.remaining(3) == 10  # a refused run uses nothing up

    limiter.finish(1)
    assert limiter.start(3) == 9  # a place is free again


# --------------------------------------------------------------------------
# What a student sees of a run
# --------------------------------------------------------------------------


def test_run_checks_every_test_case_but_shows_only_what_a_student_may_know(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "All tests", TESTS)
    r = _run(assignment, stok, code="print(int(input()) * 2)\r\n")
    assert r.status_code == 200, r.text
    body = r.json()

    # Doubles passes, the hidden test and "Wrong on purpose" fail.
    assert (body["language"], body["all_passed"], body["passed"], body["total"], body["hidden_failed"]) == (
        "python", False, 1, 3, 1)
    assert body["remaining_runs"] == 9
    # The failing VISIBLE test shows what was expected and what the program printed, and nothing else.
    assert body["failures"] == [{"sample": 2, "name": "Wrong on purpose", "status": "failed",
                                 "expected_output": "99", "actual_output": "42", "error": ""}]
    # Every test case ran, the hidden one included; the typed code was saved as main.py (newlines unified).
    assert fake.calls == [{"file": "main.py", "code": "print(int(input()) * 2)\n",
                           "names": ["Doubles", "HIDDEN-NAME", "Wrong on purpose"], "only_visible": False}]
    # Nothing about the hidden test, and no ids, points or inputs that could hint at it.
    assert not any(secret in json.dumps(body) for secret in ("HIDDEN", "points", "test_id", "visible", '"input"'))


def test_when_every_test_case_passes_the_student_just_sees_that_they_all_passed(monkeypatch):
    _use(monkeypatch, FakeRunTests(outcomes={"HIDDEN-NAME": ("passed", "HIDDEN-OUT", ""),
                                             "Wrong on purpose": ("passed", "99", "")}))
    subject, itok, stok = setup_subject_with_users(client)
    body = _run(_challenge(itok, subject, "All pass", TESTS), stok).json()
    assert (body["all_passed"], body["passed"], body["total"], body["hidden_failed"], body["failures"]) == (
        True, 3, 3, 0, [])
    assert "HIDDEN" not in json.dumps(body) and "expected_output" not in json.dumps(body)


def test_a_failing_hidden_test_is_only_counted_when_every_visible_test_passes(monkeypatch):
    _use(monkeypatch, FakeRunTests(outcomes={"Wrong on purpose": ("passed", "99", "")}))  # the hidden one still fails
    subject, itok, stok = setup_subject_with_users(client)
    body = _run(_challenge(itok, subject, "Hidden fails", TESTS), stok).json()
    assert (body["all_passed"], body["passed"], body["total"], body["hidden_failed"], body["failures"]) == (
        False, 2, 3, 1, [])
    assert "HIDDEN" not in json.dumps(body)


def test_a_visible_test_that_crashes_or_times_out_shows_its_error_but_hidden_errors_stay_secret(monkeypatch):
    _use(monkeypatch, FakeRunTests(outcomes={
        "Doubles": ("error", "", "Traceback: boom"),
        "Wrong on purpose": ("timeout", "partial", "Time limit of 10 seconds exceeded."),
        "HIDDEN-NAME": ("error", "", "Traceback: failed on HIDDEN-IN secret"),
    }))
    subject, itok, stok = setup_subject_with_users(client)
    body = _run(_challenge(itok, subject, "Crashes", TESTS), stok).json()
    assert body["failures"] == [
        {"sample": 1, "name": "Doubles", "status": "error", "expected_output": "42", "actual_output": "",
         "error": "Traceback: boom"},
        {"sample": 2, "name": "Wrong on purpose", "status": "timeout", "expected_output": "99",
         "actual_output": "partial", "error": "Time limit of 10 seconds exceeded."},
    ]
    assert (body["hidden_failed"], body["passed"], body["total"]) == (1, 0, 3)
    assert "secret" not in json.dumps(body) and "HIDDEN" not in json.dumps(body)  # the hidden test's error is not shown


def test_a_run_is_practice_only_it_creates_no_submission(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Practice", TESTS)
    assert _run(assignment, stok).status_code == 200
    assert client.get("/submissions", headers=auth_headers(stok)).json() == []
    assert client.get("/assignments", headers=auth_headers(stok)).json()[0]["my_submission"] is None


def test_the_language_follows_the_assignment_and_is_checked(fake):
    subject, itok, stok = setup_subject_with_users(client)
    ruby = _challenge(itok, subject, "Ruby only", TESTS, code_languages=["ruby"])
    assert _run(ruby, stok, code="puts 42").status_code == 200
    assert fake.calls[-1]["file"] == "main.rb"          # chosen from the assignment
    python_asked = _run(ruby, stok, language="python")
    assert python_asked.status_code == 400 and "doesn't accept python" in python_asked.json()["detail"]

    java = _challenge(itok, subject, "Java only", TESTS, code_languages=["java"])
    assert "Python and Ruby code only" in _run(java, stok).json()["detail"]

    either = _challenge(itok, subject, "Either", TESTS, code_languages=["python", "ruby"])
    assert _run(either, stok, language="ruby").status_code == 200 and fake.calls[-1]["file"] == "main.rb"


def test_only_enrolled_students_can_run_and_only_on_open_code_challenges(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Guards", TESTS)

    _, other_itok, other_stok = setup_subject_with_users(client)
    assert _run(assignment, other_stok).status_code == 404                    # not enrolled in this subject
    assert _run(assignment, itok).status_code == 403                          # an instructor
    assert client.post("/assignments/999999/run-code", headers=auth_headers(stok),
                       json={"code": "x"}).status_code == 404
    assert client.post(f"/assignments/{assignment['id']}/run-code", json={"code": "x"}).status_code == 401

    upcoming = _challenge(itok, subject, "Upcoming", TESTS, hours_open=(24, 48))
    assert _run(upcoming, stok).status_code == 404                            # not visible to students yet
    closed = _challenge(itok, subject, "Closed", TESTS, hours_open=(-48, -24))
    r = _run(closed, stok)
    assert r.status_code == 400 and "closed" in r.json()["detail"]
    plain = _challenge(itok, subject, "Plain submission")
    r = _run(plain, stok)
    assert r.status_code == 400 and "only for code challenges" in r.json()["detail"]
    assert fake.calls == []  # none of those ran anything

    # A challenge whose tests are all hidden can still be run: the student just hears pass or fail.
    hidden_only = _challenge(itok, subject, "Hidden only", [TESTS[1]])
    r = _run(hidden_only, stok)
    assert r.status_code == 200
    assert (r.json()["failures"], r.json()["hidden_failed"], r.json()["total"]) == ([], 1, 1)


def test_code_size_is_limited_and_empty_code_is_refused(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Size", TESTS)
    assert _run(assignment, stok, code="").status_code == 422
    assert _run(assignment, stok, code="x" * (sr.MAX_CODE_CHARS + 1)).status_code == 422
    assert _run(assignment, stok, code="x" * sr.MAX_CODE_CHARS).status_code == 200


def test_runs_are_limited_per_hour_and_a_failed_run_does_not_block_the_next(monkeypatch, fake):
    monkeypatch.setattr(sr, "limiter", sr.RunLimiter(per_hour=2, max_parallel=2))
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Limits", TESTS)

    assert _run(assignment, stok).json()["remaining_runs"] == 1
    assert _run(assignment, stok).json()["remaining_runs"] == 0
    refused = _run(assignment, stok)
    assert refused.status_code == 429 and "2 times per hour" in refused.json()["detail"]
    assert len(fake.calls) == 2  # the refused run never reached the sandbox
    # Another student has their own allowance.
    assert _run(assignment, new_student(client, subject["id"])).status_code == 200

    # If a run fails, the student can try again straight away (nothing is left "still going").
    monkeypatch.setattr(sr, "limiter", sr.RunLimiter(per_hour=5, max_parallel=2))
    monkeypatch.setattr(sr.code_testing, "run_tests", FakeRunTests(error=ct.CodeTestError("No file.")))
    assert _run(assignment, stok).status_code == 400
    monkeypatch.setattr(sr.code_testing, "run_tests", fake)
    assert _run(assignment, stok).status_code == 200


def test_running_code_needs_the_sandbox_and_hides_why_from_students(monkeypatch, fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Sandbox", TESTS)

    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    off = _run(assignment, stok)
    assert off.status_code == 503 and "CODE_SANDBOX" not in off.json()["detail"]  # setup details are for the instructor
    student_id = client.get("/auth/me", headers=auth_headers(stok)).json()["id"]
    assert sr.limiter.remaining(student_id) == sr.limiter.per_hour  # a refused run is not counted

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(sr.code_testing, "run_tests", FakeRunTests(error=SandboxUnavailable("Docker is not available")))
    down = _run(assignment, stok)
    assert down.status_code == 503 and "Docker" not in down.json()["detail"]


# --------------------------------------------------------------------------
# Submitting: final, and marked at once from the points of the tests passed
# --------------------------------------------------------------------------


def _submit(assignment, token, code="print(int(input()) * 2)", **extra):
    return client.post(f"/assignments/{assignment['id']}/submit-code", headers=auth_headers(token),
                       json={"code": code, **extra})


def _my_submission(assignment, token):
    rows = client.get("/assignments", headers=auth_headers(token)).json()
    return next(a for a in rows if a["id"] == assignment["id"])["my_submission"]


def _get_marks(assignment, token):
    return client.post(f"/assignments/{assignment['id']}/mark-my-code", headers=auth_headers(token))


def _run_of(body, question=0):
    """The report of one question from a Submit / Get my marks answer (the first question by default)."""
    return body["questions"][question]["run"]


def _all_pass(code_dir, tests, *, main_file="", **kwargs):
    """A run_tests where every test passes (it never reads the code)."""
    results = [ct.TestResult(test_id=t["id"], name=t["name"], visible=t["visible"], points=t["points"],
                             match=t["match"], status="passed", passed=True, expected_output=t["expected_output"],
                             actual_output=t["expected_output"]) for t in tests]
    return ct.TestRun(file="main.py", language="python", results=results)


def test_submitting_saves_the_points_of_the_tests_passed_as_the_mark_and_shows_the_result(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Marked at once", TESTS)
    r = _submit(assignment, stok, code="print(int(input()) * 2)\r\n")
    assert r.status_code == 200, r.text
    body = r.json()

    # Doubles (2 points) passes; the hidden test (5 points) and "Wrong on purpose" (1 point) fail: 2 of 8.
    assert (body["marked"], body["earned"], body["total"]) == (True, 2, 8)
    # The student is shown the same report as for Run: the counts, and expected vs actual of the failing visible test.
    run = _run_of(body)
    assert (run["passed"], run["total"], run["hidden_failed"]) == (1, 3, 1)
    assert run["failures"] == [{"sample": 2, "name": "Wrong on purpose", "status": "failed",
                                "expected_output": "99", "actual_output": "42", "error": ""}]
    assert not any(secret in json.dumps(body) for secret in ("HIDDEN", "points", "test_id", "visible", '"input"'))
    # Every test case ran, the hidden one included, on the typed code (newlines unified).
    assert fake.calls == [{"file": "main.py", "code": "print(int(input()) * 2)\n",
                           "names": ["Doubles", "HIDDEN-NAME", "Wrong on purpose"], "only_visible": False}]

    # It is the student's submission, already marked, and they can no longer edit it.
    mine = _my_submission(assignment, stok)
    assert (mine["id"], mine["status"], mine["final_mark"], mine["max_mark"], mine["can_edit"]) == (
        body["submission_id"], "graded", 2, 8, False)
    assert mine["questions_submitted"] == 1
    saved = client.get(f"/submissions/{body['submission_id']}", headers=auth_headers(itok)).json()
    assert (saved["status"], saved["final_mark"], saved["max_mark"]) == ("graded", 2, 8)
    assert (BASE_DIR / saved["code_path"] / "main.py").read_text(encoding="utf-8") == "print(int(input()) * 2)\n"


def test_passing_every_test_case_earns_every_point(monkeypatch):
    _use(monkeypatch, FakeRunTests(outcomes={"HIDDEN-NAME": ("passed", "HIDDEN-OUT", ""),
                                             "Wrong on purpose": ("passed", "99", "")}))
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Full marks", TESTS)
    body = _submit(assignment, stok).json()
    assert (body["marked"], body["earned"], body["total"]) == (True, 8, 8)
    run = _run_of(body)
    assert (run["all_passed"], run["passed"], run["total"], run["failures"]) == (True, 3, 3, [])
    assert _my_submission(assignment, stok)["final_mark"] == 8


def test_a_submitted_code_challenge_is_final(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Final", TESTS)
    sub_id = _submit(assignment, stok).json()["submission_id"]
    upload = lambda: {"code": ("main.py", io.BytesIO(b"print(1)\n"), "text/x-python")}  # noqa: E731

    again = _submit(assignment, stok)
    assert again.status_code == 409 and "already submitted" in again.json()["detail"]
    edit = client.put(f"/submissions/{sub_id}", files=upload(), headers=auth_headers(stok))
    assert edit.status_code == 409 and "can't be changed" in edit.json()["detail"]
    assert client.delete(f"/submissions/{sub_id}", headers=auth_headers(stok)).status_code == 409
    assert _my_submission(assignment, stok)["can_edit"] is False
    assert len(client.get("/submissions", headers=auth_headers(stok)).json()) == 1  # still the one submission

    # A challenge handed in as a plain file upload is final too (it just is not marked until the instructor does).
    other = new_student(client, subject["id"])
    posted = client.post("/submissions", data={"subject_id": subject["id"], "assignment_id": assignment["id"]},
                         files=upload(), headers=auth_headers(other))
    assert posted.status_code == 200, posted.text
    assert _my_submission(assignment, other)["can_edit"] is False
    assert client.put(f"/submissions/{posted.json()['id']}", files=upload(), headers=auth_headers(other)).status_code == 409
    assert client.delete(f"/submissions/{posted.json()['id']}", headers=auth_headers(other)).status_code == 409


def test_submitting_uses_none_of_the_hourly_runs_and_works_when_they_are_used_up(monkeypatch, fake):
    monkeypatch.setattr(sr, "limiter", sr.RunLimiter(per_hour=1, max_parallel=2))
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Runs used up", TESTS)
    assert _run(assignment, stok).status_code == 200
    assert _run(assignment, stok).status_code == 429                  # this hour's only run is gone

    r = _submit(assignment, stok)
    assert r.status_code == 200 and r.json()["marked"] is True       # but Submit still marks the code
    assert _run_of(r.json())["remaining_runs"] == 0                  # and took no run
    assert len(fake.calls) == 2                                      # one Run, one Submit


def test_a_marks_release_date_hides_the_mark_but_not_the_test_results(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Held back", TESTS)
    put = lambda body: client.put(f"/assignments/{assignment['id']}", headers=auth_headers(itok), json=body)  # noqa: E731
    assert put({"marks_release_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()}).status_code == 200

    body = _submit(assignment, stok).json()
    assert (body["marked"], body["earned"], body["total"]) == (True, None, None)  # the mark itself waits for the date
    assert (_run_of(body)["passed"], _run_of(body)["total"]) == (1, 3)
    held = _my_submission(assignment, stok)
    assert (held["status"], held["final_mark"], held["max_mark"], held["can_edit"]) == ("submitted", None, None, False)

    assert put({"marks_release_at": None}).status_code == 200          # released: the saved mark appears
    shown = _my_submission(assignment, stok)
    assert (shown["status"], shown["final_mark"], shown["max_mark"]) == ("graded", 2, 8)


@pytest.mark.parametrize("failure", ["sandbox off", "docker down", "no file to run", "unexpected error"])
def test_when_the_tests_cannot_run_the_code_is_still_submitted_unmarked_and_final(monkeypatch, failure):
    if failure == "sandbox off":
        monkeypatch.delenv("CODE_SANDBOX", raising=False)
    else:
        error = {"docker down": SandboxUnavailable("Docker is not available"),
                 "no file to run": ct.CodeTestError("No file."),
                 "unexpected error": RuntimeError("boom")}[failure]
        _use(monkeypatch, FakeRunTests(error=error))
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Unmarked", TESTS)

    r = _submit(assignment, stok)
    assert r.status_code == 200, r.text                               # never an error: the code is saved
    body = r.json()
    assert (body["marked"], body["complete"], body["earned"], body["total"]) == (False, True, None, None)
    [answer] = body["questions"]
    assert (answer["submitted"], answer["marked"], answer["run"], answer["earned"]) == (True, False, None, None)
    assert answer["code"] == "print(int(input()) * 2)"                # what they handed in is shown back
    assert "Docker" not in r.text and "boom" not in r.text            # the student is not told why
    mine = _my_submission(assignment, stok)
    assert (mine["status"], mine["final_mark"], mine["can_edit"]) == ("submitted", None, False)
    assert _submit(assignment, stok).status_code == 409               # and it is final all the same


def test_an_unmarked_submission_can_be_marked_by_the_instructor_afterwards(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Marked later", TESTS)
    sub_id = _submit(assignment, stok).json()["submission_id"]
    assert _my_submission(assignment, stok)["final_mark"] is None

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    monkeypatch.setattr(sr.code_testing, "run_tests", _all_pass)
    r = client.post(f"/submissions/{sub_id}/mark-from-tests", headers=auth_headers(itok))
    assert r.status_code == 200, r.text
    assert (r.json()["earned_points"], r.json()["total_points"]) == (8, 8)
    mine = _my_submission(assignment, stok)
    assert (mine["status"], mine["final_mark"], mine["max_mark"], mine["can_edit"]) == ("graded", 8, 8, False)


def test_a_busy_server_leaves_the_submission_unmarked_instead_of_refusing_it(monkeypatch, fake):
    busy = sr.RunLimiter(per_hour=10, max_parallel=1, marking_wait=0)
    monkeypatch.setattr(sr, "limiter", busy)
    busy.start(999_999)                                               # another student's run holds the only place
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Busy", TESTS)

    r = _submit(assignment, stok)
    assert r.status_code == 200 and r.json()["marked"] is False
    assert fake.calls == []
    assert _my_submission(assignment, stok)["status"] == "submitted"


def test_only_enrolled_students_can_submit_to_open_code_challenges(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Submit guards", TESTS)

    _, other_itok, other_stok = setup_subject_with_users(client)
    assert _submit(assignment, other_stok).status_code == 404         # not enrolled in this subject
    assert _submit(assignment, itok).status_code == 403               # an instructor
    assert client.post(f"/assignments/{assignment['id']}/submit-code", json={"code": "x"}).status_code == 401
    assert client.post("/assignments/999999/submit-code", headers=auth_headers(stok),
                       json={"code": "x"}).status_code == 404
    assert _submit(_challenge(itok, subject, "Not yet", TESTS, hours_open=(24, 48)), stok).status_code == 404
    closed = _submit(_challenge(itok, subject, "Over", TESTS, hours_open=(-48, -24)), stok)
    assert closed.status_code == 400 and "closed" in closed.json()["detail"]
    plain = _submit(_challenge(itok, subject, "Plain upload"), stok)
    assert plain.status_code == 400 and "only for code challenges" in plain.json()["detail"]
    assert _submit(assignment, stok, code="").status_code == 422
    assert _submit(assignment, stok, code="x" * (sr.MAX_CODE_CHARS + 1)).status_code == 422

    assert fake.calls == []                                           # none of those ran anything
    assert client.get("/submissions", headers=auth_headers(stok)).json() == []  # and none saved anything


def test_the_submitted_file_follows_the_assignments_language(fake):
    subject, itok, stok = setup_subject_with_users(client)
    ruby = _challenge(itok, subject, "Ruby only", TESTS, code_languages=["ruby"])
    r = _submit(ruby, stok, code="puts 42")
    assert r.status_code == 200, r.text
    assert fake.calls[-1]["file"] == "main.rb"
    saved = client.get(f"/submissions/{r.json()['submission_id']}", headers=auth_headers(itok)).json()
    assert (BASE_DIR / saved["code_path"] / "main.rb").read_text(encoding="utf-8") == "puts 42"

    other = new_student(client, subject["id"])
    wrong = _submit(ruby, other, language="python")
    assert wrong.status_code == 400 and "doesn't accept python" in wrong.json()["detail"]
    assert client.get("/submissions", headers=auth_headers(other)).json() == []


def test_a_marking_run_uses_no_hourly_run_but_counts_towards_the_server_cap():
    limiter = sr.RunLimiter(per_hour=1, max_parallel=1)
    limiter.start(1)
    limiter.finish(1)                                                 # the student's only run this hour is used
    with limiter.marking():
        assert limiter.remaining(1) == 0                              # marking took none, and was not refused for it
        with pytest.raises(sr.RunLimitError) as busy:
            limiter.start(2)                                          # it holds the server's only place
        assert busy.value.status == 503
    assert limiter.start(2) == 0                                      # the place is free again


def test_a_marking_run_waits_for_a_free_place_and_gives_up_after_the_wait():
    limiter = sr.RunLimiter(per_hour=10, max_parallel=1, marking_wait=5)
    limiter.start(1)                                                  # a practice run holds the only place
    went_ahead = threading.Event()

    def mark():
        with limiter.marking():
            went_ahead.set()

    worker = threading.Thread(target=mark)
    worker.start()
    assert not went_ahead.wait(0.2)                                   # it waits instead of being refused
    limiter.finish(1)
    assert went_ahead.wait(5)                                         # and goes ahead as soon as the place frees up
    worker.join(5)

    short = sr.RunLimiter(per_hour=10, max_parallel=1, marking_wait=0.05)
    short.start(1)
    with pytest.raises(sr.RunLimitError) as gave_up:
        with short.marking():
            pass
    assert gave_up.value.status == 503
    short.finish(1)
    assert short.start(2) == 9                                        # giving up left nothing behind


# --------------------------------------------------------------------------
# Getting the mark of code that was submitted without one
# --------------------------------------------------------------------------


def test_a_student_can_get_the_mark_of_code_that_was_submitted_unmarked(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)                 # the tests could not run when they submitted
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Get my marks", TESTS)
    sub_id = _submit(assignment, stok).json()["submission_id"]
    assert _my_submission(assignment, stok)["final_mark"] is None

    still_off = _get_marks(assignment, stok)                          # asking while it is still off: nothing happens
    assert still_off.status_code == 200 and still_off.json()["marked"] is False
    assert _my_submission(assignment, stok)["final_mark"] is None

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    runner = _use(monkeypatch, FakeRunTests())
    body = _get_marks(assignment, stok).json()
    assert (body["submission_id"], body["marked"], body["earned"], body["total"]) == (sub_id, True, 2, 8)
    run = _run_of(body)
    assert (run["passed"], run["total"], run["hidden_failed"]) == (1, 3, 1)
    assert run["failures"][0]["name"] == "Wrong on purpose"           # the same report Submit gives
    assert runner.calls[0]["names"] == ["Doubles", "HIDDEN-NAME", "Wrong on purpose"]
    assert not any(secret in json.dumps(body) for secret in ("HIDDEN", "points", "test_id", "visible", '"input"'))

    mine = _my_submission(assignment, stok)
    assert (mine["status"], mine["final_mark"], mine["max_mark"], mine["can_edit"]) == ("graded", 2, 8, False)
    again = _get_marks(assignment, stok)
    assert again.status_code == 409 and "already marked" in again.json()["detail"]
    assert len(runner.calls) == 1                                     # a marked submission is not run again


def test_getting_marks_checks_who_asks_and_what_was_submitted(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Mark guards", TESTS)
    assert _get_marks(assignment, stok).status_code == 404            # nothing submitted yet
    _, _, other_stok = setup_subject_with_users(client)
    assert _get_marks(assignment, other_stok).status_code == 404      # not enrolled in this subject
    assert _get_marks(assignment, itok).status_code == 403            # an instructor
    assert client.post(f"/assignments/{assignment['id']}/mark-my-code").status_code == 401
    assert client.post("/assignments/999999/mark-my-code", headers=auth_headers(stok)).status_code == 404
    plain = _challenge(itok, subject, "Plain assignment")
    assert _get_marks(plain, stok).status_code == 400
    assert _get_marks(_challenge(itok, subject, "Not yet", TESTS, hours_open=(24, 48)), stok).status_code == 404
    assert fake.calls == []                                           # none of those ran anything


def test_the_mark_can_be_fetched_after_the_deadline_and_still_respects_the_release_date(monkeypatch, fake):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Late marks", TESTS)
    _submit(assignment, stok)                                         # submitted unmarked
    now = datetime.now(timezone.utc)
    moved = client.put(f"/assignments/{assignment['id']}", headers=auth_headers(itok), json={
        "available_from": (now - timedelta(days=3)).isoformat(), "deadline": (now - timedelta(minutes=1)).isoformat(),
        "marks_release_at": (now + timedelta(days=3)).isoformat()})
    assert moved.status_code == 200, moved.text                       # closed, with the marks held back

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    body = _get_marks(assignment, stok).json()
    assert (body["marked"], body["earned"], body["total"]) == (True, None, None)  # marked, but the mark waits
    assert (_run_of(body)["passed"], _run_of(body)["total"]) == (1, 3)
    held = [a for a in client.get("/assignments", headers=auth_headers(stok)).json() if a["id"] == assignment["id"]]
    assert held[0]["my_submission"]["final_mark"] is None
    sub = client.get("/submissions", headers=auth_headers(itok), params={"subject_id": subject["id"]}).json()[0]
    assert (sub["status"], sub["final_mark"], sub["max_mark"]) == ("graded", 2, 8)  # the instructor sees it


# --------------------------------------------------------------------------
# A challenge with several tasks
# --------------------------------------------------------------------------

# Question 1 is worth 5 points, question 2 is worth 5: FakeRunTests passes the tests that expect "42".
Q1_TESTS = [
    {"name": "Doubles", "input": "21", "expected_output": "42", "visible": True, "points": 2},
    {"name": "HIDDEN-NAME", "input": "HIDDEN-IN", "expected_output": "HIDDEN-OUT", "points": 3},
]
Q2_TESTS = [
    {"name": "Triples", "input": "14", "expected_output": "42", "visible": True, "points": 4, "question": 2},
    {"name": "Wrong on purpose", "input": "1", "expected_output": "99", "visible": True, "points": 1, "question": 2},
]
QUESTIONS = [{"title": "Double it", "statement": "Print twice the number."},
             {"title": "Triple it", "statement": "Print three times the number."}]


def _two_questions(itok, subject, name, **extra):
    return _challenge(itok, subject, name, Q1_TESTS + Q2_TESTS, questions=QUESTIONS, **extra)


def _submit_question(assignment, token, question, code, **extra):
    """Hand in the code of one question."""
    return client.post(f"/assignments/{assignment['id']}/submit-code", headers=auth_headers(token),
                       json={"question": question, "code": code, **extra})


def _work(assignment, token):
    """What the student has handed in so far (the page asks for this when it opens)."""
    return client.get(f"/assignments/{assignment['id']}/my-code", headers=auth_headers(token))


def _not_handed_in(question, title):
    return {"question": question, "title": title, "submitted": False, "marked": False, "language": None,
            "code": None, "run": None, "earned": None, "total": None}


def test_students_see_each_questions_title_and_statement_but_never_a_test_case(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Two questions")

    mine = client.get(f"/assignments/{assignment['id']}", headers=auth_headers(itok)).json()  # the instructor's view
    assert [(q["id"], q["title"]) for q in mine["questions"]] == [(1, "Double it"), (2, "Triple it")]
    assert [(t["id"], t["question"], t["name"]) for t in mine["test_cases"]] == [
        (1, 1, "Doubles"), (2, 1, "HIDDEN-NAME"), (3, 2, "Triples"), (4, 2, "Wrong on purpose")]

    seen = client.get(f"/assignments/{assignment['id']}", headers=auth_headers(stok)).json()
    assert seen["questions"] == [
        {"id": 1, "title": "Double it", "statement": "Print twice the number.", "starter_code": ""},
        {"id": 2, "title": "Triple it", "statement": "Print three times the number.", "starter_code": ""}]
    listed = json.dumps(client.get("/assignments", headers=auth_headers(stok)).json())
    for secret in ("Doubles", "Triples", "HIDDEN", "Wrong on purpose", "test_cases", "expected_output"):
        assert secret not in listed and secret not in json.dumps(seen), secret


def test_run_checks_the_tests_of_the_question_it_was_sent_for(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Run a question")

    first = _run(assignment, stok, code="print(1)")                   # no question named: the first
    assert first.status_code == 200, first.text
    assert (first.json()["passed"], first.json()["total"], first.json()["hidden_failed"]) == (1, 2, 1)
    second = _run(assignment, stok, code="print(2)", question=2)
    assert (second.json()["passed"], second.json()["total"], second.json()["hidden_failed"]) == (1, 2, 0)
    assert second.json()["failures"] == [{"sample": 2, "name": "Wrong on purpose", "status": "failed",
                                          "expected_output": "99", "actual_output": "42", "error": ""}]
    # Each run used only its own question's tests, and the code was saved in a file named after the question.
    assert [(c["file"], c["names"]) for c in fake.calls] == [
        ("q1.py", ["Doubles", "HIDDEN-NAME"]), ("q2.py", ["Triples", "Wrong on purpose"])]

    missing = _run(assignment, stok, question=3)
    assert missing.status_code == 404 and "Task not found" in missing.json()["detail"]
    assert _run(assignment, stok, question=0).status_code == 422
    assert len(fake.calls) == 2                                       # neither of those ran anything


def test_each_question_is_handed_in_and_marked_on_its_own_and_the_points_add_up(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "One by one")

    first = _submit_question(assignment, stok, 1, "print(1)\r\n")
    assert first.status_code == 200, first.text
    body = first.json()
    # Question 1: Doubles (2 of its 5 points) passes. Question 2 is not handed in yet: it earns nothing for
    # now, but its 5 points are in the total.
    assert (body["marked"], body["complete"], body["earned"], body["total"]) == (True, False, 2, 10)
    one, two = body["questions"]
    assert (one["question"], one["title"], one["submitted"], one["marked"], one["earned"], one["total"]) == (
        1, "Double it", True, True, 2, 5)
    assert (one["code"], one["language"]) == ("print(1)\n", "python")
    assert (one["run"]["passed"], one["run"]["total"], one["run"]["hidden_failed"], one["run"]["failures"]) == (
        1, 2, 1, [])
    assert two == _not_handed_in(2, "Triple it")
    assert [(c["file"], c["code"], c["names"]) for c in fake.calls] == [
        ("q1.py", "print(1)\n", ["Doubles", "HIDDEN-NAME"])]           # only its own tests ran
    mine = _my_submission(assignment, stok)
    assert (mine["status"], mine["final_mark"], mine["max_mark"], mine["can_edit"], mine["questions_submitted"]) == (
        "graded", 2, 10, False, 1)

    second = _submit_question(assignment, stok, 2, "print(2)")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["submission_id"] == first.json()["submission_id"]     # every question goes into the one submission
    assert (body["marked"], body["complete"], body["earned"], body["total"]) == (True, True, 6, 10)
    one, two = body["questions"]
    assert (one["earned"], one["total"], two["earned"], two["total"]) == (2, 5, 4, 5)
    assert (two["run"]["passed"], two["run"]["total"], two["run"]["hidden_failed"]) == (1, 2, 0)
    assert two["run"]["failures"] == [{"sample": 2, "name": "Wrong on purpose", "status": "failed",
                                       "expected_output": "99", "actual_output": "42", "error": ""}]
    assert one["run"]["passed"] == 1                                   # question 1 keeps the result it got
    assert [(c["file"], c["names"]) for c in fake.calls] == [
        ("q1.py", ["Doubles", "HIDDEN-NAME"]), ("q2.py", ["Triples", "Wrong on purpose"])]  # and did not run again
    assert not any(secret in json.dumps(body) for secret in ("HIDDEN", "points", "test_id", "visible", '"input"'))

    mine = _my_submission(assignment, stok)
    assert (mine["status"], mine["final_mark"], mine["max_mark"], mine["questions_submitted"]) == ("graded", 6, 10, 2)
    saved = client.get(f"/submissions/{body['submission_id']}", headers=auth_headers(itok)).json()
    code_dir = BASE_DIR / saved["code_path"]
    assert sorted(p.name for p in code_dir.iterdir()) == ["q1.py", "q2.py"]
    assert (code_dir / "q1.py").read_text(encoding="utf-8") == "print(1)\n"
    assert (saved["status"], saved["final_mark"], saved["max_mark"]) == ("graded", 6, 10)
    assert len(client.get("/submissions", headers=auth_headers(stok)).json()) == 1


def test_a_question_can_be_handed_in_only_once(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Only once")
    handed_in = _submit_question(assignment, stok, 1, "print(1)")
    assert handed_in.status_code == 200, handed_in.text

    again = _submit_question(assignment, stok, 1, "print(99)")
    assert again.status_code == 409 and "already submitted task 1" in again.json()["detail"]
    saved = client.get(f"/submissions/{handed_in.json()['submission_id']}", headers=auth_headers(itok)).json()
    assert (BASE_DIR / saved["code_path"] / "q1.py").read_text(encoding="utf-8") == "print(1)"  # nothing changed
    assert len(fake.calls) == 1                                       # and nothing was run again
    assert _submit_question(assignment, stok, 2, "print(2)").status_code == 200  # the other question is still open


def test_a_question_not_handed_in_earns_nothing_but_its_points_still_count(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "One answer")
    body = _submit_question(assignment, stok, 2, "print(2)").json()

    assert (body["marked"], body["complete"], body["earned"], body["total"]) == (True, False, 4, 10)
    assert body["questions"][0] == _not_handed_in(1, "Double it")
    assert body["questions"][1]["submitted"] is True
    assert [c["file"] for c in fake.calls] == ["q2.py"]               # nothing was run for the other question
    saved = client.get(f"/submissions/{body['submission_id']}", headers=auth_headers(itok)).json()
    assert [p.name for p in (BASE_DIR / saved["code_path"]).iterdir()] == ["q2.py"]
    mine = _my_submission(assignment, stok)
    assert (mine["final_mark"], mine["max_mark"], mine["questions_submitted"]) == (4, 10, 1)


def test_the_answer_is_checked_before_anything_is_saved(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Answer checks", code_languages=["python"])
    post = lambda body: client.post(f"/assignments/{assignment['id']}/submit-code",  # noqa: E731
                                    headers=auth_headers(stok), json=body)

    assert post({}).status_code == 422                                # no code
    assert post({"question": 3, "code": "x"}).status_code == 404      # no such question
    assert post({"question": 1, "code": ""}).status_code == 422
    assert post({"question": 0, "code": "x"}).status_code == 422
    assert post({"question": 1, "code": "x", "language": "java"}).status_code == 422
    wrong = post({"question": 1, "code": "x", "language": "ruby"})    # a language the assignment does not accept
    assert wrong.status_code == 400 and "doesn't accept ruby" in wrong.json()["detail"]
    assert fake.calls == [] and client.get("/submissions", headers=auth_headers(stok)).json() == []

    short = post({"code": "print(1)"})                                # no question named: the first
    assert short.status_code == 200, short.text
    assert (short.json()["earned"], short.json()["total"]) == (2, 10)
    assert [q["submitted"] for q in short.json()["questions"]] == [True, False]


def test_each_question_can_be_answered_in_its_own_language(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Mixed languages", code_languages=["python", "ruby"])
    assert _submit_question(assignment, stok, 1, "print(1)", language="python").status_code == 200
    body = _submit_question(assignment, stok, 2, "puts 2", language="ruby").json()
    assert [c["file"] for c in fake.calls] == ["q1.py", "q2.rb"]
    assert [(q["language"], q["code"]) for q in body["questions"]] == [("python", "print(1)"), ("ruby", "puts 2")]


def test_reopening_the_page_shows_what_was_handed_in_with_its_report(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Reopen")
    before = _work(assignment, stok)
    assert before.status_code == 200, before.text
    assert before.json() == {"submission_id": None, "marked": False, "complete": False, "earned": None, "total": None,
                             "questions": [_not_handed_in(1, "Double it"), _not_handed_in(2, "Triple it")]}

    handed_in = _submit_question(assignment, stok, 2, "print(2)").json()
    after = _work(assignment, stok).json()
    assert after == handed_in                                         # the same picture: the report was kept
    assert after["questions"][1]["code"] == "print(2)"
    assert after["questions"][1]["run"]["failures"][0]["name"] == "Wrong on purpose"
    assert not any(secret in json.dumps(after) for secret in ("HIDDEN", "points", "test_id", "visible", '"input"'))

    other = _work(assignment, new_student(client, subject["id"])).json()  # another student sees none of it
    assert (other["submission_id"], other["questions"]) == (None, [_not_handed_in(1, "Double it"),
                                                                    _not_handed_in(2, "Triple it")])


def test_a_marks_release_date_hides_the_points_of_each_question_but_not_its_report(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Held back per question")
    put = lambda body: client.put(f"/assignments/{assignment['id']}", headers=auth_headers(itok), json=body)  # noqa: E731
    assert put({"marks_release_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()}).status_code == 200

    body = _submit_question(assignment, stok, 1, "print(1)").json()
    assert (body["marked"], body["earned"], body["total"]) == (True, None, None)
    first = body["questions"][0]
    assert (first["marked"], first["earned"], first["total"]) == (True, None, None)
    assert (first["run"]["passed"], first["run"]["total"]) == (1, 2)  # the test report is shown at once
    assert (_work(assignment, stok).json()["earned"], _my_submission(assignment, stok)["final_mark"]) == (None, None)

    assert put({"marks_release_at": None}).status_code == 200         # released: the saved points appear
    shown = _work(assignment, stok).json()
    assert (shown["earned"], shown["total"], shown["questions"][0]["earned"], shown["questions"][0]["total"]) == (
        2, 10, 2, 5)


def test_a_closed_challenge_takes_no_more_answers_but_shows_the_ones_handed_in(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Closing")
    assert _submit_question(assignment, stok, 1, "print(1)").status_code == 200
    now = datetime.now(timezone.utc)
    moved = client.put(f"/assignments/{assignment['id']}", headers=auth_headers(itok), json={
        "available_from": (now - timedelta(days=3)).isoformat(), "deadline": (now - timedelta(minutes=1)).isoformat()})
    assert moved.status_code == 200, moved.text

    late = _submit_question(assignment, stok, 2, "print(2)")
    assert late.status_code == 400 and "closed" in late.json()["detail"]
    seen = _work(assignment, stok)
    assert seen.status_code == 200, seen.text
    assert [(q["submitted"], q["earned"]) for q in seen.json()["questions"]] == [(True, 2), (False, None)]


def test_only_enrolled_students_can_read_what_was_handed_in(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Read guards")

    _, _, other_stok = setup_subject_with_users(client)
    assert _work(assignment, other_stok).status_code == 404           # not enrolled in this subject
    assert _work(assignment, itok).status_code == 403                 # an instructor
    assert client.get(f"/assignments/{assignment['id']}/my-code").status_code == 401
    assert client.get("/assignments/999999/my-code", headers=auth_headers(stok)).status_code == 404
    assert _work(_challenge(itok, subject, "Plain assignment"), stok).status_code == 400
    assert _work(_two_questions(itok, subject, "Not yet", hours_open=(24, 48)), stok).status_code == 404
    assert fake.calls == []


def test_an_answer_whose_tests_could_not_run_is_marked_later_while_another_is_marked_at_once(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)                 # the tests cannot run when question 1 is handed in
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Marked later")
    first = _submit_question(assignment, stok, 1, "print(1)").json()
    assert (first["marked"], first["earned"], first["total"]) == (False, None, None)
    assert [(q["submitted"], q["marked"], q["run"]) for q in first["questions"]] == [(True, False, None), (False, False, None)]
    assert _my_submission(assignment, stok)["final_mark"] is None

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    runner = _use(monkeypatch, FakeRunTests())
    second = _submit_question(assignment, stok, 2, "print(2)").json()
    # Question 2 has its result; question 1 is handed in and still waits for its own.
    assert (second["marked"], second["complete"], second["earned"], second["total"]) == (True, True, 4, 10)
    assert [(q["marked"], q["earned"]) for q in second["questions"]] == [(False, None), (True, 4)]
    assert [c["file"] for c in runner.calls] == ["q2.py"]

    marked = _get_marks(assignment, stok).json()
    assert (marked["earned"], marked["total"]) == (6, 10)
    assert [(q["marked"], q["earned"]) for q in marked["questions"]] == [(True, 2), (True, 4)]
    assert [c["file"] for c in runner.calls] == ["q2.py", "q1.py"]    # only the answer without a result was run
    again = _get_marks(assignment, stok)
    assert again.status_code == 409 and "already marked" in again.json()["detail"]
    assert len(runner.calls) == 2
    mine = _my_submission(assignment, stok)
    assert (mine["status"], mine["final_mark"], mine["max_mark"]) == ("graded", 6, 10)


def test_getting_the_marks_runs_every_answer_that_has_none(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX", raising=False)
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Get marks for two questions")
    assert _submit_question(assignment, stok, 1, "a").status_code == 200
    body = _submit_question(assignment, stok, 2, "b").json()
    assert (body["marked"], body["complete"]) == (False, True)        # both handed in, the tests could not run
    assert [(q["submitted"], q["marked"]) for q in body["questions"]] == [(True, False), (True, False)]

    monkeypatch.setenv("CODE_SANDBOX", "docker")
    runner = _use(monkeypatch, FakeRunTests())
    marked = _get_marks(assignment, stok).json()
    assert (marked["marked"], marked["earned"], marked["total"]) == (True, 6, 10)
    assert [q["question"] for q in marked["questions"]] == [1, 2]
    assert [c["file"] for c in runner.calls] == ["q1.py", "q2.py"]


def test_the_instructor_sees_the_tests_question_by_question_and_can_mark_the_submission(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Instructor view")
    sub_id = _submit_question(assignment, stok, 2, "print(2)").json()["submission_id"]

    r = client.post(f"/submissions/{sub_id}/run-tests", headers=auth_headers(itok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["file"], body["language"], body["passed"], body["total"]) == ("q2.py", "python", 1, 4)
    assert (body["earned_points"], body["total_points"], body["saved"]) == (4, 10, False)
    # The question that was not handed in is shown as skipped, not as wrong output.
    assert [(t["question"], t["name"], t["status"]) for t in body["results"]] == [
        (1, "Doubles", "skipped"), (1, "HIDDEN-NAME", "skipped"),
        (2, "Triples", "passed"), (2, "Wrong on purpose", "failed")]
    assert [(q["question"], q["title"], q["answered"], q["passed"], q["total"], q["earned_points"], q["total_points"])
            for q in body["questions"]] == [(1, "Double it", False, 0, 2, 0, 5), (2, "Triple it", True, 1, 2, 4, 5)]

    marked = client.post(f"/submissions/{sub_id}/mark-from-tests", headers=auth_headers(itok)).json()
    assert (marked["saved"], marked["earned_points"], marked["total_points"]) == (True, 4, 10)
    assert (_my_submission(assignment, stok)["final_mark"], _my_submission(assignment, stok)["max_mark"]) == (4, 10)


def test_the_instructors_mark_replaces_what_the_student_sees_for_each_question(monkeypatch):
    # The instructor runs the tests again (say, after fixing a test case): every question handed in gets the new result.
    _use(monkeypatch, FakeRunTests())
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "Re-marked")
    sub_id = _submit_question(assignment, stok, 1, "print(1)").json()["submission_id"]   # question 1: 2 of 5

    _use(monkeypatch, FakeRunTests(outcomes={"HIDDEN-NAME": ("passed", "HIDDEN-OUT", "")}))
    marked = client.post(f"/submissions/{sub_id}/mark-from-tests", headers=auth_headers(itok)).json()
    assert (marked["saved"], marked["earned_points"], marked["total_points"]) == (True, 5, 10)
    seen = _work(assignment, stok).json()
    assert (seen["earned"], seen["total"]) == (5, 10)
    first, second = seen["questions"]
    assert (first["earned"], first["total"], first["run"]["all_passed"], first["run"]["hidden_failed"]) == (5, 5, True, 0)
    assert first["code"] == "print(1)"                                # its file is still the one that was handed in
    assert second == _not_handed_in(2, "Triple it")                   # the instructor's run hands nothing in


def test_a_submission_made_before_answers_were_kept_one_by_one_still_works(fake):
    subject, itok, stok = setup_subject_with_users(client)
    single = _challenge(itok, subject, "Old way", TESTS)
    posted = client.post("/submissions", data={"subject_id": subject["id"], "assignment_id": single["id"]},
                         files={"code": ("main.py", io.BytesIO(b"print(1)\n"), "text/x-python")},
                         headers=auth_headers(stok))
    assert posted.status_code == 200, posted.text

    seen = _work(single, stok).json()                                 # worked out from its file
    assert (seen["submission_id"], seen["marked"], seen["complete"]) == (posted.json()["id"], False, True)
    [answer] = seen["questions"]
    assert (answer["submitted"], answer["marked"], answer["language"], answer["code"], answer["run"]) == (
        True, False, "python", "print(1)\n", None)
    assert _my_submission(single, stok)["questions_submitted"] == 1
    assert _submit(single, stok).status_code == 409                   # it is final as it stands

    body = _get_marks(single, stok).json()
    assert (body["marked"], body["earned"], body["total"]) == (True, 2, 8)
    assert (body["questions"][0]["marked"], body["questions"][0]["run"]["passed"]) == (True, 1)
    assert _work(single, stok).json() == body                         # and the result is kept from now on

    # A submission of several questions made when they were all handed in at once has no per-question
    # results: it shows what its files hold, keeps the mark it has and cannot be added to.
    two = _two_questions(itok, subject, "Old way, two questions")
    other = new_student(client, subject["id"])
    handed_in = _submit_question(two, other, 1, "print(1)").json()
    db = SessionLocal()
    try:
        db.get(Submission, handed_in["submission_id"]).question_results = None
        db.commit()
    finally:
        db.close()
    seen = _work(two, other).json()
    assert [(q["submitted"], q["marked"], q["earned"]) for q in seen["questions"]] == [(True, True, None), (False, False, None)]
    assert (seen["earned"], seen["total"]) == (2, 10)
    assert _submit_question(two, other, 2, "print(2)").status_code == 409


def test_a_challenge_with_several_questions_is_not_answered_by_uploading_a_file(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _two_questions(itok, subject, "No uploads")
    r = client.post("/submissions", data={"subject_id": subject["id"], "assignment_id": assignment["id"]},
                    files={"code": ("main.py", io.BytesIO(b"print(1)\n"), "text/x-python")},
                    headers=auth_headers(stok))
    assert r.status_code == 400 and "several tasks" in r.json()["detail"]
    assert client.get("/submissions", headers=auth_headers(stok)).json() == []
