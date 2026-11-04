"""
The instructor's side-by-side view of one code pair
(GET /subjects/{id}/assignments/{name}/code-compare): both submissions' files
and the line ranges carrying fingerprints the other one has too.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from tests.auth_helpers import auth_headers, create_assignment, setup_subject_with_users, submit

client = TestClient(fastapi_app)

# The function both copies share, at lines 4-12 of copy A and lines 6-14 of copy B.
SHARED = '''def late_fine(days_late, rate, cap):
    total = 0
    for day in range(days_late):
        if day < 7:
            total += rate
        else:
            total += rate * 2
    return min(total, cap)
'''
COPY_A = "import sys\n\n\n" + SHARED + "\nprint(late_fine(int(sys.argv[1]), 5, 100))\n"
COPY_B = ("# my library fines\nNAME = 'fines'\n\n\nheader = NAME.upper()\n" + SHARED
          + "\nfor n in [1, 8, 20]:\n    print(header, late_fine(n, 5, 100))\n")
OWN = '''class Account:
    def __init__(self, owner):
        self.owner = owner
        self.items = []

    def borrow(self, title):
        self.items.append(title)
        return len(self.items)
'''


def _class(name):
    subject, itok, stok = setup_subject_with_users(client)
    a = create_assignment(client, itok, subject["id"], name)
    ids = []
    for filename, source in (("a.py", COPY_A), ("b.py", COPY_B), ("c.py", OWN)):
        r = submit(client, subject["id"], a["name"], {"code": (filename, io.BytesIO(source.encode()), "text/x-python")})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    return subject, itok, stok, a, ids


def _compare(subject, a, x, y, tok):
    return client.get(f"/subjects/{subject['id']}/assignments/{a['name']}/code-compare",
                      params={"a": x, "b": y}, headers=auth_headers(tok))


def test_compare_shows_both_files_and_the_shared_lines():
    subject, itok, _, a, (ida, idb, idc) = _class("Fines compare")
    r = _compare(subject, a, ida, idb, itok)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shared_fingerprints"] > 0
    assert (body["a"]["submission_id"], body["b"]["submission_id"]) == (ida, idb)
    [file_a], [file_b] = body["a"]["files"], body["b"]["files"]
    assert file_a["source"] == COPY_A.rstrip("\n") and file_b["source"] == COPY_B.rstrip("\n")
    assert file_a["line_count"] == len(COPY_A.splitlines()) and not file_a["truncated"]

    def covered(f):
        return {n for r in f["ranges"] for n in range(r["start"], r["end"] + 1)}

    # The copied function is marked on both sides, where it sits in each file; each one's own code is not.
    assert set(range(5, 12)) <= covered(file_a) and set(range(7, 14)) <= covered(file_b)
    assert 1 not in covered(file_a) and not {1, 2, 5} & covered(file_b)

    # A pair that copied nothing shares at most a generic scrap or two, and never the copied function.
    other = _compare(subject, a, ida, idc, itok).json()
    assert other["shared_fingerprints"] < body["shared_fingerprints"] / 5
    assert not set(range(5, 12)) <= covered(other["a"]["files"][0])


def test_compare_only_for_two_code_submissions_of_this_assignment():
    subject, itok, _, a, (ida, idb, _) = _class("Fines compare refused")
    assert _compare(subject, a, ida, ida, itok).status_code == 404
    assert _compare(subject, a, ida, 999999, itok).status_code == 404
    elsewhere = create_assignment(client, itok, subject["id"], "Another assignment")
    assert _compare(subject, elsewhere, ida, idb, itok).status_code == 404


def test_compare_is_for_the_subjects_instructors_only():
    subject, _, stok, a, (ida, idb, _) = _class("Fines compare private")
    assert _compare(subject, a, ida, idb, stok).status_code == 403  # a student
    _, other_instructor, _ = setup_subject_with_users(client)
    assert _compare(subject, a, ida, idb, other_instructor).status_code == 403  # another subject's instructor
