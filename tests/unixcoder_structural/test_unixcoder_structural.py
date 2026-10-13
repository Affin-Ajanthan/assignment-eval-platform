"""
Structural-transformation robustness of ``microsoft/unixcoder-base-nine`` (Python).

For every pair in ``dataset/pairs.py``:

1. Relationship check -- both programs are EXECUTED (isolated namespaces) on the
   listed edge-case inputs plus 200 seeded random inputs; behaviour-preserving
   pairs must return identical results (or raise the same exception type).
   Structural/equivalent pairs must also still differ after the production
   preprocessing, so the measured change is structural, not cosmetic.
2. Similarity -- existing ``normalize_code`` -> ``UniXcoderEncoder.encode_many``
   -> ``semantic_similarity`` (production), plus the raw source (informational).
3. Comparison with baselines -- identical code (1.0) and the band of unrelated
   control pairs.

Scope/limitations: Python only, because behaviour is verified by execution and
some transformations (list comprehensions, conditional expressions) are
Python-specific. Similarity scores are measurements, never plagiarism labels.
Results: ``results/results.md`` / ``.csv`` / ``.json``.
"""

from __future__ import annotations

import copy
import csv
import json
import statistics
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "dataset"))
from pairs import all_cases  # noqa: E402

from app.similarity.semantic import SemanticThresholds, normalize_code, semantic_similarity  # noqa: E402

CASES = all_cases()
RESULTS_DIR = HERE / "results"
REVIEW = SemanticThresholds().review
CATEGORY_LABEL = {
    "superficial": "Same source, superficial changes",
    "structural": "Similar implementation, structural changes",
    "equivalent": "Functionally equivalent, different implementation",
    "unrelated": "Unrelated code (control)",
}


def _run(source: str, entry: str, args: tuple):
    namespace: dict = {}
    exec(compile(source, "<pair>", "exec"), namespace)  # test-owned code, not user input
    try:
        return ("ok", namespace[entry](*copy.deepcopy(args)))
    except Exception as exc:
        return ("error", type(exc).__name__)


def verify(case) -> tuple[bool | None, str]:
    """(preserves behaviour?, detail). None for unrelated controls."""
    if case["category"] == "unrelated":
        return None, "different tasks; behaviour not comparable"
    inputs = list(case["inputs"]) + case.get("random_inputs", [])
    for args in inputs:
        a, b = _run(case["original"], case["entry"], args), _run(case["modified"], case["entry"], args)
        if a != b:
            return False, f"differs for input {args!r}: {a!r} vs {b!r}"
    return True, f"identical results on {len(inputs)} inputs ({len(case['inputs'])} edge cases + " \
                 f"{len(inputs) - len(case['inputs'])} random)"


@pytest.fixture(scope="module")
def measured(encoder):
    texts = {}
    for c in CASES:
        for side in ("original", "modified"):
            texts[("production", c[side])] = normalize_code(c[side], "x.py")
            texts[("raw", c[side])] = c[side]
    keys = list(texts)
    emb = dict(zip(keys, encoder.encode_many([texts[k] for k in keys])))
    out = {}
    for c in CASES:
        out[c["id"]] = {mode: semantic_similarity(emb[(mode, c["original"])], emb[(mode, c["modified"])])
                        for mode in ("production", "raw")}
        out[c["id"]]["normalized_identical"] = texts[("production", c["original"])] == texts[("production", c["modified"])]
    return out


@pytest.fixture(scope="module")
def sink():
    rows: list[dict] = []
    yield rows
    _write(rows)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_structural_pair(case, measured, sink):
    preserves, detail = verify(case)
    m = measured[case["id"]]
    problems = []
    if case["category"] != "unrelated" and preserves is not True:
        problems.append(f"claimed behaviour-preserving but {detail}")
    if case["category"] in {"structural", "equivalent"} and m["normalized_identical"]             and not case.get("removed_by_cleanup"):
        problems.append("preprocessing erases the change, so this is not a structural transformation")
    if case.get("removed_by_cleanup") and not m["normalized_identical"]:
        problems.append("expected the dead-code cleanup to remove this change, but it did not")
    sink.append({"id": case["id"], "category": case["category"], "transformation": case["transformation"],
                 "preserves_behaviour": preserves, "verification": detail,
                 "normalized_identical": m["normalized_identical"],
                 "production": m["production"], "raw": m["raw"],
                 "status": "PASS" if not problems else "FAIL", "problems": "; ".join(problems),
                 "original": case["original"], "modified": case["modified"]})
    assert not problems, "; ".join(problems)


def _write(rows):
    if not rows:
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    rows.sort(key=lambda r: (list(CATEGORY_LABEL).index(r["category"]), r["id"]))
    (RESULTS_DIR / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with (RESULTS_DIR / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    unrel = [r for r in rows if r["category"] == "unrelated"]
    band = {mode: (min(r[mode] for r in unrel), statistics.mean(r[mode] for r in unrel), max(r[mode] for r in unrel))
            for mode in ("production", "raw")}
    lo, mean_u, hi = band["production"]
    passed = sum(r["status"] == "PASS" for r in rows)

    L = ["# UniXcoder structural-transformation results (Python)", "",
         f"Model `microsoft/unixcoder-base-nine`. {len(rows)} pairs, {passed} passed verification, "
         f"{len(rows) - passed} failed. Production = `normalize_code` -> encode -> `semantic_similarity` "
         f"(what the app uses); raw = unprocessed source (informational).", "",
         "Baselines: identical code = **1.000**; unrelated controls (different tasks) = production "
         f"**{lo:.3f}-{hi:.3f}** (mean {mean_u:.3f}), raw {band['raw'][0]:.3f}-{band['raw'][2]:.3f}. "
         f"Semantic review threshold: {REVIEW}.", "",
         "Behaviour was verified by executing both programs on edge cases plus 200 seeded random inputs. "
         "Scores are similarity measurements, not plagiarism labels.", "",
         "## Ranked by production score drop (structural and equivalent pairs)", "",
         "| Rank | TC | Category | Transformation | Production | Drop from 1.0 | Position | Raw | Behaviour |",
         "|---|---|---|---|---|---|---|---|---|"]
    ranked = sorted([r for r in rows if r["category"] in {"structural", "equivalent"}], key=lambda r: r["production"])
    for i, r in enumerate(ranked, 1):
        if r["production"] <= hi:
            pos = "**within unrelated band**"
        elif r["production"] < REVIEW:
            pos = "below review threshold"
        else:
            pos = "at/above review threshold"
        L.append(f"| {i} | {r['id']} | {r['category']} | {r['transformation']} | {r['production']:.3f} | "
                 f"{1 - r['production']:.3f} | {pos} | {r['raw']:.3f} | "
                 f"{'preserved' if r['preserves_behaviour'] else 'NOT preserved'} |")

    L += ["", "## By category (production)", "", "| Category | Pairs | Min | Mean | Max |", "|---|---|---|---|---|"]
    for cat, label in CATEGORY_LABEL.items():
        vals = [r["production"] for r in rows if r["category"] == cat]
        L.append(f"| {label} | {len(vals)} | {min(vals):.3f} | {statistics.mean(vals):.3f} | {max(vals):.3f} |")

    L += ["", "## All pairs", "", "| ID | Category | Transformation | Production | Raw | Erased by preprocessing | "
          "Verification | Status |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['id']} | {r['category']} | {r['transformation']} | {r['production']:.3f} | {r['raw']:.3f} | "
                 f"{'yes' if r['normalized_identical'] else 'no'} | {r['verification']} | {r['status']} |")
    L += ["", "## Assumptions and limitations", "",
          "- Python only: behaviour is verified by execution, and list comprehensions / conditional expressions "
          "are Python constructs. Earlier batches showed scores vary by language, so these numbers are not "
          "assumed to transfer to other languages.",
          "- Equivalence is checked on representative and random inputs, not proven for all inputs.",
          "- Programs are small (5-20 lines); in a larger submission one transformed function is diluted by the "
          "unchanged code around it, so whole-submission drops would usually be smaller.",
          "- TC17's dead branches never execute on any input (the `elif` condition is implied false by the "
          "preceding `if`), so behaviour is unchanged by construction as well as by test."]
    (RESULTS_DIR / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
