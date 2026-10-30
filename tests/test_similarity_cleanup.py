"""Shared pieces the similarity checks use: the command-line checker runs the
website's comparison, one rule for "code/text most of the class shares", and
one way to read numeric settings."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.settings import env_float, env_int
from app.similarity import cli
from app.similarity import report_similarity as rs
from app.similarity.core import COMMON_MIN_SUBMISSIONS, common_hashes
from app.similarity_runs import code_similarity_for_dirs

ORIGINAL = """def average(marks):
    total = 0
    for m in marks:
        total = total + m
    return total / len(marks)


def grade(avg):
    if avg >= 75:
        return "A"
    if avg >= 50:
        return "B"
    return "F"
"""
# The same program padded with junk: the website removes it before fingerprinting.
PADDED = """import random
def average(marks):
    total = 0
    counter = 99
    for m in marks:
        total = total + m
    if False:
        print("never")
    return total / len(marks)


def grade(avg):
    label = "x"
    if avg >= 75:
        return "A"
    if avg >= 50:
        return "B"
    return "F"
"""
OTHER = """class Shelf:
    def __init__(self):
        self.books = []

    def add(self, book):
        self.books.append(book)
        return len(self.books)
"""


def _class(tmp_path, files):
    for student, (name, code) in files.items():
        (tmp_path / student).mkdir()
        (tmp_path / student / name).write_text(code, encoding="utf-8")
    return tmp_path


def test_the_command_line_checker_gives_the_websites_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_SIMILARITY", "0")
    root = _class(tmp_path, {"alice": ("grades.py", ORIGINAL), "bob": ("grades.py", PADDED),
                             "carol": ("shelf.php", "<?php\n$books = [];\nfunction add($b) { global $books; "
                                                    "$books[] = $b; return count($books); }\n")})
    out, js = tmp_path / "report.html", tmp_path / "report.json"
    assert cli.main(["check", str(root), "--out", str(out), "--json", str(js), "--no-semantic"]) == 0
    payload = json.loads(js.read_text(encoding="utf-8"))
    pairs = {frozenset((p["submission_a"], p["submission_b"])): p for p in payload["pairs"]}
    padded = pairs[frozenset(("alice", "bob"))]
    assert padded["jaccard"] == 1.0 and padded["token_flagged"]          # junk removed, as on the website
    assert frozenset(("alice", "carol")) in pairs                       # PHP is read (it wasn't before)
    website = code_similarity_for_dirs({d: root / d for d in ("alice", "bob", "carol")}, remove_common=True)
    assert {frozenset((p.submission_a, p.submission_b)): p.jaccard for p in website.pairs} == \
        {k: p["jaccard"] for k, p in pairs.items()}
    assert out.read_text(encoding="utf-8").strip()


def test_the_command_line_checker_needs_two_students(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_SIMILARITY", "0")
    root = _class(tmp_path, {"alice": ("grades.py", ORIGINAL)})
    assert cli.main(["check", str(root), "--out", str(tmp_path / "r.html"), "--no-semantic"]) == 1


def test_one_rule_for_what_most_of_the_class_shares():
    # present in more than half of the submissions, and in at least 4 of them
    assert common_hashes([{1, 2}, {1, 3}, {1, 4}]) == set()             # 3 submissions: never
    assert common_hashes([{1, 9}, {1, 2}, {1, 3}, {1, 4}, {5}]) == {1}  # in 4 of 5
    assert common_hashes([{1}, {1}, {1}, {1}, {2}, {2}, {2}, {2}]) == set()  # exactly half: kept
    assert COMMON_MIN_SUBMISSIONS == 4


def test_the_report_check_uses_the_same_rule():
    brief = "write a program that reads the marks file and prints the class average and the best student"
    reports = [rs.tokenize(str(i), f"{brief} and then my own text number {i} " + f"word{i} " * 30)
               for i in range(5)]
    expected = common_hashes([set(r.fingerprints) for r in reports])
    assert expected and rs.remove_common_fingerprints(reports) == len(expected)
    assert all(not (set(r.fingerprints) & expected) for r in reports)


def test_settings_fall_back_to_the_default_when_unset_or_not_a_number(monkeypatch):
    monkeypatch.delenv("TEST_SETTING", raising=False)
    assert env_float("TEST_SETTING", 0.5) == 0.5 and env_int("TEST_SETTING", 3) == 3
    monkeypatch.setenv("TEST_SETTING", "0.75")
    assert env_float("TEST_SETTING", 0.5) == 0.75
    monkeypatch.setenv("TEST_SETTING", "seven")
    assert env_float("TEST_SETTING", 0.5) == 0.5 and env_int("TEST_SETTING", 3) == 3
