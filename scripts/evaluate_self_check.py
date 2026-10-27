"""
Measure the student self-check similarity bands against labelled test sets.

Each set in scripts/self_check_eval_sets.json lists every student's code (a
folder or a .zip) and, where known, report, plus the groups of students who
copied (an original and its copies). The real production code is run on each
set -- app.similarity_runs.code_similarity_for_dirs, self_checks.code_result /
report_result and the band rules -- so the numbers are what students would see.

Reports, per set and overall:
  - students: a student is "positive" when they are in a copy group (an
    original author matches their copiers too). Counted twice: flagged as
    High only, and flagged as Moderate-or-High.
  - pairs: a pair is a known copy when both students are in the same group.
    Precision / recall for the self-check bands, and for the instructor's own
    flag for comparison.
  - every missed copy and every false alarm, with its scores.
Known-hard cases (partial or restructured copies) are listed separately.

Nothing is stored and the app's database is never touched.

Examples:
    python scripts/evaluate_self_check.py --data-root "C:/Users/me/OneDrive/Desktop/checksim/submisstions"
    python scripts/evaluate_self_check.py --data-root ... --set PHP --no-semantic
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("self_check_eval_sets.json")
FLAGGED = ("moderate", "high")


# ---- metrics (pure; tested in tests/test_evaluate_self_check.py) ----------------

def positive_pairs(groups: list[list[str]] | None) -> set[frozenset]:
    """Known-copy pairs: every pair inside each group (groups are not merged)."""
    return {frozenset(p) for g in (groups or []) for p in combinations(g, 2)}


def positive_students(groups: list[list[str]] | None) -> set[str]:
    return {s for g in (groups or []) for s in g}


def confusion(predicted: set, actual: set, universe: set) -> dict:
    tp, fp, fn = len(predicted & actual), len(predicted - actual), len(actual - predicted)
    tn = len(universe) - tp - fp - fn
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


def add(total: dict, part: dict) -> None:
    for k in ("tp", "fp", "fn", "tn"):
        total[k] = total.get(k, 0) + part[k]
    tp, fp, fn = total["tp"], total["fp"], total["fn"]
    total["precision"] = round(tp / (tp + fp), 3) if tp + fp else None
    total["recall"] = round(tp / (tp + fn), 3) if tp + fn else None


def pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


# ---- running one set --------------------------------------------------------------

def _prepare(path: Path, work: Path, key: str) -> Path:
    """A student's code as a folder: zips are extracted to a work folder."""
    if path.is_dir():
        return path
    if path.suffix.lower() == ".zip":
        target = work / key
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(target)
        return target
    raise SystemExit(f"Not a folder or .zip: {path}")


def _scores(p) -> dict:
    return {"jaccard": p.jaccard, "containment": p.containment,
            "semantic": None if p.semantic_similarity is None else round(p.semantic_similarity, 3)}


def evaluate_code(spec: dict, data_root: Path, work: Path) -> dict:
    from app import self_checks
    from app.common import ANALYZED_EXTENSIONS
    from app.similarity_runs import code_similarity_for_dirs

    dirs = {}
    for sid, files in spec["students"].items():
        src = data_root / files["code"]
        if not src.exists():
            raise SystemExit(f"[{spec['name']}] student {sid}: not found: {src}")
        dirs[sid] = _prepare(src, work, sid)
    file_lists = {sid: sorted(p.relative_to(d).as_posix() for p in d.rglob("*")
                              if p.is_file() and p.suffix.lower() in ANALYZED_EXTENSIONS) for sid, d in dirs.items()}

    # The self-check as students get it (code common to the class removed), and
    # the instructor's own check (unchanged) for comparison.
    run = code_similarity_for_dirs(dirs, remove_common=True)
    instructor = {frozenset((p.submission_a, p.submission_b)): p.flagged for p in code_similarity_for_dirs(dirs).pairs}
    lines = self_checks.code_moderate_lines(run.pairs)
    hashes = {sid: fp.hashes for sid, fp in run.fingerprints.items()}
    bands = {sid: self_checks.code_result(sid, run.pairs, run.files_by_submission.get(sid, []), hashes,
                                          run.batch.status)["band"] for sid in dirs}

    truth_pairs = positive_pairs(spec["code_groups"])
    hard = positive_pairs(spec.get("known_hard", {}).get("code"))
    pair_rows = []
    for p in run.pairs:
        key = frozenset((p.submission_a, p.submission_b))
        pair_rows.append({"pair": sorted(key, key=_num), "copy": key in truth_pairs, "known_hard": key in hard,
                          "band": self_checks.code_pair_band(p, lines), "instructor_flag": instructor[key],
                          **_scores(p)})
    return _summarise(spec, "code", bands, truth_pairs, pair_rows,
                      {"semantic": run.batch.status, "class_baseline": lines, "files": file_lists,
                       "common_fingerprints_removed": run.common_removed})


def evaluate_report(spec: dict, data_root: Path, semantic: bool) -> dict | None:
    if not spec.get("report_groups"):
        return None
    from app import self_checks
    from app.evaluator.semantic_consistency import get_consistency_service
    from app.similarity import report_similarity as report_sim
    from app.similarity_runs import report_text_for_path

    texts, skipped = {}, {}
    for sid, files in spec["students"].items():
        text, reason = report_text_for_path(data_root / files["report"])
        if text is None:
            skipped[sid] = reason
        else:
            texts[sid] = text
    comparison = report_sim.compare_reports(texts, get_consistency_service() if semantic else None)
    lines = self_checks.report_moderate_lines(comparison.pairs)
    bands = {sid: self_checks.report_result(sid, comparison.pairs, comparison.semantic_status)["band"]
             for sid in texts}

    truth_pairs = positive_pairs(spec["report_groups"])
    hard = positive_pairs(spec.get("known_hard", {}).get("report"))
    pair_rows = []
    for p in comparison.pairs:
        key = frozenset((p.submission_a, p.submission_b))
        coverage = max(p.coverage_a, p.coverage_b)
        pair_rows.append({"pair": sorted(key, key=_num), "copy": key in truth_pairs, "known_hard": key in hard,
                          "band": self_checks.report_pair_band(p, coverage, lines),
                          "instructor_flag": p.flag_level is not None, **_scores(p), "coverage": coverage})
    return _summarise(spec, "report", bands, truth_pairs, pair_rows,
                      {"semantic": comparison.semantic_status, "class_baseline": lines, "skipped": skipped})


def _num(s: str):
    return (0, int(s)) if s.isdigit() else (1, s)


def _summarise(spec, part, bands, truth_pairs, pair_rows, extra) -> dict:
    groups = spec[f"{part}_groups"]
    truth_students = positive_students(groups) & set(bands)
    universe = set(bands)
    all_pairs = {frozenset(r["pair"]) for r in pair_rows}
    flagged = lambda levels: {frozenset(r["pair"]) for r in pair_rows if r["band"] in levels}  # noqa: E731
    return {
        "part": part, "bands": dict(sorted(bands.items(), key=lambda kv: _num(kv[0]))),
        "students_high": confusion({s for s, b in bands.items() if b == "high"}, truth_students, universe),
        "students_flagged": confusion({s for s, b in bands.items() if b in FLAGGED}, truth_students, universe),
        "pairs_high": confusion(flagged(("high",)), truth_pairs & all_pairs, all_pairs),
        "pairs_flagged": confusion(flagged(FLAGGED), truth_pairs & all_pairs, all_pairs),
        "pairs_instructor": confusion({frozenset(r["pair"]) for r in pair_rows if r["instructor_flag"]},
                                      truth_pairs & all_pairs, all_pairs),
        "missed": [r for r in pair_rows if r["copy"] and r["band"] not in FLAGGED],
        "false_alarms": [r for r in pair_rows if not r["copy"] and r["band"] in FLAGGED],
        "known_hard": [r for r in pair_rows if r["known_hard"]],
        **extra,
    }


# ---- output -------------------------------------------------------------------

def _row_text(r: dict) -> str:
    sem = "—" if r["semantic"] is None else f"{r['semantic']:.2f}"
    cov = f", coverage {r['coverage']:.0%}" if "coverage" in r else ""
    return (f"{r['pair'][0]}–{r['pair'][1]}: band {r['band']}, instructor flag {'yes' if r['instructor_flag'] else 'no'} "
            f"(Jaccard {r['jaccard']:.2f}, containment {r['containment']:.2f}, semantic {sem}{cov})")


def markdown(results: list[dict], totals: dict, semantic: bool, seconds: float) -> str:
    out = [f"# Self-check similarity evaluation — {datetime.now():%Y-%m-%d %H:%M}", "",
           f"Mode: {'semantic checks on (UniXcoder, MiniLM)' if semantic else 'token checks only (--no-semantic)'}"
           f" · {seconds:.0f} s", "",
           "Students: positive = in a copy group (originals included). Pairs: positive = both in the same group.", ""]
    for part in ("code", "report"):
        t = totals.get(part)
        if not t:
            continue
        out += [f"## Overall — {part}", "",
                "| Measure | TP | FP | FN | TN | Precision | Recall |", "|---|---|---|---|---|---|---|"]
        for key, label in (("students_high", "Students flagged High"),
                           ("students_flagged", "Students flagged Moderate or High"),
                           ("pairs_high", "Pairs High"), ("pairs_flagged", "Pairs Moderate or High"),
                           ("pairs_instructor", "Pairs — instructor's own flag")):
            c = t[key]
            out.append(f"| {label} | {c['tp']} | {c['fp']} | {c['fn']} | {c['tn']} | "
                       f"{pct(c['precision'])} | {pct(c['recall'])} |")
        out.append("")
    for res in results:
        out += [f"## {res['name']}", "", res.get("notes", ""), ""]
        for part in ("code", "report"):
            r = res.get(part)
            if not r:
                continue
            s, p = r["students_flagged"], r["pairs_flagged"]
            out += [f"**{part.capitalize()}** (semantic: {r['semantic']}; class baseline {r['class_baseline']})", "",
                    "Bands: " + ", ".join(f"{k}={v}" for k, v in r["bands"].items()), "",
                    f"- Students (Moderate/High): precision {pct(s['precision'])}, recall {pct(s['recall'])} "
                    f"(TP {s['tp']}, FP {s['fp']}, FN {s['fn']})",
                    f"- Pairs (Moderate/High): precision {pct(p['precision'])}, recall {pct(p['recall'])}; "
                    f"instructor flag recall {pct(r['pairs_instructor']['recall'])}"]
            for title, rows in (("Missed copies", r["missed"]), ("False alarms", r["false_alarms"]),
                                ("Known-hard cases", r["known_hard"])):
                if rows:
                    out.append(f"- {title}:")
                    out += [f"  - {_row_text(x)}" for x in rows]
            out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, required=True, help="the checksim/submisstions folder")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--set", action="append", default=[], help="only sets whose name contains this (repeatable)")
    parser.add_argument("--no-semantic", action="store_true", help="token checks only (fast; not the official numbers)")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "self_check_eval",
                        help="folder for the .md and .json results (eval/ is git-ignored)")
    args = parser.parse_args()

    # Never touch the real portal.db: the app's modules point at a throwaway folder.
    work = Path(tempfile.mkdtemp(prefix="selfcheck_eval_"))
    os.environ["PORTAL_DATA_DIR"] = str(work)
    os.environ["PORTAL_DB_PATH"] = str(work / "eval.db")
    if args.no_semantic:
        os.environ["SEMANTIC_SIMILARITY"] = "0"
        os.environ["CROSS_MODAL_SEMANTIC"] = "0"
    sys.path.insert(0, str(ROOT))

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    specs = [s for s in manifest["sets"] if not args.set or any(f.lower() in s["name"].lower() for f in args.set)]
    if not specs:
        raise SystemExit("No set matches --set")

    started = time.monotonic()
    results, totals = [], {}
    for spec in specs:
        print(f"== {spec['name']} ({len(spec['students'])} students)", flush=True)
        res = {"name": spec["name"], "notes": spec.get("notes", ""),
               "code": evaluate_code(spec, args.data_root, work / "code" / spec["name"].replace(" ", "_"))}
        report = evaluate_report(spec, args.data_root, not args.no_semantic)
        if report:
            res["report"] = report
        for part in ("code", "report"):
            r = res.get(part)
            if not r:
                continue
            for key in ("students_high", "students_flagged", "pairs_high", "pairs_flagged", "pairs_instructor"):
                add(totals.setdefault(part, {}).setdefault(key, {}), r[key])
            f = r["students_flagged"]
            print(f"   {part:6s} students flagged: precision {pct(f['precision'])}, recall {pct(f['recall'])}"
                  f" | missed copies {len(r['missed'])}, false alarms {len(r['false_alarms'])}", flush=True)
        for sid, files in res["code"]["files"].items():
            print(f"     {sid}: {len(files)} code file(s) {files[:4]}{' ...' if len(files) > 4 else ''}")
        results.append(res)

    seconds = time.monotonic() - started
    shutil.rmtree(work, ignore_errors=True)  # the extracted zips
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path, json_path = args.out / f"self_check_eval_{stamp}.md", args.out / f"self_check_eval_{stamp}.json"
    md_path.write_text(markdown(results, totals, not args.no_semantic, seconds), encoding="utf-8")
    json_path.write_text(json.dumps({"semantic": not args.no_semantic, "totals": totals, "sets": results},
                                    indent=2, default=list), encoding="utf-8")
    print("\nOverall (Moderate or High):")
    for part, t in totals.items():
        s, p = t["students_flagged"], t["pairs_flagged"]
        print(f"  {part:6s} students: precision {pct(s['precision'])}, recall {pct(s['recall'])} | "
              f"pairs: precision {pct(p['precision'])}, recall {pct(p['recall'])} | "
              f"instructor flag pair recall {pct(t['pairs_instructor']['recall'])}")
    print(f"\nResults: {md_path}\n         {json_path}")


if __name__ == "__main__":
    main()
