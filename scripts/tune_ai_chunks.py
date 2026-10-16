"""
Time report AI-text detection and pick AI_TEXT_MAX_CHUNKS: how much faster
fewer chunks would be, and whether the result would change.

The detector scores at most AI_TEXT_MAX_CHUNKS chunks of 256 tokens per
report (default 8), spread evenly across the report. On CPU each chunk
takes seconds, so this is most of the AI-detection time in a batch.

Each report's chunks are scored ONCE -- every chunk any of the --chunks
settings would pick -- and each setting is then simulated from those
scores with the pipeline's own chunk selection (select_chunks). So one run
gives, for every setting:
  - estimated seconds per report, and for a batch of --batch-size reports
  - how far the report score moves from the reference setting (default 8,
    today's behaviour), and how many reports change signal level
    (low / medium / high)

Suggests the smallest setting that changes no report's signal level and
moves the score by at most --tolerance on average.

Reports come from the portal database or --folder, as in
measure_ai_flags.py. Scores are saved after every report (CSV, resumed).

Examples:
    python scripts/tune_ai_chunks.py --limit 10
    python scripts/tune_ai_chunks.py --folder path/to/reports --chunks 2,3,4,6,8
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_ai_flags import db_reports, folder_reports, signal  # noqa: E402

from app.evaluator.ai_text_detection import (  # noqa: E402
    CHUNK_TOKENS,
    MIN_TOKENS,
    model_name,
    select_chunks,
    thresholds,
)
from app.evaluator.report_analysis import extract_report  # noqa: E402

FIELDS = ["path", "group", "model", "status", "total_chunks", "scores", "chunks_scored", "seconds"]


@dataclass
class Report:
    path: str
    group: str
    model: str
    status: str  # "ok" | "insufficient_text" | "error"
    total_chunks: int = 0
    scores: dict[int, float] = field(default_factory=dict)  # chunk index -> curvature
    chunks_scored: int = 0  # model calls made for this report (for timing)
    seconds: float = 0.0  # time spent in those calls


def picked(total_chunks: int, max_chunks: int) -> list[int]:
    """Indices of the chunks the detector scores at this setting -- the
    same even spread as select_chunks, applied to chunk positions."""
    return [c[0] for c in select_chunks(list(range(total_chunks)), 1, max_chunks)]


def report_score(report: Report, max_chunks: int) -> float:
    idx = picked(report.total_chunks, max_chunks)
    return sum(report.scores[i] for i in idx) / len(idx)


def load(csv_path: Path) -> dict[tuple[str, str], Report]:
    if not csv_path.is_file():
        return {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return {
            (r["path"], r["model"]): Report(
                r["path"], r["group"], r["model"], r["status"], int(r["total_chunks"] or 0),
                {int(k): v for k, v in json.loads(r["scores"] or "{}").items()},
                int(r["chunks_scored"] or 0), float(r["seconds"] or 0))
            for r in csv.DictReader(handle)
        }


def save(csv_path: Path, reports: dict[tuple[str, str], Report]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for r in reports.values():
            writer.writerow({"path": r.path, "group": r.group, "model": r.model, "status": r.status,
                             "total_chunks": r.total_chunks, "scores": json.dumps(r.scores),
                             "chunks_scored": r.chunks_scored, "seconds": f"{r.seconds:.2f}"})


def score_report(path: Path, group: str, model: str, scorer, settings: list[int],
                 previous: Report | None) -> Report:
    """Score the chunks the settings need that aren't stored yet."""
    report = previous or Report(str(path), group, model, "ok")
    if report.status != "ok":
        return report
    try:
        text = " ".join(extract_report(path).text.split())
        chunks = scorer.all_chunks(text, CHUNK_TOKENS)
        if sum(len(c) for c in chunks) < MIN_TOKENS:
            report.status = "insufficient_text"
            return report
        report.total_chunks = len(chunks)
        needed = sorted({i for s in settings for i in picked(len(chunks), s)} - set(report.scores))
        start = time.perf_counter()
        scores = scorer.score_chunks([chunks[i] for i in needed])
        report.seconds += time.perf_counter() - start
        report.chunks_scored += len(needed)
        report.scores.update(zip(needed, scores))
    except Exception as exc:  # unreadable report: record it and carry on
        print(f"  ! {path.name}: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        report.status = "error"
    return report


def summarize(reports: list[Report], settings: list[int], reference: int, medium: float, high: float,
              batch_size: int, tolerance: float) -> dict:
    ok = [r for r in reports if r.status == "ok" and r.total_chunks]
    calls = sum(r.chunks_scored for r in ok)
    per_chunk = sum(r.seconds for r in ok) / calls if calls else None
    rows = []
    for s in settings:
        chunks = [len(picked(r.total_chunks, s)) for r in ok]
        deltas = [abs(report_score(r, s) - report_score(r, reference)) for r in ok]
        changed = sum(1 for r in ok if signal(report_score(r, s), medium, high)
                      != signal(report_score(r, reference), medium, high))
        avg_chunks = sum(chunks) / len(chunks) if chunks else 0
        rows.append({
            "max_chunks": s, "avg_chunks": avg_chunks,
            "seconds_per_report": avg_chunks * per_chunk if per_chunk is not None else None,
            "mean_delta": sum(deltas) / len(deltas) if deltas else 0.0,
            "max_delta": max(deltas, default=0.0), "signal_changes": changed,
        })
    suggestion = next((row["max_chunks"] for row in rows
                       if row["signal_changes"] == 0 and row["mean_delta"] <= tolerance), reference)
    return {"reports": len(ok), "skipped": len(reports) - len(ok), "seconds_per_chunk": per_chunk,
            "reference": reference, "batch_size": batch_size, "rows": rows, "suggestion": suggestion}


def print_summary(s: dict) -> None:
    print(f"\n{s['reports']} report(s) scored ({s['skipped']} skipped: too short or unreadable)")
    if s["seconds_per_chunk"] is not None:
        print(f"Model time: {s['seconds_per_chunk']:.2f} s per {CHUNK_TOKENS}-token chunk on this machine")
    print(f"\n{'max chunks':>10}  {'avg used':>8}  {'s/report':>8}  {'batch of ' + str(s['batch_size']):>12}  "
          f"{'mean diff':>9}  {'max diff':>8}  level changes (vs {s['reference']})")
    for row in s["rows"]:
        spr = row["seconds_per_report"]
        timing = (f"{spr:8.1f}  {spr * s['batch_size'] / 60:9.1f} min" if spr is not None
                  else f"{'-':>8}  {'-':>13}")
        print(f"{row['max_chunks']:>10}  {row['avg_chunks']:8.1f}  {timing}  {row['mean_delta']:9.2f}  "
              f"{row['max_delta']:8.2f}  {row['signal_changes']}/{s['reports']}")
    print(f"\nSuggested: AI_TEXT_MAX_CHUNKS={s['suggestion']}")
    if s["reports"] < 20:
        print("WARNING: fewer than 20 reports -- run on more before changing the default.")


def _settings(text: str) -> list[int]:
    try:
        values = sorted({int(v) for v in text.split(",") if v.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError("use comma-separated whole numbers, e.g. 2,3,4,6,8")
    if not values or values[0] < 1:
        raise argparse.ArgumentTypeError("chunk counts must be 1 or more")
    return values


def main(argv: list[str] | None = None, scorer_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", type=Path, action="append", default=[],
                        help="folder of report files (repeatable); without it, reports come from the database")
    parser.add_argument("--subject-id", type=int, default=None, help="database mode: only this subject")
    parser.add_argument("--assignment", default=None, help="database mode: only this assignment name")
    parser.add_argument("--chunks", type=_settings, default=[2, 3, 4, 6, 8],
                        help="settings to compare (default 2,3,4,6,8)")
    parser.add_argument("--reference", type=int, default=8,
                        help="setting the others are compared with (default 8, today's default)")
    parser.add_argument("--batch-size", type=int, default=30, help="reports per batch for the estimate")
    parser.add_argument("--tolerance", type=float, default=0.15,
                        help="max mean score change accepted for the suggestion (default 0.15)")
    parser.add_argument("--medium", type=float, default=None, help="medium threshold (default: current)")
    parser.add_argument("--high", type=float, default=None, help="high threshold (default: current)")
    parser.add_argument("--limit", type=int, default=None, help="score at most this many new reports")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "ai_chunk_tuning.csv",
                        help="CSV of per-chunk scores (resumed if it exists)")
    args = parser.parse_args(argv)

    settings = sorted(set(args.chunks) | {args.reference})
    for folder in args.folder:
        if not folder.is_dir():
            parser.error(f"not a folder: {folder}")
    sources = folder_reports(args.folder) if args.folder else db_reports(args.subject_id, args.assignment)
    if not sources:
        print("No report files found.", file=sys.stderr)
        return 1

    model = model_name()
    stored = load(args.out)
    todo = [(p, g) for p, g in sources
            if (str(p), model) not in stored
            or (stored[(str(p), model)].status == "ok"
                and any(i not in stored[(str(p), model)].scores
                        for s in settings for i in picked(stored[(str(p), model)].total_chunks, s)))]
    if args.limit is not None:
        todo = todo[:args.limit]

    if todo:
        try:
            if scorer_factory is None:
                from app.evaluator.ai_text_detection import FastDetectGPTScorer
                scorer_factory = FastDetectGPTScorer
            scorer = scorer_factory()
        except Exception as exc:
            print(f"Could not load the AI-text model {model} ({exc.__class__.__name__}: {exc}).", file=sys.stderr)
            return 1
    print(f"{len(sources)} report(s) found, {len(todo)} to score")
    for i, (path, group) in enumerate(todo, 1):
        report = score_report(path, group, model, scorer, settings, stored.get((str(path), model)))
        stored[(str(path), model)] = report
        save(args.out, stored)
        print(f"  [{i}/{len(todo)}] {path.name}: {report.status}, {report.total_chunks} chunk(s), "
              f"{report.seconds:.0f}s")

    wanted = {str(p) for p, _ in sources}
    reports = [r for (path, m), r in stored.items() if m == model and path in wanted]
    medium, high = thresholds()
    medium = args.medium if args.medium is not None else medium
    high = args.high if args.high is not None else high
    print_summary(summarize(reports, settings, args.reference, medium, high, args.batch_size, args.tolerance))
    print(f"\nPer-chunk scores: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
