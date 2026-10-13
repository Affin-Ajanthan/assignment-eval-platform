"""
False-positive risk of ``microsoft/unixcoder-base-nine`` on known-negative pairs.

Every pair in ``dataset/fp_pairs.py`` is NOT a copy. For each pair this records the
production semantic score (``normalize_code`` -> encode -> ``semantic_similarity``),
the raw-source score, the token check the app also runs (Winnowing Jaccard /
containment and its flag rule), the share of identical lines, and whether the
pair would be flagged at each experimental threshold. False-positive rates
(with Wilson 95% intervals) are computed over the known negatives.

A cohort simulation runs six independent solutions that share the same
instructor starter code through the production decision rule
(``apply_semantic_signal``: absolute 0.80 floor + cohort-outlier bar).

EXPLORATORY: no threshold here was calibrated on a representative set of real
student submissions, and the negatives were written by one author.
Results: ``results/results.md`` / ``.csv`` / ``.json``. Production code unchanged.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "dataset"))
from fp_pairs import PAIRS, STARTER_SOLUTIONS, starter  # noqa: E402

from app.similarity.core import (  # noqa: E402
    compare_all, containment_similarity, fingerprint_source, jaccard_similarity,
)
from app.similarity.semantic import (  # noqa: E402
    SemanticThresholds, apply_semantic_signal, normalize_code, semantic_similarity,
)

THRESHOLDS = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
PRODUCTION_FLOOR = SemanticThresholds().review
RESULTS_DIR = HERE / "results"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def shared_line_fraction(a: str, b: str) -> float:
    la = [l.strip() for l in a.splitlines() if l.strip()]
    lb = {l.strip() for l in b.splitlines() if l.strip()}
    return sum(1 for l in la if l in lb) / len(la) if la else 0.0


@pytest.fixture(scope="module")
def measured(encoder):
    texts = {}
    for p in PAIRS:
        for side, fn in zip(("a", "b"), p["files"]):
            texts[(p["id"], side, "production")] = normalize_code(p[side], fn)
            texts[(p["id"], side, "raw")] = p[side]
    keys = list(texts)
    emb = dict(zip(keys, encoder.encode_many([texts[k] for k in keys])))
    out = {}
    for p in PAIRS:
        fa = fingerprint_source("a", p["files"][0], p["a"])
        fb = fingerprint_source("b", p["files"][1], p["b"])
        j, c = jaccard_similarity(fa.hashes, fb.hashes), containment_similarity(fa.hashes, fb.hashes)
        out[p["id"]] = {
            "production": semantic_similarity(emb[(p["id"], "a", "production")], emb[(p["id"], "b", "production")]),
            "raw": semantic_similarity(emb[(p["id"], "a", "raw")], emb[(p["id"], "b", "raw")]),
            "jaccard": j, "containment": c, "token_flag": j >= 0.6 or c >= 0.75,
            "shared_lines": max(shared_line_fraction(p["a"], p["b"]), shared_line_fraction(p["b"], p["a"])),
        }
    return out


@pytest.fixture(scope="module")
def sink():
    state = {"rows": [], "cohort": None}
    yield state
    _write(state)


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p["id"])
def test_known_negative_pair(pair, measured, sink):
    m = measured[pair["id"]]
    # Dataset integrity: a negative pair must not be the same program.
    assert normalize_code(pair["a"], pair["files"][0]) != normalize_code(pair["b"], pair["files"][1])
    assert all(math.isfinite(m[k]) and 0.0 <= m[k] <= 1.0 for k in ("production", "raw"))
    sink["rows"].append({**{k: pair[k] for k in ("id", "language", "relationship", "why_similar")},
                         **m, "flagged_at": {t: m["production"] >= t for t in THRESHOLDS},
                         "a": pair["a"], "b": pair["b"]})


def test_starter_code_cohort_through_production_rule(encoder, sink):
    """Six students, same starter code, independent calculate_fine(): what does
    the production decision rule (token flags + semantic floor/outlier) flag?"""
    sources = {name: starter(body) for name, body in STARTER_SOLUTIONS.items()}
    fps = {name: fingerprint_source(name, "student.py", src) for name, src in sources.items()}
    pairs = compare_all(fps)
    names = list(sources)
    embs = dict(zip(names, encoder.encode_many([normalize_code(sources[n], "student.py") for n in names])))
    stats = apply_semantic_signal(pairs, embs)
    sink["cohort"] = {
        "students": len(names), "pairs": len(pairs), "stats": stats,
        "pair_rows": [{"a": p.submission_a, "b": p.submission_b, "semantic": p.semantic_similarity,
                       "jaccard": p.jaccard, "containment": p.containment,
                       "flag_level": p.flag_level} for p in pairs],
    }
    assert len(pairs) == len(list(itertools.combinations(names, 2)))


def _write(state):
    rows = state["rows"]
    if not rows:
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    rows.sort(key=lambda r: r["production"], reverse=True)
    serial = [{**r, "flagged_at": {str(k): v for k, v in r["flagged_at"].items()}} for r in rows]
    (RESULTS_DIR / "results.json").write_text(json.dumps({"pairs": serial, "cohort": state["cohort"]}, indent=2)
                                              + "\n", encoding="utf-8")
    fields = ["id", "language", "relationship", "why_similar", "production", "raw", "jaccard", "containment",
              "token_flag", "shared_lines"] + [f"flag@{t}" for t in THRESHOLDS] + ["a", "b"]
    with (RESULTS_DIR / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, **{f"flag@{t}": r["flagged_at"][t] for t in THRESHOLDS}})

    n = len(rows)
    L = ["# UniXcoder false-positive results — EXPLORATORY", "",
         f"Model `microsoft/unixcoder-base-nine`, production path (`normalize_code` -> encode -> "
         f"`semantic_similarity`). **{n} known-negative pairs** (no pair is a copy). These thresholds were not "
         "calibrated on a representative dataset of real student work, and all programs were written by one "
         "author, so every rate below is exploratory, not conclusive. A high score is not evidence of "
         "plagiarism.", "",
         "## False-positive rate by threshold (semantic score alone)", "",
         "| Threshold | Flagged negatives | False-positive rate | 95% CI (Wilson) |", "|---|---|---|---|"]
    for t in THRESHOLDS:
        k = sum(r["flagged_at"][t] for r in rows)
        lo, hi = wilson(k, n)
        mark = " (production floor)" if t == PRODUCTION_FLOOR else ""
        L.append(f"| {t:.2f}{mark} | {k}/{n} | {k / n:.0%} | {lo:.0%}-{hi:.0%} |")
    k_tok = sum(r["token_flag"] for r in rows)
    lo, hi = wilson(k_tok, n)
    L += ["", f"Token check (Winnowing: Jaccard >= 0.60 or containment >= 0.75), which the app also runs: "
              f"{k_tok}/{n} flagged ({k_tok / n:.0%}, 95% CI {lo:.0%}-{hi:.0%})."]
    L += ["", "Note: in production the semantic flag also requires the pair to be an outlier against the "
              "class's other pairs (cohort rule, >= 10 pairs); a single pair here can't be evaluated against a "
              "class, so the per-pair rates above are a worst case for the semantic signal. See the cohort "
              "simulation below.", ""]

    L += ["## Highest-scoring negative pairs", "",
          "| Rank | TC | Lang | Relationship | Production | Raw | Token J / C | Identical lines | Likely cause |",
          "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        L.append(f"| {i} | {r['id']} | {r['language']} | {r['relationship']} | **{r['production']:.3f}** | "
                 f"{r['raw']:.3f} | {r['jaccard']:.2f} / {r['containment']:.2f}"
                 f"{' (**token flag**)' if r['token_flag'] else ''} | {r['shared_lines']:.0%} | {r['why_similar']} |")

    c = state["cohort"]
    if c:
        flagged_sem = [p for p in c["pair_rows"] if p["flag_level"] == "review"]
        flagged_tok = [p for p in c["pair_rows"] if p["flag_level"] == "high"]
        sem_scores = sorted((p["semantic"] for p in c["pair_rows"] if p["semantic"] is not None), reverse=True)
        L += ["", "## Starter-code cohort simulation (production decision rule)", "",
              f"{c['students']} students submit the same instructor starter code with independently written "
              f"`calculate_fine()` bodies ({c['pairs']} pairs), run through `apply_semantic_signal` unchanged.", "",
              f"- Semantic scores: {sem_scores[-1]:.3f}-{sem_scores[0]:.3f}; cohort median "
              f"{c['stats']['cohort_median']}; effective review bar {c['stats']['review_threshold']} "
              f"(the 0.80 floor raised by the cohort-outlier rule).",
              f"- Semantic-only review flags: **{len(flagged_sem)}/{c['pairs']}**.",
              f"- Token (Winnowing) flags: **{len(flagged_tok)}/{c['pairs']}**."]
        if flagged_tok or flagged_sem:
            L.append("- Flagged pairs: " + ", ".join(
                f"{p['a']}-{p['b']} ({p['flag_level']}, semantic "
                f"{p['semantic']:.3f}, J {p['jaccard']:.2f}, C {p['containment']:.2f})"
                for p in c["pair_rows"] if p["flag_level"]) + ".")
    (RESULTS_DIR / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
