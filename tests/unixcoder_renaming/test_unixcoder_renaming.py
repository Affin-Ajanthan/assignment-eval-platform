"""
Identifier-renaming batch for ``microsoft/unixcoder-base-nine``.

Dataset: ``dataset/cases.json`` (built by ``dataset/build_dataset.py`` from the
templates in ``dataset/programs.py``): TC01-TC15 renaming pairs in nine
languages plus one unrelated-program control pair per language.

Every pair is scored with the existing ``UniXcoderEncoder.encode_many`` and
``semantic_similarity`` in three modes (production code unchanged):

- raw        -- the source as written;
- cleaned    -- comments stripped and whitespace collapsed, identifiers KEPT
                (experimental: the comment regexes from app/similarity/semantic.py,
                without the identifier anonymisation step);
- production -- ``normalize_code`` (cleaned + identifiers anonymised), which is
                what the app actually embeds.

raw -> cleaned isolates the effect of comments/whitespace; cleaned ->
production isolates identifier normalisation. A similarity score is a
measurement, not a plagiarism verdict. The tests assert only that every pair
was measured with valid output and that identical code scores 1.0; the
analysis is written to ``results/``.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import pytest

from app.similarity import semantic
from app.similarity.semantic import SemanticThresholds, normalize_code, semantic_similarity

HERE = Path(__file__).parent
CASES = json.loads((HERE / "dataset" / "cases.json").read_text(encoding="utf-8"))
RESULTS_DIR = HERE / "results"
MODES = ("raw", "cleaned", "production")
REVIEW_THRESHOLD = SemanticThresholds().review
NOISE_FLOOR = 1e-6  # identical code (float32 rounding), from the invariance batch


def cleaned(source: str, filename: str) -> str:
    """normalize_code without identifier anonymisation (experimental mode)."""
    pattern = (semantic._HASH_COMMENT_RE if Path(filename).suffix.lower() in semantic._HASH_COMMENT_LANGS
               else semantic._C_COMMENT_RE)
    stripped = pattern.sub(lambda m: "" if m.lastgroup == "comment" else m.group(), source)
    return " ".join(stripped.split())


PREPARE = {
    "raw": lambda src, fn: src,
    "cleaned": cleaned,
    "production": normalize_code,
}


def _key(case):
    return f"{case['id']}-{case['language']}"


@pytest.fixture(scope="module")
def measured(encoder):
    """Encode every distinct prepared text once, then score all pairs and baselines."""
    jobs = {}
    for c in CASES:
        if c["status"] != "measure":
            continue
        mod_fn = c.get("modified_filename", c["filename"])
        for mode in MODES:
            jobs[(mode, c["filename"], c["original"])] = PREPARE[mode](c["original"], c["filename"])
            jobs[(mode, mod_fn, c["modified"])] = PREPARE[mode](c["modified"], mod_fn)
    keys = list(jobs)
    emb = dict(zip(keys, encoder.encode_many([jobs[k] for k in keys])))

    out = {}
    for c in CASES:
        if c["status"] != "measure":
            continue
        mod_fn = c.get("modified_filename", c["filename"])
        row = {}
        for mode in MODES:
            a, b = emb[(mode, c["filename"], c["original"])], emb[(mode, mod_fn, c["modified"])]
            row[mode] = {"score": semantic_similarity(a, b), "baseline": semantic_similarity(a, a),
                         "texts_identical": jobs[(mode, c["filename"], c["original"])]
                         == jobs[(mode, mod_fn, c["modified"])]}
        out[_key(c)] = row
    return out


@pytest.fixture(scope="module")
def sink():
    rows: list[dict] = []
    yield rows
    _write_results(rows)


@pytest.mark.parametrize("case", CASES, ids=_key)
def test_renaming_pair(case, measured, sink):
    base = {k: case[k] for k in ("id", "language", "transformation", "renamed_roles", "note", "filename")}
    if case["status"] == "N/A":
        sink.append({**base, "mode": "all", "status": "N/A", "original": None, "modified": None})
        return  # recorded explicitly as not applicable to this language, not skipped
    row = measured[_key(case)]
    problems = []
    for mode in MODES:
        r = row[mode]
        if not (math.isfinite(r["score"]) and 0.0 <= r["score"] <= 1.0):
            problems.append(f"{mode}: invalid score {r['score']!r}")
        if abs(1.0 - r["baseline"]) > NOISE_FLOOR:
            problems.append(f"{mode}: identical code scored {r['baseline']!r}")
        sink.append({**base, "mode": mode, "preprocessing": mode != "raw",
                     "identifiers_normalized": mode == "production", "comments_removed": mode != "raw",
                     "score": r["score"], "baseline": r["baseline"], "drop": r["baseline"] - r["score"],
                     "texts_identical_after_prep": r["texts_identical"],
                     "status": "PASS" if not problems else "FAIL",
                     "original": case["original"], "modified": case["modified"]})
    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _fmt(x):
    return f"{x:.4f}"


def _write_results(rows):
    if not rows:
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    fields = ["id", "language", "transformation", "mode", "preprocessing", "identifiers_normalized",
              "comments_removed", "score", "baseline", "drop", "texts_identical_after_prep", "status", "note",
              "renamed_roles", "original", "modified"]
    with (RESULTS_DIR / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    measured = [r for r in rows if r.get("mode") in MODES]
    rename = [r for r in measured if r["id"] != "UNRELATED"]
    control = [r for r in measured if r["id"] == "UNRELATED"]
    na = [r for r in rows if r.get("status") == "N/A"]
    get = defaultdict(dict)
    for r in measured:
        get[(r["id"], r["language"])][r["mode"]] = r
    langs = list(dict.fromkeys(r["language"] for r in rename))
    tcs = sorted({r["id"] for r in rename})
    desc = {r["id"]: r["transformation"] for r in rename}

    def mean_drop(sel, mode):
        vals = [r["drop"] for r in sel if r["mode"] == mode]
        return statistics.mean(vals) if vals else float("nan")

    passed = sum(r["status"] == "PASS" for r in measured)
    L = ["# UniXcoder identifier-renaming results", "",
         f"Model `microsoft/unixcoder-base-nine`. {len(rename) // 3} renaming pairs + {len(control) // 3} "
         f"unrelated controls, each scored in 3 modes ({passed}/{len(measured)} measurements valid); "
         f"{len(na)} case(s) not applicable: " + ", ".join(f"{r['id']} {r['language']} ({r['note']})" for r in na)
         + ".", "",
         "Modes: **raw** = source as written; **cleaned** = comments stripped + whitespace collapsed, names kept "
         "(experimental); **production** = `normalize_code` (cleaned + identifiers anonymised), what the app "
         "embeds. Drop = identical-code score (1.0) - pair score. Scores are similarity measurements, not "
         "plagiarism verdicts.", ""]

    # 1. Languages
    L += ["## 1. Languages most affected by renaming (mean drop over TC01-TC15)", "",
          "| Language | raw | cleaned | production | production: renames fully erased |", "|---|---|---|---|---|"]
    lang_rows = []
    for lang in langs:
        sel = [r for r in rename if r["language"] == lang]
        erased = sum(1 for r in sel if r["mode"] == "production" and r["texts_identical_after_prep"])
        n = sum(1 for r in sel if r["mode"] == "production")
        lang_rows.append((mean_drop(sel, "raw"), lang, mean_drop(sel, "cleaned"), mean_drop(sel, "production"),
                          f"{erased}/{n}"))
    for raw_d, lang, cl_d, pr_d, erased in sorted(lang_rows, reverse=True):
        L.append(f"| {lang} | {_fmt(raw_d)} | {_fmt(cl_d)} | {_fmt(pr_d)} | {erased} |")

    # 2. Transformations
    L += ["", "## 2. Transformations by score reduction", "",
          "| TC | Transformation | raw mean / max drop | cleaned mean / max | production mean / max | "
          "production: renames fully erased |", "|---|---|---|---|---|---|"]
    tc_rows = []
    for tc in tcs:
        sel = [r for r in rename if r["id"] == tc]
        m = {mode: [r["drop"] for r in sel if r["mode"] == mode] for mode in MODES}
        erased = sum(1 for r in sel if r["mode"] == "production" and r["texts_identical_after_prep"])
        tc_rows.append((statistics.mean(m["raw"]), tc, m, erased, len(m["production"])))
    for _, tc, m, erased, n in sorted(tc_rows, reverse=True):
        L.append(f"| {tc} | {desc[tc]} | " + " | ".join(
            f"{_fmt(statistics.mean(m[mode]))} / {_fmt(max(m[mode]))}" for mode in MODES) + f" | {erased}/{n} |")

    # 3. Does normalisation help?
    better = worse = same = 0
    worst_cases = []
    for (tc, lang), modes in get.items():
        if tc == "UNRELATED":
            continue
        d_clean, d_prod = modes["cleaned"]["drop"], modes["production"]["drop"]
        if d_prod < d_clean - NOISE_FLOOR:
            better += 1
        elif d_prod > d_clean + NOISE_FLOOR:
            worse += 1
            worst_cases.append((d_prod - d_clean, tc, lang))
        else:
            same += 1
    L += ["", "## 3. Does identifier normalisation improve renamed-pair scores?", "",
          f"Comparing **production** with **cleaned** (same comment/whitespace handling, only identifier "
          f"normalisation differs): smaller drop in {better} pairs, larger in {worse}, unchanged in {same}. "
          f"Mean drop: raw {_fmt(mean_drop(rename, 'raw'))}, cleaned {_fmt(mean_drop(rename, 'cleaned'))}, "
          f"production {_fmt(mean_drop(rename, 'production'))}."]
    if worst_cases:
        L.append("Pairs where normalisation made the drop larger: " + ", ".join(
            f"{tc} {lang} (+{_fmt(d)})" for d, tc, lang in sorted(worst_cases, reverse=True)[:8]) + ".")

    # 4. Unrelated code
    L += ["", "## 4. Does normalisation make unrelated code look more similar?", "",
          "Each language's inventory program vs its unrelated averaging program.", "",
          "| Language | raw | cleaned | production | production - raw | production - cleaned | "
          f">= review threshold ({REVIEW_THRESHOLD})? |", "|---|---|---|---|---|---|---|"]
    inflated = []
    for lang in langs:
        m = get[("UNRELATED", lang)]
        s = {mode: m[mode]["score"] for mode in MODES}
        if s["production"] > s["cleaned"] + NOISE_FLOOR:
            inflated.append(lang)
        L.append(f"| {lang} | {_fmt(s['raw'])} | {_fmt(s['cleaned'])} | {_fmt(s['production'])} | "
                 f"{s['production'] - s['raw']:+.4f} | {s['production'] - s['cleaned']:+.4f} | "
                 f"{'**yes**' if s['production'] >= REVIEW_THRESHOLD else 'no'} |")
    L += ["", f"Normalisation raised the unrelated-pair score (vs cleaned) in {len(inflated)}/{len(langs)} "
              f"languages" + (f": {', '.join(inflated)}." if inflated else ".")]

    # Per-pair table
    L += ["", "## All pairs", "",
          "| TC | Language | Transformation | raw | cleaned | production | production drop | "
          "renames erased by normalisation | Note |", "|---|---|---|---|---|---|---|---|---|"]
    for (tc, lang), modes in sorted(get.items()):
        p = modes["production"]
        L.append(f"| {tc} | {lang} | {p['transformation']} | {_fmt(modes['raw']['score'])} | "
                 f"{_fmt(modes['cleaned']['score'])} | {_fmt(p['score'])} | {_fmt(p['drop'])} | "
                 f"{'yes' if p['texts_identical_after_prep'] else 'no'} | {p['note'] or ''} |")
    for r in na:
        L.append(f"| {r['id']} | {r['language']} | {r['transformation']} | N/A | N/A | N/A | N/A | N/A | "
                 f"{r['note']} |")
    (RESULTS_DIR / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
