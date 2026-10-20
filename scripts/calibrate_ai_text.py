"""
Calibrate the report AI-text thresholds (AI_TEXT_MEDIUM / AI_TEXT_HIGH)
against a labelled set of human-written and AI-written reports.

Input is two folders of reports (.pdf, .docx, .md, .txt; searched
recursively): one written by students without AI help, one written (or
rewritten) by an AI assistant -- ideally AI rewrites of the same reports,
so topic and length don't separate the two groups.

Every report is scored with the same Fast-DetectGPT detector the pipeline
uses (app/evaluator/ai_text_detection.py) and written to a CSV row as soon
as it is scored, so an interrupted run resumes where it stopped. Rows are
keyed by file and model: changing AI_TEXT_DETECTOR_MODEL scores again.

Reports:
  - how well the scores separate the groups (AUC: 0.5 = chance, 1.0 = perfect)
  - false-flag rate (human reports flagged) and detection rate (AI reports
    flagged) at the current thresholds
  - suggested thresholds: the lowest values that keep the false-flag rate
    on human reports at or under --high-fpr (default 5%) for "high" and
    --medium-fpr (default 20%) for "medium"

The suggestion is only as good as the labelled set: use at least 20
reports per group, from the same kind of assignment as real submissions.

Example:
    python scripts/calibrate_ai_text.py --human data/ai_calibration/human \\
        --ai data/ai_calibration/ai --out eval/results/ai_text_calibration.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluator.ai_text_detection import get_ai_text_detector, model_name, thresholds  # noqa: E402
from app.evaluator.report_analysis import extract_report  # noqa: E402

REPORT_SUFFIXES = {".pdf", ".docx", ".md", ".txt"}
FIELDS = ["path", "label", "status", "curvature", "chunks_scored", "total_tokens", "model", "seconds"]
MIN_PER_GROUP = 20


@dataclass
class Row:
    path: str
    label: str  # "human" | "ai"
    status: str  # "ok" | "insufficient_text" | "error"
    curvature: float | None
    chunks_scored: int
    total_tokens: int
    model: str
    seconds: float


def collect_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in REPORT_SUFFIXES)


def load_rows(csv_path: Path) -> list[Row]:
    if not csv_path.is_file():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [
            Row(path=r["path"], label=r["label"], status=r["status"],
                curvature=float(r["curvature"]) if r["curvature"] else None,
                chunks_scored=int(r["chunks_scored"] or 0), total_tokens=int(r["total_tokens"] or 0),
                model=r["model"], seconds=float(r["seconds"] or 0))
            for r in csv.DictReader(handle)
        ]


def append_row(csv_path: Path, row: Row) -> None:
    new_file = not csv_path.is_file()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({
            "path": row.path, "label": row.label, "status": row.status,
            "curvature": "" if row.curvature is None else f"{row.curvature:.4f}",
            "chunks_scored": row.chunks_scored, "total_tokens": row.total_tokens,
            "model": row.model, "seconds": f"{row.seconds:.1f}",
        })


def score_file(path: Path, label: str, detector, model: str) -> Row:
    start = time.perf_counter()
    try:
        text = extract_report(path).text
        result = detector.detect(text)
    except Exception as exc:  # unreadable file: record it and carry on
        print(f"  ! {path.name}: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        result = None
    seconds = time.perf_counter() - start
    if result is None:
        return Row(str(path), label, "error", None, 0, 0, model, seconds)
    return Row(str(path), label, result.status, result.curvature, result.chunks_scored,
               result.total_tokens, model, seconds)


# ---- metrics ----------------------------------------------------------------

def flag_rate(scores: list[float], threshold: float) -> float:
    """Share of scores flagged at this threshold (the pipeline flags c >= t)."""
    return sum(1 for s in scores if s >= threshold) / len(scores) if scores else 0.0


def auc(human: list[float], ai: list[float]) -> float | None:
    """Probability that a random AI report scores above a random human one
    (ties count half)."""
    if not human or not ai:
        return None
    wins = sum(1.0 if a > h else 0.5 if a == h else 0.0 for a in ai for h in human)
    return wins / (len(ai) * len(human))


def suggest_threshold(human: list[float], max_fpr: float) -> float | None:
    """Lowest threshold (on a 0.01 grid) whose false-flag rate on the human
    reports is at most ``max_fpr``. The flag rate only drops just above a
    human score, so those points are the only candidates needed."""
    if not human:
        return None
    candidates = sorted({round(math.floor(s * 100) / 100 + 0.01, 2) for s in human})
    for t in candidates:
        if flag_rate(human, t) <= max_fpr:
            return t
    return candidates[-1]  # unreachable: the last one is above every human score


def summarize(rows: list[Row], high_fpr: float, medium_fpr: float) -> dict:
    human = [r.curvature for r in rows if r.label == "human" and r.status == "ok" and r.curvature is not None]
    ai = [r.curvature for r in rows if r.label == "ai" and r.status == "ok" and r.curvature is not None]
    medium, high = thresholds()

    def at(t: float | None) -> dict | None:
        if t is None:
            return None
        return {"threshold": t, "false_flag_rate": flag_rate(human, t), "detection_rate": flag_rate(ai, t)}

    suggested_high = suggest_threshold(human, high_fpr)
    suggested_medium = suggest_threshold(human, medium_fpr)
    if suggested_high is not None and suggested_medium is not None:
        suggested_medium = min(suggested_medium, suggested_high)
    return {
        "human": len(human), "ai": len(ai),
        "skipped": sum(1 for r in rows if r.status != "ok"),
        "auc": auc(human, ai),
        "current": {"medium": at(medium), "high": at(high)},
        "suggested": {"medium": at(suggested_medium), "high": at(suggested_high)},
    }


def print_summary(summary: dict) -> None:
    def pct(x: float) -> str:
        return f"{x * 100:5.1f}%"

    print(f"\nScored reports: {summary['human']} human, {summary['ai']} AI "
          f"({summary['skipped']} skipped: too short or unreadable)")
    if summary["human"] < MIN_PER_GROUP or summary["ai"] < MIN_PER_GROUP:
        print(f"WARNING: fewer than {MIN_PER_GROUP} reports in a group -- treat the numbers as rough.")
    if summary["auc"] is not None:
        print(f"AUC: {summary['auc']:.3f}  (0.5 = no better than chance, 1.0 = perfect separation)")
    for name in ("current", "suggested"):
        print(f"\n{name.capitalize()} thresholds:")
        for level in ("medium", "high"):
            m = summary[name][level]
            if m is None:
                print(f"  {level:<6}  (not enough human reports)")
                continue
            print(f"  {level:<6} >= {m['threshold']:5.2f}   human flagged {pct(m['false_flag_rate'])}   "
                  f"AI flagged {pct(m['detection_rate'])}")
    s = summary["suggested"]
    if s["medium"] and s["high"]:
        print(f"\nTo use the suggestion:  AI_TEXT_MEDIUM={s['medium']['threshold']:g}  "
              f"AI_TEXT_HIGH={s['high']['threshold']:g}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--human", type=Path, required=True, help="folder of human-written reports")
    parser.add_argument("--ai", type=Path, required=True, help="folder of AI-written reports")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "ai_text_calibration.csv",
                        help="CSV of per-report scores (resumed if it exists)")
    parser.add_argument("--high-fpr", type=float, default=0.05,
                        help="max share of human reports flagged 'high' (default 0.05)")
    parser.add_argument("--medium-fpr", type=float, default=0.20,
                        help="max share of human reports flagged 'medium' or above (default 0.20)")
    parser.add_argument("--limit", type=int, default=None, help="score at most this many new reports per group")
    args = parser.parse_args(argv)

    for folder in (args.human, args.ai):
        if not folder.is_dir():
            parser.error(f"not a folder: {folder}")

    detector = get_ai_text_detector()
    if not detector.load():
        print(f"AI-text detector is not available ({detector.status}: {detector.error}). "
              "Calibration needs the Fast-DetectGPT model, not the style heuristic.", file=sys.stderr)
        return 1

    current_model = model_name()
    rows = [r for r in load_rows(args.out) if r.model == current_model]
    done = {(r.path, r.label) for r in rows}
    for label, folder in (("human", args.human), ("ai", args.ai)):
        todo = [p for p in collect_files(folder) if (str(p), label) not in done]
        if args.limit is not None:
            todo = todo[:args.limit]
        print(f"{label}: {len(todo)} report(s) to score in {folder}")
        for i, path in enumerate(todo, 1):
            row = score_file(path, label, detector, current_model)
            append_row(args.out, row)
            rows.append(row)
            value = "-" if row.curvature is None else f"{row.curvature:.2f}"
            print(f"  [{i}/{len(todo)}] {path.name}: {row.status} {value} ({row.seconds:.0f}s)")

    print_summary(summarize(rows, args.high_fpr, args.medium_fpr))
    print(f"\nPer-report scores: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
