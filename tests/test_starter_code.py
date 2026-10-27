"""
Instructor starter code is excluded from the Winnowing token check.

Independent solutions built on the same starter code used to share enough
fingerprints (containment ~0.80) to get a "high" token flag. These tests
cover the subtraction itself, the starter-code cohort from the UniXcoder
false-positive batch (tests/unixcoder_false_positives), and the assignment
API/similarity endpoint, including that assignments without starter code
behave exactly as before.
"""

import importlib.util
import io
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.similarity.core import Fingerprint, compare_all, fingerprint_source, subtract_starter
from tests.auth_helpers import auth_headers, create_assignment, setup_subject_with_users, submit

# Loaded under its own module name: other suites have their own `pairs`
# module on sys.path, and a plain `import pairs` here would shadow theirs.
_spec = importlib.util.spec_from_file_location(
    "unixcoder_fp_pairs", Path(__file__).parent / "unixcoder_false_positives" / "dataset" / "fp_pairs.py")
_fp_pairs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fp_pairs)
STARTER, STARTER_SOLUTIONS, starter = _fp_pairs.STARTER, _fp_pairs.STARTER_SOLUTIONS, _fp_pairs.starter

client = TestClient(fastapi_app)

# The starter as handed out: the unimplemented function body left empty.
STARTER_HANDOUT = starter("pass")


def _cohort_fingerprints(starter_fp=None, filename="solution.py"):
    return {
        name: subtract_starter(fingerprint_source(name, filename, starter(body)), starter_fp)
        for name, body in STARTER_SOLUTIONS.items()
    }


# ---- subtract_starter ----------------------------------------------------

def test_subtract_starter_removes_starter_hashes():
    starter_fp = fingerprint_source("starter", "starter.py", STARTER_HANDOUT)
    full = fingerprint_source("s1", "solution.py", starter(STARTER_SOLUTIONS["tiers"]))
    reduced = subtract_starter(full, starter_fp)
    assert starter_fp.hashes & full.hashes, "fixture should share starter fingerprints"
    assert reduced.hashes == full.hashes - starter_fp.hashes
    assert not reduced.hashes & starter_fp.hashes
    assert reduced.hashes, "the student's own code keeps fingerprints"
    assert reduced.token_count == full.token_count
    assert full.hashes == fingerprint_source("s1", "solution.py", starter(STARTER_SOLUTIONS["tiers"])).hashes


def test_subtract_starter_only_touches_same_extension():
    starter_fp = fingerprint_source("starter", "starter.py", STARTER_HANDOUT)
    other = fingerprint_source("s1", "Main.java", "class Main { void f() { int x = 1; } }")
    assert subtract_starter(other, starter_fp) is other


def test_subtract_starter_extension_match_is_case_insensitive():
    starter_fp = fingerprint_source("starter", "starter.PY", STARTER_HANDOUT)
    full = fingerprint_source("s1", "solution.py", starter(STARTER_SOLUTIONS["loop"]))
    assert subtract_starter(full, starter_fp).hashes == full.hashes - starter_fp.hashes


def test_no_starter_is_a_no_op():
    full = fingerprint_source("s1", "solution.py", starter(STARTER_SOLUTIONS["tiers"]))
    assert subtract_starter(full, None) is full
    empty = Fingerprint(submission_id="starter", filename="starter.py", token_count=0)
    assert subtract_starter(full, empty) is full


# ---- starter-code cohort from tests/unixcoder_false_positives ------------

def test_starter_cohort_token_flags_without_subtraction():
    """Baseline (unchanged behaviour): the shared starter alone token-flags
    most pairs of independent solutions. Winnowing's hash is stable across
    processes, so the count is exact."""
    pairs = compare_all(_cohort_fingerprints())
    assert len(pairs) == 15
    assert sum(p.token_flagged for p in pairs) == 11


def test_starter_cohort_no_longer_token_flags_with_subtraction():
    starter_fp = fingerprint_source("starter", "starter.py", STARTER_HANDOUT)
    pairs = compare_all(_cohort_fingerprints(starter_fp))
    assert len(pairs) == 15
    flagged = [(p.submission_a, p.submission_b, p.jaccard, p.containment) for p in pairs if p.token_flagged]
    assert flagged == []


def test_starter_template_with_placeholder_also_works():
    """Subtracting the raw template text (with its {body} placeholder) works
    too -- what matters is the shared surrounding code."""
    starter_fp = fingerprint_source("starter", "starter.py", STARTER)
    pairs = compare_all(_cohort_fingerprints(starter_fp))
    assert not any(p.token_flagged for p in pairs)


def test_copied_solution_on_top_of_starter_is_still_flagged():
    starter_fp = fingerprint_source("starter", "starter.py", STARTER_HANDOUT)
    fps = {
        "a": subtract_starter(fingerprint_source("a", "a.py", starter(STARTER_SOLUTIONS["tiers"])), starter_fp),
        "b": subtract_starter(fingerprint_source("b", "b.py", starter(STARTER_SOLUTIONS["tiers"])), starter_fp),
    }
    (pair,) = compare_all(fps)
    assert pair.token_flagged
    assert pair.jaccard == 1.0


# ---- assignment API -------------------------------------------------------

def test_assignment_stores_starter_code_for_instructors_only():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    a = create_assignment(client, instructor_tok, subject["id"])
    assert a["starter_code"] == "" and a["starter_code_filename"] == ""

    r = client.put(f"/assignments/{a['id']}", json={"starter_code": STARTER_HANDOUT,
                                                    "starter_code_filename": "fines.py"},
                   headers=auth_headers(instructor_tok))
    assert r.status_code == 200, r.text
    assert r.json()["starter_code"] == STARTER_HANDOUT
    assert r.json()["starter_code_filename"] == "fines.py"

    # Updating something else leaves it alone.
    r = client.put(f"/assignments/{a['id']}", json={"description": "x"}, headers=auth_headers(instructor_tok))
    assert r.json()["starter_code_filename"] == "fines.py"

    student_view = client.get(f"/assignments/{a['id']}", headers=auth_headers(student_tok)).json()
    assert "starter_code" not in student_view and "starter_code_filename" not in student_view
    for listed in client.get("/assignments", headers=auth_headers(student_tok)).json():
        assert "starter_code" not in listed

    # Empty code removes it.
    r = client.put(f"/assignments/{a['id']}", json={"starter_code": ""}, headers=auth_headers(instructor_tok))
    assert r.json()["starter_code"] == "" and r.json()["starter_code_filename"] == ""


def test_starter_code_needs_a_code_file_name():
    subject, instructor_tok, _ = setup_subject_with_users(client)
    a = create_assignment(client, instructor_tok, subject["id"])
    for filename in ("", "starter", "notes.txt"):
        r = client.put(f"/assignments/{a['id']}", json={"starter_code": "x = 1\n", "starter_code_filename": filename},
                       headers=auth_headers(instructor_tok))
        assert r.status_code == 400, filename


def test_check_similarity_excludes_starter_code_and_restores_old_behaviour_without_it():
    subject, instructor_tok, _ = setup_subject_with_users(client)
    a = create_assignment(client, instructor_tok, subject["id"], "Library fines")
    for name, body in STARTER_SOLUTIONS.items():
        r = submit(client, subject["id"], a["name"],
                   {"code": (f"{name}.py", io.BytesIO(starter(body).encode()), "text/x-python")})
        assert r.status_code == 200, r.text
    url = f"/subjects/{subject['id']}/assignments/{a['name']}/check-similarity"

    # With "ignore common code" on (the default), code every student shares is
    # dropped by itself -- the shared starter flags nothing even without a file.
    body = client.post(url, headers=auth_headers(instructor_tok)).json()
    assert body["common_code_removed"] > 0
    assert sum(p["token_flagged"] for p in body["pairs"]) == 0

    # The rest of this test exercises the starter-code file on its own.
    r = client.put(f"/assignments/{a['id']}", json={"ignore_common_code": False}, headers=auth_headers(instructor_tok))
    assert r.status_code == 200 and r.json()["ignore_common_code"] is False

    # No starter code: the shared starter token-flags most pairs, as before.
    body = client.post(url, headers=auth_headers(instructor_tok)).json()
    assert body["common_code_removed"] == 0
    assert body["starter_code_excluded"] is False
    assert len(body["pairs"]) == len(list(itertools.combinations(STARTER_SOLUTIONS, 2)))
    assert sum(p["token_flagged"] for p in body["pairs"]) >= 5

    r = client.put(f"/assignments/{a['id']}", json={"starter_code": STARTER_HANDOUT,
                                                    "starter_code_filename": "starter.py"},
                   headers=auth_headers(instructor_tok))
    assert r.status_code == 200, r.text
    body = client.post(url, headers=auth_headers(instructor_tok)).json()
    assert body["starter_code_excluded"] is True
    assert not any(p["token_flagged"] for p in body["pairs"])
    assert not any(p["flagged"] for p in body["pairs"])
