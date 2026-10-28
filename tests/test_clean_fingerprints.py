"""Token fingerprints come from the code without junk (unused variables, dead
branches), the same cleanup the semantic check uses (python_cleanup,
ts_cleanup), so padding a copy doesn't lower its Jaccard -- in both the
instructor's similarity check and the student self-check, which share
app/similarity_runs.py. Removed code keeps its line breaks, so highlights
still point at the student's real lines."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import self_checks
from app.similarity.core import fingerprint_source, jaccard_similarity
from app.similarity.python_cleanup import strip_python_dead_code
from app.similarity.semantic import strip_junk
from app.similarity.ts_cleanup import strip_dead_code
from app.similarity_runs import code_similarity_for_dirs

PY_ORIGINAL = """def average(marks):
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

# The same program padded the way a copier would: unused variables, a dead
# branch, a junk import and code after a return.
PY_PADDED = """import random
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
    print("unreachable")
"""

JAVA_ORIGINAL = """public class Grades {
    static double average(int[] marks) {
        int sum = 0;
        for (int m : marks) {
            sum += m;
        }
        return (double) sum / marks.length;
    }

    static String grade(double avg) {
        if (avg >= 75) {
            return "A";
        }
        return "F";
    }
}
"""

JAVA_PADDED = """public class Grades {
    static double average(int[] marks) {
        int sum = 0;
        int junk = 7;
        for (int m : marks) {
            String unused = "pad";
            sum += m;
        }
        if (false) {
            System.out.println("never");
        }
        return (double) sum / marks.length;
    }

    static String grade(double avg) {
        if (avg >= 75) {
            return "A";
        }
        return "F";
    }
}
"""


def _jaccard(a: str, b: str, name: str) -> float:
    return jaccard_similarity(fingerprint_source("a", name, a).hashes, fingerprint_source("b", name, b).hashes)


def _run(tmp_path, files: dict[str, tuple[str, str]]):
    dirs = {}
    for sid, (name, source) in files.items():
        d = tmp_path / sid
        d.mkdir(parents=True)
        (d / name).write_text(source, encoding="utf-8")
        dirs[sid] = d
    return code_similarity_for_dirs(dirs)


def test_keep_lines_blanks_removed_code_but_keeps_every_line_number():
    for cleaned, original in ((strip_python_dead_code(PY_PADDED, keep_lines=True), PY_PADDED),
                              (strip_dead_code(JAVA_PADDED, "java", keep_lines=True), JAVA_PADDED)):
        assert cleaned != original                                  # something was removed
        old, new = original.splitlines(), cleaned.splitlines()
        assert len(new) == len(old)
        for before, after in zip(old, new):
            assert after == before or not after.strip()             # a line is kept as is, or blanked
    # without keep_lines the removed code's lines go (what the semantic check uses)
    assert len(strip_python_dead_code(PY_PADDED).splitlines()) < len(PY_PADDED.splitlines())


def test_padding_no_longer_lowers_the_token_score(tmp_path):
    for name, original, padded in (("main.py", PY_ORIGINAL, PY_PADDED), ("Grades.java", JAVA_ORIGINAL, JAVA_PADDED)):
        raw = _jaccard(original, padded, name)
        assert raw < 0.75, (name, raw)                              # the raw code hides the copy...
        run = _run(tmp_path / name, {"a": (name, original), "b": (name, padded)})
        assert run.pairs[0].jaccard == 1.0, name                    # ...the cleaned code doesn't
        assert run.pairs[0].token_flagged


def test_honest_code_is_not_made_more_similar(tmp_path):
    other = """def mean(values):
    if not values:
        return 0
    return sum(values) / len(values)
"""
    run = _run(tmp_path, {"a": ("main.py", PY_ORIGINAL), "b": ("main.py", other)})
    assert run.pairs[0].jaccard == _jaccard(PY_ORIGINAL, other, "main.py")  # no junk: same score as before


def test_highlights_point_at_the_students_own_lines(tmp_path):
    run = _run(tmp_path, {"a": ("main.py", PY_ORIGINAL), "b": ("main.py", PY_PADDED)})
    padded_file = run.files_by_submission["b"][0]
    assert padded_file.source == PY_PADDED                         # shown text is the original file
    highlights = self_checks.code_highlights([padded_file], run.fingerprints["a"].hashes)
    assert highlights
    lines = PY_PADDED.splitlines()
    for h in highlights:
        # the line numbers and the text agree with the file the student submitted
        assert h["text"].splitlines()[0] == lines[h["start_line"] - 1]
    assert highlights[0]["start_line"] == 2                         # "def average", not the junk import on line 1


def test_a_variable_another_file_uses_is_not_removed(tmp_path):
    # a top-level constant read by another file isn't junk (external names)
    config = "LIMIT = 10\n"
    assert strip_junk(config, "config.py", {"LIMIT", "print"}, keep_lines=True) == config


def test_languages_without_a_cleanup_are_fingerprinted_unchanged():
    kotlin = "fun main() {\n    val unused = 5\n}\n"
    assert strip_junk(kotlin, "Main.kt", keep_lines=True) == kotlin
