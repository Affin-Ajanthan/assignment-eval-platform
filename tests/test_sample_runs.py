"""Students running their typed code against a code challenge's visible tests
(POST /assignments/{id}/sample-run, app/routers/sample_runs.py).

The runner is faked, so these tests need no Docker.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.evaluator import code_testing as ct
from app.evaluator.code_execution import SandboxUnavailable
from app.main import app as fastapi_app
from app.routers import sample_runs as sr
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
    return client.post(f"/assignments/{assignment['id']}/sample-run", headers=auth_headers(token),
                       json={"code": code, **extra})


class FakeRunTests:
    """Stands in for code_testing.run_tests: records what it was given and
    answers 'passed' for the tests expecting 42."""

    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, code_dir, tests, *, main_file="", only_visible=False, **kwargs):
        if self.error:
            raise self.error
        self.calls.append({"file": main_file, "code": (Path(code_dir) / main_file).read_text(encoding="utf-8"),
                           "names": [t["name"] for t in tests], "only_visible": only_visible})
        results = [ct.TestResult(test_id=t["id"], name=t["name"], visible=t["visible"], points=t["points"],
                                 match=t["match"], status="passed" if t["expected_output"] == "42" else "failed",
                                 passed=t["expected_output"] == "42", expected_output=t["expected_output"],
                                 actual_output="42") for t in tests if t["visible"] or not only_visible]
        return ct.TestRun(file=main_file, language="python", results=results)


@pytest.fixture
def fake(monkeypatch):
    runner = FakeRunTests()
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
# The endpoint
# --------------------------------------------------------------------------


def test_a_student_runs_their_code_against_the_visible_tests_only(fake):
    subject, itok, stok = setup_subject_with_users(client)
    assignment = _challenge(itok, subject, "Visible only", TESTS)
    r = _run(assignment, stok, code="print(int(input()) * 2)\r\n")
    assert r.status_code == 200, r.text
    body = r.json()

    assert (body["language"], body["passed"], body["total"], body["hidden_test_count"]) == ("python", 1, 2, 1)
    assert body["remaining_runs"] == 9
    assert [(x["name"], x["status"], x["passed"]) for x in body["results"]] == [
        ("Doubles", "passed", True), ("Wrong on purpose", "failed", False)]
    first = body["results"][0]
    assert (first["input"], first["expected_output"], first["actual_output"], first["match"]) == (
        "21", "42", "42", "exact")
    # Only the visible tests reached the runner, and the typed code was saved as main.py (newlines unified).
    assert fake.calls == [{"file": "main.py", "code": "print(int(input()) * 2)\n",
                           "names": ["Doubles", "Wrong on purpose"], "only_visible": True}]
    # Nothing about the hidden test, and no ids or points that could hint at it.
    assert not any(secret in json.dumps(body) for secret in ("HIDDEN", "points"))
    assert set(first) == {"name", "input", "match", "expected_output", "status", "passed", "actual_output", "stderr"}


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
    assert client.post("/assignments/999999/sample-run", headers=auth_headers(stok),
                       json={"code": "x"}).status_code == 404
    assert client.post(f"/assignments/{assignment['id']}/sample-run", json={"code": "x"}).status_code == 401

    upcoming = _challenge(itok, subject, "Upcoming", TESTS, hours_open=(24, 48))
    assert _run(upcoming, stok).status_code == 404                            # not visible to students yet
    closed = _challenge(itok, subject, "Closed", TESTS, hours_open=(-48, -24))
    r = _run(closed, stok)
    assert r.status_code == 400 and "closed" in r.json()["detail"]
    plain = _challenge(itok, subject, "Plain submission")
    r = _run(plain, stok)
    assert r.status_code == 400 and "only for code challenges" in r.json()["detail"]
    hidden_only = _challenge(itok, subject, "Hidden only", [TESTS[1]])
    r = _run(hidden_only, stok)
    assert r.status_code == 400 and "no sample tests" in r.json()["detail"]
    assert fake.calls == []  # none of those ran anything


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
