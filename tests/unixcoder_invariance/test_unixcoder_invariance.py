"""
Formatting and comment invariance of the UniXcoder similarity (production path).

Dataset: ``dataset/cases.json`` (built by ``dataset/build_dataset.py`` from the
nine programs in ``dataset/originals/``): TC01-TC09 identical-copy baselines,
TC10-TC18 nine transformations per language (81 pairs).

Each pair is scored twice with the existing functions only:

- production path -- ``normalize_code`` (strips comments, anonymises
  identifiers, collapses whitespace) -> ``UniXcoderEncoder.encode_many`` ->
  ``semantic_similarity``. This is what the app does, and it decides pass/fail.
- raw -- the same encoder and similarity on the unprocessed source. Recorded
  for comparison only (status INFO): the app never embeds raw code.

Tolerances, set from a pilot measurement on 12 Oct 2026 (CPU, base-nine):

- Identical baselines deviated from 1.0 by at most 1.2e-7 (production) /
  1.8e-7 (raw): float32 rounding. -> NOISE_FLOOR = 1e-6.
- Indentation, blank lines, comment edits, line endings and filename changes
  produced byte-identical normalised text in 9/9 languages and a difference of
  0. -> these must keep identical normalised text and stay within NOISE_FLOOR.
- Operator spacing (max drop 0.045, Go; median 0.013) and comma/parenthesis
  spacing (max 0.008) survive normalisation. -> SPACING_TOLERANCE = 0.10
  (about 2x the worst measured drop), and the score must stay at or above the
  semantic review threshold (0.80) so reformatting alone can't hide a copy.

Rows whose drop is far from the other languages' for the same transformation
(> median + 3 x MAD, MAD floored at 0.002) are marked as outliers in the report.
Results go to ``results/results.md``, ``results.csv`` and ``results.json``.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import pytest

from app.similarity.semantic import SemanticThresholds, normalize_code, semantic_similarity

HERE = Path(__file__).parent
CASES = json.loads((HERE / "dataset" / "cases.json").read_text(encoding="utf-8"))
RESULTS_DIR = HERE / "results"

NOISE_FLOOR = 1e-6
SPACING_TOLERANCE = 0.10
REVIEW_THRESHOLD = SemanticThresholds().review
SPACING_CASES = {"TC12", "TC13"}  # spacing that normalize_code does not remove
BASELINE_CASES = {f"TC0{i}" for i in range(1, 10)}


def _key(case):
    return f"{case['id']}-{case['language']}"


@pytest.fixture(scope="module")
def measured(encoder):
    """Embed every distinct text once (batched) and score all 90 pairs in both modes."""
    texts = {}
    for c in CASES:
        texts[(c["original_filename"], c["original"], True)] = normalize_code(c["original"], c["original_filename"])
        texts[(c["modified_filename"], c["modified"], True)] = normalize_code(c["modified"], c["modified_filename"])
        texts[(c["original_filename"], c["original"], False)] = c["original"]
        texts[(c["modified_filename"], c["modified"], False)] = c["modified"]
    keys = list(texts)
    embeddings = dict(zip(keys, encoder.encode_many([texts[k] for k in keys])))

    rows = {}
    for c in CASES:
        for mode, pre in (("production", True), ("raw", False)):
            a = embeddings[(c["original_filename"], c["original"], pre)]
            b = embeddings[(c["modified_filename"], c["modified"], pre)]
            rows[(_key(c), mode)] = {
                "score": semantic_similarity(a, b),
                "normalized_identical": texts[(c["original_filename"], c["original"], True)]
                == texts[(c["modified_filename"], c["modified"], True)],
            }
    baselines = {(c["language"], mode): rows[(_key(c), mode)]["score"]
                 for c in CASES if c["id"] in BASELINE_CASES for mode in ("production", "raw")}
    for c in CASES:
        for mode in ("production", "raw"):
            r = rows[(_key(c), mode)]
            r["baseline"] = baselines[(c["language"], mode)]
            r["difference"] = r["baseline"] - r["score"]
    return rows


@pytest.fixture(scope="module")
def sink():
    records: list[dict] = []
    yield records
    _write_results(records)


def _verdict(case, prod) -> tuple[str, str, str]:
    """(status, tolerance, reason) for the production-path score."""
    if case["id"] in BASELINE_CASES:
        ok = abs(1.0 - prod["score"]) <= NOISE_FLOOR
        return ("PASS" if ok else "FAIL", f"|1 - score| <= {NOISE_FLOOR:g}",
                "" if ok else f"identical copy scored {prod['score']!r}")
    if case["id"] in SPACING_CASES:
        problems = []
        if prod["difference"] > SPACING_TOLERANCE:
            problems.append(f"drop {prod['difference']:.4f} > {SPACING_TOLERANCE}")
        if prod["score"] < REVIEW_THRESHOLD:
            problems.append(f"score {prod['score']:.4f} below review threshold {REVIEW_THRESHOLD}")
        return ("FAIL" if problems else "PASS", f"drop <= {SPACING_TOLERANCE} and score >= {REVIEW_THRESHOLD}",
                "; ".join(problems))
    problems = []
    if not prod["normalized_identical"]:
        problems.append("normalised text differs (preprocessing did not remove this change)")
    if abs(prod["difference"]) > NOISE_FLOOR:
        problems.append(f"difference {prod['difference']:.3g} > noise floor {NOISE_FLOOR:g}")
    return ("FAIL" if problems else "PASS", f"identical normalised text and |difference| <= {NOISE_FLOOR:g}",
            "; ".join(problems))


@pytest.mark.parametrize("case", CASES, ids=_key)
def test_invariance(case, measured, sink):
    prod, raw = measured[(_key(case), "production")], measured[(_key(case), "raw")]
    status, tolerance, reason = _verdict(case, prod)
    for mode, r, st in (("production", prod, status), ("raw", raw, "INFO")):
        sink.append({
            "id": case["id"], "language": case["language"], "transformation": case["transformation"],
            "mode": mode, "preprocessing_applied": mode == "production", "comments_removed": mode == "production",
            "normalized_text_identical": prod["normalized_identical"],
            "original_filename": case["original_filename"], "modified_filename": case["modified_filename"],
            "original": case["original"], "modified": case["modified"],
            "score": r["score"], "baseline": r["baseline"], "difference": r["difference"],
            "tolerance": tolerance if mode == "production" else "n/a (informational)",
            "status": st, "reason": reason if mode == "production" else "",
        })
    assert status == "PASS", f"{_key(case)}: {reason}"


def _mark_outliers(records):
    groups = defaultdict(list)
    for r in records:
        if r["id"] not in BASELINE_CASES:
            groups[(r["id"], r["mode"])].append(r)
    for rows in groups.values():
        diffs = [r["difference"] for r in rows]
        med = statistics.median(diffs)
        mad = max(statistics.median(abs(d - med) for d in diffs), 0.002)
        for r in rows:
            r["outlier"] = r["difference"] > med + 3 * mad
            r["group_median_difference"] = med


def _write_results(records):
    if not records:
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    _mark_outliers(records)
    order = {c["id"]: i for i, c in enumerate(CASES)}
    records.sort(key=lambda r: (r["id"], r["language"], r["mode"] != "production"))
    (RESULTS_DIR / "results.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    fields = ["id", "language", "transformation", "mode", "preprocessing_applied", "comments_removed",
              "normalized_text_identical", "score", "baseline", "difference", "tolerance", "status", "outlier",
              "reason", "original_filename", "modified_filename", "original", "modified"]
    with (RESULTS_DIR / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    prod = [r for r in records if r["mode"] == "production"]
    passed = sum(r["status"] == "PASS" for r in prod)
    lines = [
        "# UniXcoder formatting/comment invariance results", "",
        f"Model `microsoft/unixcoder-base-nine`, production path (normalize_code -> encode -> semantic_similarity). "
        f"Pairs: {len(prod)}; passed {passed}, failed {len(prod) - passed}. Raw-mode scores are informational.", "",
        "Full original/modified sources for every row are in `results.csv` / `results.json` "
        "(and `../dataset/cases.json`).", "",
        "## Summary by transformation (difference = baseline - score)", "",
        "| ID | Transformation | Production: normalised text identical | Production max drop | Raw max drop | "
        "Production result |",
        "|---|---|---|---|---|---|",
    ]
    by_tc = defaultdict(list)
    for r in records:
        by_tc[r["id"]].append(r)
    for tc_id in sorted(by_tc, key=lambda t: order[t]):
        rows = by_tc[tc_id]
        p = [r for r in rows if r["mode"] == "production"]
        raw = [r for r in rows if r["mode"] == "raw"]
        lines.append(f"| {tc_id} | {p[0]['transformation'] if tc_id not in BASELINE_CASES else 'identical copy'} | "
                     f"{sum(r['normalized_text_identical'] for r in p)}/{len(p)} | "
                     f"{max(r['difference'] for r in p):.6f} | {max(r['difference'] for r in raw):.6f} | "
                     f"{sum(r['status'] == 'PASS' for r in p)}/{len(p)} pass |")
    lines += ["", "## All pairs", "",
              "| ID | Language | Transformation | Mode | Preprocessed | Comments removed | Score | Baseline | "
              "Difference | Status | Outlier | Notes |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        lines.append(f"| {r['id']} | {r['language']} | {r['transformation']} | {r['mode']} | "
                     f"{'yes' if r['preprocessing_applied'] else 'no'} | {'yes' if r['comments_removed'] else 'no'} | "
                     f"{r['score']:.6f} | {r['baseline']:.6f} | {r['difference']:+.6f} | {r['status']} | "
                     f"{'**yes**' if r.get('outlier') else ''} | {r['reason'] or ''} |")
    (RESULTS_DIR / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
