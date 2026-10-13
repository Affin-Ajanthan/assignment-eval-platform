"""
Builds ``cases.json`` for the identifier-renaming batch (deterministic):

- TC01-TC15 x 9 languages: (original, renamed) pairs from ``programs.py``.
  A TC whose roles don't exist in a language (C has no nested functions) is
  written as an explicit N/A row, never silently dropped.
- 9 "unrelated" control pairs: each language's inventory program vs that
  language's unrelated averaging program from the invariance suite, used to
  check whether normalisation makes unrelated code look more similar.

    python tests/unixcoder_renaming/dataset/build_dataset.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from programs import SCHEMES, TEMPLATES, render, roles_in  # noqa: E402

LOCALS = ["L_CURRENT", "L_TOTAL", "L_RESULT"]
PARAMS = ["P_NAME", "P_QTY", "P_INV", "P_LIMIT"]
FUNCS = ["F_TOTAL", "F_LOW"]
METHODS = ["M_ADD", "M_REMOVE"]
NESTED = ["N_FUNC", "N_PARAM"]
LOOPS = ["LOOP_KEY", "LOOP_COUNT", "LOOP_PRODUCT", "LOOP_AMOUNT"]
ALL = ["CLASS", "FIELD"] + METHODS + PARAMS + LOCALS + FUNCS + LOOPS + NESTED

# id -> (description, roles renamed, scheme of the ORIGINAL side, scheme of the MODIFIED side, extra)
TESTS = {
    "TC01": ("rename local variables", LOCALS, "base", "alt", None),
    "TC02": ("rename function parameters", PARAMS, "base", "alt", None),
    "TC03": ("rename function names", FUNCS, "base", "alt", None),
    "TC04": ("rename local variables and parameters together", LOCALS + PARAMS, "base", "alt", None),
    "TC05": ("rename functions and variables together", FUNCS + LOCALS + LOOPS, "base", "alt", None),
    "TC06": ("short identifiers -> descriptive names", ALL, "short", "descriptive", None),
    "TC07": ("descriptive identifiers -> short names", ALL, "base", "short", None),
    "TC08": ("identifiers -> unrelated but valid names", ALL, "base", "unrelated", None),
    "TC09": ("rename class and method names", ["CLASS"] + METHODS, "base", "alt", None),
    "TC10": ("rename all identifiers + change formatting", ALL, "base", "alt", "format"),
    "TC11": ("rename all identifiers + modify comments", ALL, "base", "alt", "comments"),
    "TC12": ("rename identifiers in the nested function", NESTED, "base", "alt", None),
    "TC13": ("rename loop and conditional variables", LOOPS, "base", "alt", None),
    "TC14": ("rename identifiers in the object-oriented part",
             ["CLASS", "FIELD"] + METHODS + ["P_NAME", "P_QTY", "L_CURRENT"], "base", "alt", None),
    "TC15": ("rename identifiers across the several functions",
             FUNCS + NESTED + ["P_INV", "P_LIMIT", "L_TOTAL", "L_RESULT"] + LOOPS, "base", "alt", None),
}

INVARIANCE_ORIGINALS = HERE.parent.parent / "unixcoder_invariance" / "dataset" / "originals"
UNRELATED_FILES = {"Python": "python.py", "Java": "java.java", "JavaScript": "javascript.js", "C": "c.c",
                   "C++": "cpp.cpp", "C#": "csharp.cs", "Go": "go.go", "PHP": "php.php", "Ruby": "ruby.rb"}


def reformat(src: str, lang: str) -> str:
    """TC10 formatting change: no spaces around = + - < >, half the indentation."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip(" \t")
        lead = line[: len(line) - len(stripped)]
        lead = lead.replace("\t", "  ") if lang == "Go" else " " * (len(lead) // 2)
        if not stripped.startswith(("#", "//")):
            for op in (" = ", " + ", " - ", " < ", " > "):
                stripped = stripped.replace(op, op.strip())
        out.append(lead + stripped)
    return "\n".join(out)


def build() -> list[dict]:
    cases = []
    for lang in TEMPLATES:
        filename = TEMPLATES[lang][0]
        present = roles_in(lang)
        for tc_id, (desc, roles, orig_scheme, mod_scheme, extra) in TESTS.items():
            usable = [r for r in roles if r in present]
            base = {"id": tc_id, "language": lang, "transformation": desc, "filename": filename,
                    "renamed_roles": usable}
            if not usable:
                cases.append({**base, "status": "N/A",
                              "note": f"{lang} has no {', '.join(roles)} (e.g. no nested functions)",
                              "original": None, "modified": None})
                continue
            original = render(lang, {r: SCHEMES[orig_scheme][r] for r in usable})
            modified = render(lang, {r: SCHEMES[mod_scheme][r] for r in usable},
                              comments="changed" if extra == "comments" else "base")
            if extra == "format":
                modified = reformat(modified, lang)
            assert original != modified, f"{tc_id} {lang}: nothing changed"
            note = ""
            if lang == "C" and tc_id in {"TC09", "TC14"}:
                note = "C has no classes: struct + functions taking it"
            cases.append({**base, "status": "measure", "note": note, "original": original, "modified": modified})

        unrelated = (INVARIANCE_ORIGINALS / UNRELATED_FILES[lang]).read_text(encoding="utf-8")
        cases.append({"id": "UNRELATED", "language": lang, "transformation": "unrelated program (control)",
                      "filename": filename, "renamed_roles": [], "status": "measure",
                      "note": "inventory program vs averaging program",
                      "original": render(lang), "modified": unrelated, "modified_filename": UNRELATED_FILES[lang]})
    return cases


if __name__ == "__main__":
    cases = build()
    (HERE / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                     newline="\n")
    print(f"wrote {len(cases)} cases ({sum(c['status'] == 'N/A' for c in cases)} N/A) to {HERE / 'cases.json'}")
