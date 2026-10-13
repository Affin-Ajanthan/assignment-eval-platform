"""
Builds ``cases.json``: identical-code baselines and formatting/comment
transformations for nine languages, from the hand-written programs in
``originals/``. Deterministic -- re-running produces the same file.

    python tests/unixcoder_invariance/dataset/build_dataset.py

Every transformation leaves the program's logic unchanged; only layout,
comments, line endings or the filename differ.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent

LANGUAGES = {  # language -> (original file, comment prefix)
    "Python": ("python.py", "#"),
    "Java": ("java.java", "//"),
    "JavaScript": ("javascript.js", "//"),
    "C": ("c.c", "//"),
    "C++": ("cpp.cpp", "//"),
    "C#": ("csharp.cs", "//"),
    "Go": ("go.go", "//"),
    "PHP": ("php.php", "//"),
    "Ruby": ("ruby.rb", "#"),
}
BASELINE_IDS = {"Python": "TC01", "Java": "TC02", "JavaScript": "TC03", "C": "TC04", "C++": "TC05",
                "C#": "TC06", "Go": "TC07", "PHP": "TC08", "Ruby": "TC09"}


def _is_comment(line: str, prefix: str) -> bool:
    return line.lstrip().startswith(prefix)


def change_indentation(src: str, lang: str, prefix: str) -> str:
    """Re-indent: 4 spaces -> 2 spaces (2 -> 4 for Ruby, tabs -> 4 spaces for Go)."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip(" \t")
        lead = line[: len(line) - len(stripped)]
        if lang == "Go":
            new_lead = lead.replace("\t", "    ")
        elif lang == "Ruby":
            new_lead = " " * (len(lead) * 2)
        else:
            new_lead = " " * (len(lead) // 2)
        out.append(new_lead + stripped)
    return "\n".join(out)


def add_blank_lines(src: str, lang: str, prefix: str) -> str:
    """A blank line after every line."""
    return "\n".join(line + "\n" for line in src.rstrip("\n").split("\n")) + "\n"


_OPERATORS = [" == ", " := ", " = ", " + ", " / ", " > ", " < "]


def change_operator_spacing(src: str, lang: str, prefix: str) -> str:
    """Remove the spaces around binary operators: `total = total + v` -> `total=total+v`."""
    out = []
    for line in src.split("\n"):
        if _is_comment(line, prefix) or line.lstrip().startswith("#include"):
            out.append(line)
            continue
        lead = line[: len(line) - len(line.lstrip())]
        body = line.lstrip()
        for op in _OPERATORS:
            body = body.replace(op, op.strip())
        out.append(lead + body)
    return "\n".join(out)


def change_comma_paren_spacing(src: str, lang: str, prefix: str) -> str:
    """`f(a, b)` -> `f( a ,b )`: space inside parentheses, space moved before commas."""
    out = []
    for line in src.split("\n"):
        if _is_comment(line, prefix) or line.lstrip().startswith(("#include", "<?php")):
            out.append(line)
            continue
        lead = line[: len(line) - len(line.lstrip())]
        body = line.lstrip().replace(", ", " ,").replace("(", "( ").replace(")", " )")
        out.append(lead + body)
    return "\n".join(out)


def add_comments(src: str, lang: str, prefix: str) -> str:
    """Add a header comment and a comment above every code line that starts a block."""
    lines = src.rstrip("\n").split("\n")
    insert_at = 1 if lines[0].startswith("<?php") else 0
    header = [f"{prefix} Student submission for the statistics exercise.",
              f"{prefix} Written and tested by the student."]
    out = lines[:insert_at] + header
    for line in lines[insert_at:]:
        stripped = line.strip()
        if stripped.startswith(("for", "foreach", "values.each", "if ", "if(")) and not _is_comment(line, prefix):
            lead = line[: len(line) - len(line.lstrip())]
            out.append(f"{lead}{prefix} the next statement is explained here")
        out.append(line)
    return "\n".join(out) + "\n"


def change_comments(src: str, lang: str, prefix: str) -> str:
    """Reword every existing comment."""
    replacements = iter(["Computes a mean over strictly positive inputs only.",
                         "ignore anything that is not greater than zero",
                         "extra comment"])
    out = []
    for line in src.split("\n"):
        if _is_comment(line, prefix) and not line.lstrip().startswith("#include"):
            lead = line[: len(line) - len(line.lstrip())]
            out.append(f"{lead}{prefix} {next(replacements)}")
        else:
            out.append(line)
    return "\n".join(out)


def remove_comments(src: str, lang: str, prefix: str) -> str:
    """Delete every comment line."""
    return "\n".join(l for l in src.split("\n")
                     if not (_is_comment(l, prefix) and not l.lstrip().startswith("#include")))


def change_line_endings(src: str, lang: str, prefix: str) -> str:
    """LF -> CRLF."""
    return src.replace("\n", "\r\n")


TRANSFORMATIONS = [  # (id, name, function, changes the filename?)
    ("TC10", "change indentation", change_indentation, False),
    ("TC11", "add blank lines", add_blank_lines, False),
    ("TC12", "change spaces around operators", change_operator_spacing, False),
    ("TC13", "change spaces around commas and parentheses", change_comma_paren_spacing, False),
    ("TC14", "add comments to one submission", add_comments, False),
    ("TC15", "change existing comments", change_comments, False),
    ("TC16", "remove comments from one submission", remove_comments, False),
    ("TC17", "change line endings (LF -> CRLF)", change_line_endings, False),
    ("TC18", "change the filename, identical source", lambda s, l, p: s, True),
]


def build() -> list[dict]:
    cases = []
    for lang, (filename, prefix) in LANGUAGES.items():
        original = (HERE / "originals" / filename).read_text(encoding="utf-8")
        cases.append({"id": BASELINE_IDS[lang], "language": lang, "transformation": "identical copy (baseline)",
                      "original_filename": filename, "modified_filename": filename,
                      "original": original, "modified": original})
        for tc_id, name, fn, renames in TRANSFORMATIONS:
            modified = fn(original, lang, prefix)
            if not renames:
                assert modified != original, f"{tc_id} {lang}: transformation changed nothing"
            stem, ext = filename.rsplit(".", 1)
            cases.append({"id": tc_id, "language": lang, "transformation": name,
                          "original_filename": filename,
                          "modified_filename": f"submission_{stem}_v2.{ext}" if renames else filename,
                          "original": original, "modified": modified})
    return cases


if __name__ == "__main__":
    cases = build()
    (HERE / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                     newline="\n")
    print(f"wrote {len(cases)} cases to {HERE / 'cases.json'}")
