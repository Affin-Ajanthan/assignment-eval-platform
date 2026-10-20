"""
Measure how often the report AI-text signal flags REAL student reports:
how many come out low / medium / high, overall and per assignment.

Most student reports are human-written, so a high flagged share means the
thresholds would show instructors many false flags. Run this before
instructors rely on the flag, and again after changing AI_TEXT_MEDIUM /
AI_TEXT_HIGH (or try new values with --medium / --high without re-scoring).

Reports come from the portal database (every submission with a report;
narrow it with --subject-id / --assignment) or from folders of report files
(--folder, repeatable; .pdf, .docx, .md, .txt, searched recursively).

Scores are saved to a CSV after every report, so an interrupted run resumes
and a re-run with other thresholds needs no model time. The CSV holds file
paths and assignment names only -- no student names.

Examples:
    python scripts/measure_ai_flags.py
    python scripts/measure_ai_flags.py --assignment "Assignment 1" --subject-id 2
    python scripts/measure_ai_flags.py --folder sample_submissions --medium 1.2 --high 2.4
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate_ai_text import Row, append_row, collect_files, load_rows, score_file  # noqa: E402

from app.evaluator.ai_text_detection import get_ai_text_detector, model_name, thresholds  # noqa: E402

SIGNALS = ("low", "medium", "high")


def db_reports(subject_id: int | None = None, assignment: str | None = None) -> list[tuple[Path, str]]:
    """(report file, "subject <id> / <assignment>") for every submission
    with a report file that still exists."""
    from app.db import BASE_DIR, SessionLocal
    from app.models import Submission

    with SessionLocal() as db:
        query = db.query(Submission).filter(Submission.report_path.isnot(None))
        if subject_id is not None:
            query = query.filter(Submission.subject_id == subject_id)
        if assignment is not None:
            query = query.filter(Submission.assignment_name == assignment)
        found = []
        for s in query.order_by(Submission.id).all():
            path = BASE_DIR / s.report_path
            if path.is_file():
                found.append((path, f"subject {s.subject_id} / {s.assignment_name}"))
        return found


def folder_reports(folders: list[Path]) -> list[tuple[Path, str]]:
    return [(path, folder.name) for folder in folders for path in collect_files(folder)]


def signal(curvature: float, medium: float, high: float) -> str:
    # Same banding as ai_text_detection.to_score.
    return "high" if curvature >= high else "medium" if curvature >= medium else "low"


def summarize(rows: list[Row], medium: float, high: float) -> dict:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in (*SIGNALS, "skipped")})
    flagged = []
    for r in rows:
        if r.status != "ok" or r.curvature is None:
            groups[r.label]["skipped"] += 1
            continue
        level = signal(r.curvature, medium, high)
        groups[r.label][level] += 1
        if level != "low":
            flagged.append((r.curvature, level, r.label, r.path))
    total = {s: sum(g[s] for g in groups.values()) for s in (*SIGNALS, "skipped")}
    return {"medium": medium, "high": high, "total": total, "groups": dict(groups),
            "flagged": sorted(flagged, reverse=True)}


def _line(name: str, counts: dict[str, int]) -> str:
    scored = sum(counts[s] for s in SIGNALS)
    if not scored:
        return f"  {name}: no scorable reports ({counts['skipped']} skipped)"
    parts = "   ".join(f"{s} {counts[s]:>3} ({counts[s] / scored * 100:4.1f}%)" for s in SIGNALS)
    return f"  {name}: {scored} scored   {parts}   skipped {counts['skipped']}"


def print_summary(summary: dict, top: int) -> None:
    print(f"\nThresholds: medium >= {summary['medium']:g}, high >= {summary['high']:g}")
    print(_line("ALL", summary["total"]))
    if len(summary["groups"]) > 1:
        for name in sorted(summary["groups"]):
            print(_line(name, summary["groups"][name]))
    scored = sum(summary["total"][s] for s in SIGNALS)
    if scored:
        share = (summary["total"]["medium"] + summary["total"]["high"]) / scored * 100
        print(f"\n{share:.1f}% of real reports would show a medium or high AI-text signal. If most of these "
              "students wrote their own reports, that is roughly the false-flag rate instructors would see.")
    if summary["flagged"] and top:
        print(f"\nHighest-scoring flagged reports (top {min(top, len(summary['flagged']))}) -- check them by hand:")
        for curvature, level, group, path in summary["flagged"][:top]:
            print(f"  {curvature:6.2f}  {level:<6}  {group}  {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", type=Path, action="append", default=[],
                        help="folder of report files (repeatable); without it, reports come from the database")
    parser.add_argument("--subject-id", type=int, default=None, help="database mode: only this subject")
    parser.add_argument("--assignment", default=None, help="database mode: only this assignment name")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "ai_flag_rate.csv",
                        help="CSV of per-report scores (resumed if it exists)")
    parser.add_argument("--medium", type=float, default=None, help="try this medium threshold (default: current)")
    parser.add_argument("--high", type=float, default=None, help="try this high threshold (default: current)")
    parser.add_argument("--limit", type=int, default=None, help="score at most this many new reports")
    parser.add_argument("--top", type=int, default=10, help="list this many flagged reports (default 10)")
    args = parser.parse_args(argv)

    for folder in args.folder:
        if not folder.is_dir():
            parser.error(f"not a folder: {folder}")
    reports = folder_reports(args.folder) if args.folder else db_reports(args.subject_id, args.assignment)
    if not reports:
        print("No report files found.", file=sys.stderr)
        return 1

    current_model = model_name()
    wanted = {(str(path), group) for path, group in reports}
    rows = [r for r in load_rows(args.out) if r.model == current_model and (r.path, r.label) in wanted]
    done = {(r.path, r.label) for r in rows}
    todo = [(path, group) for path, group in reports if (str(path), group) not in done]
    if args.limit is not None:
        todo = todo[:args.limit]

    if todo:
        detector = get_ai_text_detector()
        if not detector.load():
            print(f"AI-text detector is not available ({detector.status}: {detector.error}). "
                  "The flag rate must be measured with the Fast-DetectGPT model.", file=sys.stderr)
            return 1
    print(f"{len(reports)} report(s) found, {len(todo)} to score ({len(rows)} already in {args.out})")
    for i, (path, group) in enumerate(todo, 1):
        row = score_file(path, group, get_ai_text_detector(), current_model)
        append_row(args.out, row)
        rows.append(row)
        value = "-" if row.curvature is None else f"{row.curvature:.2f}"
        print(f"  [{i}/{len(todo)}] {path.name}: {row.status} {value} ({row.seconds:.0f}s)")

    medium, high = thresholds()
    medium = args.medium if args.medium is not None else medium
    high = args.high if args.high is not None else high
    print_summary(summarize(rows, medium, high), args.top)
    print(f"\nPer-report scores: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
