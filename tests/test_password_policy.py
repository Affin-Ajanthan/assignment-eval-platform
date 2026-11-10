"""
A student or instructor whose password was set by an admin (a new account or a reset) must replace it, at their
first login, with a strong password of their own: at least 8 characters with an uppercase and a lowercase letter, a
number and a special character. Until then every other request is refused. Admins can still set short passwords
(4 characters or more), and accounts that existed before this rule keep working unchanged.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.auth import PASSWORD_CHANGE_REQUIRED, password_problems
from app.db import SessionLocal
from app.main import app as fastapi_app
from app.models import User
from tests.auth_helpers import _unique, admin_token, auth_headers, create_subject

client = TestClient(fastapi_app)
STRONG = "Str0ng!pass"


@pytest.fixture(autouse=True)
def _no_login_limit(monkeypatch):
    import app.routers.auth as auth_routes

    monkeypatch.setattr(auth_routes, "login_limiter", auth_routes._UnlockLimiter(tries=10_000))


def _new_account(role="student", password="abcd"):
    """An account just created by the admin, with a short admin-chosen password, not yet logged in."""
    admin = admin_token(client)
    subject = create_subject(client, admin)
    email = _unique(role) + "@example.com"
    r = client.post(f"/admin/{role}s", json={"email": email, "full_name": "New User", "password": password,
                                              "subject_ids": [subject["id"]]}, headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    return r.json(), email


def _login(email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def _change(token, current, new):
    return client.post("/auth/change-password", json={"current_password": current, "new_password": new},
                       headers=auth_headers(token))


# ---- The rule ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("password, missing", [
    ("Ab1!", "at least 8 characters"),
    ("abcdefg1!", "an uppercase letter"),
    ("ABCDEFG1!", "a lowercase letter"),
    ("Abcdefgh!", "a number"),
    ("Abcdefgh1", "a special character"),
    ("Abcdefg 1", "a special character"),  # a space does not count as one
])
def test_weak_passwords_are_named_by_what_they_lack(password, missing):
    assert any(p.startswith(missing) for p in password_problems(password))


@pytest.mark.parametrize("password", ["Str0ng!pass", "Aa1#aaaa", "P@ssw0rd-2026", "Ünïcødé9!x"])
def test_strong_passwords_pass(password):
    assert password_problems(password) == []


# ---- Admin side: short passwords still allowed, and they must be changed ------------------------------------------

@pytest.mark.parametrize("role", ["student", "instructor"])
def test_admin_can_still_give_a_short_password_and_it_must_be_changed(role):
    user, email = _new_account(role, password="abcd")
    assert user["must_change_password"] is True
    r = _login(email, "abcd")
    assert r.status_code == 200
    assert r.json()["user"]["must_change_password"] is True


def test_admin_minimum_of_4_characters_is_unchanged():
    admin = admin_token(client)
    r = client.post("/admin/students", json={"email": _unique("s") + "@example.com", "full_name": "X",
                                               "password": "abc", "subject_ids": []}, headers=auth_headers(admin))
    assert r.status_code == 422


# ---- Before the change: everything but "who am I" and the change itself is refused --------------------------------

def test_a_new_account_can_do_nothing_until_the_password_is_changed():
    _, email = _new_account("student")
    token = _login(email, "abcd").json()["token"]
    for path in ("/assignments", "/submissions", "/student/subjects"):
        r = client.get(path, headers=auth_headers(token))
        assert r.status_code == 403, path
        assert r.json()["detail"] == PASSWORD_CHANGE_REQUIRED
    me = client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200 and me.json()["must_change_password"] is True


def test_an_instructor_is_held_the_same_way():
    _, email = _new_account("instructor")
    token = _login(email, "abcd").json()["token"]
    assert client.get("/rubrics", headers=auth_headers(token)).json()["detail"] == PASSWORD_CHANGE_REQUIRED


# ---- The change -------------------------------------------------------------------------------------------------

def test_changing_to_a_strong_password_unlocks_the_account():
    _, email = _new_account("student")
    token = _login(email, "abcd").json()["token"]
    r = _change(token, "abcd", STRONG)
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert client.get("/assignments", headers=auth_headers(token)).status_code == 200  # same session keeps working
    assert _login(email, "abcd").status_code == 401  # the admin's password no longer works
    assert _login(email, STRONG).json()["user"]["must_change_password"] is False


@pytest.mark.parametrize("weak", ["Sh0rt!a", "abcdefgh", "Abcdefgh1", "abcdefg1!", "ABCDEFG1!"])
def test_a_weak_new_password_is_refused_and_the_account_stays_held(weak):
    assert password_problems(weak)
    _, email = _new_account("student")
    token = _login(email, "abcd").json()["token"]
    r = _change(token, "abcd", weak)
    assert r.status_code == 400 and "needs" in r.json()["detail"]
    assert client.get("/assignments", headers=auth_headers(token)).status_code == 403


def test_the_current_password_must_be_right():
    _, email = _new_account("student")
    token = _login(email, "abcd").json()["token"]
    assert _change(token, "wrong", STRONG).status_code == 400
    assert client.get("/assignments", headers=auth_headers(token)).status_code == 403


def test_the_new_password_must_differ_from_the_current_one():
    _, email = _new_account("student", password="Str0ng!pass")  # an admin may happen to choose a strong one
    token = _login(email, STRONG).json()["token"]
    assert _change(token, STRONG, STRONG).status_code == 400


def test_changing_the_password_logs_out_other_sessions_but_not_this_one():
    _, email = _new_account("student")
    other = _login(email, "abcd").json()["token"]
    this = _login(email, "abcd").json()["token"]
    assert _change(this, "abcd", STRONG).status_code == 200
    assert client.get("/auth/me", headers=auth_headers(this)).status_code == 200
    assert client.get("/auth/me", headers=auth_headers(other)).status_code == 401


def test_change_password_needs_a_login():
    r = client.post("/auth/change-password", json={"current_password": "a", "new_password": STRONG})
    assert r.status_code == 401


# ---- Admin reset, and accounts from before the rule ---------------------------------------------------------------

def test_an_admin_reset_must_be_changed_again():
    user, email = _new_account("student")
    token = _login(email, "abcd").json()["token"]
    assert _change(token, "abcd", STRONG).status_code == 200
    admin = admin_token(client)
    r = client.put(f"/admin/students/{user['id']}", json={"password": "wxyz"}, headers=auth_headers(admin))
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert _login(email, "wxyz").json()["user"]["must_change_password"] is True


def test_an_admin_edit_without_a_new_password_does_not_hold_the_account():
    user, email = _new_account("student")
    token = _login(email, "abcd").json()["token"]
    assert _change(token, "abcd", STRONG).status_code == 200
    admin = admin_token(client)
    assert client.put(f"/admin/students/{user['id']}", json={"full_name": "Renamed"},
                      headers=auth_headers(admin)).json()["must_change_password"] is False


def test_an_existing_account_with_a_short_password_keeps_working():
    """Accounts from before the rule (must_change_password False) are not asked to change anything."""
    user, email = _new_account("student")
    with SessionLocal() as db:
        db.query(User).filter(User.id == user["id"]).update({User.must_change_password: False})
        db.commit()
    r = _login(email, "abcd")
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False
    assert client.get("/assignments", headers=auth_headers(r.json()["token"])).status_code == 200


def test_the_admin_is_never_held():
    admin = admin_token(client)
    assert client.get("/auth/me", headers=auth_headers(admin)).json()["must_change_password"] is False
    assert client.get("/admin/subjects", headers=auth_headers(admin)).status_code == 200
