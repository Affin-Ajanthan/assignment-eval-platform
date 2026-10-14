"""
Measure the rubric grader against instructor marks.

Input is a CSV with one row per criterion of each graded submission:

    submission_id,code_dir,report_path,criterion,description,max_points,instructor_mark

``code_dir`` and ``report_path`` are paths relative to the CSV file (leave
blank when not submitted). Every row of one submission must repeat the same
paths.

Reports, for the chosen grader:
  - MAE (marks), share of criteria within 1 mark, bias (model - instructor)
  - false zeros: model gave 0 where the instructor gave marks
  - with --calibrate: a linear fit (instructor ~ a * model + b) learned on the
    first half of submissions and checked on the second half

Example:
    python scripts/evaluate_grader.py data/mohler_eval.csv --model qwen3:8b
    python scripts/evaluate_grader.py data/mohler_eval.csv --backend heuristic
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluator.code_analysis import FULL_SOURCE_LIMIT, analyze_directory, read_sources  # noqa: E402
from app.evaluator.report_analysis import analyze_report  # noqa: E402
from app.evaluator.rubric_grading import (  # noqa: E402
    Criterion,
    Evidence,
    HeuristicRubricGrader,
    OllamaRubricGrader,
)


@dataclass
class Submission:
    submission_id: str
    code_dir: Path | None
    report_path: Path | None
    criteria: list[Criterion] = field(default_factory=list)
    instructor: list[float] = field(default_factory=list)


def load_rows(csv_path: Path) -> list[Submission]:
    base = csv_path.parent
    submissions: dict[str, Submission] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sid = row["submission_id"].strip()
            if sid not in submissions:
                code = row.get("code_dir", "").strip()
                report = row.get("report_path", "").strip()
                submissions[sid] = Submission(
                    sid,
                    base / code if code else None,
                    base / report if report else None,
                )
            sub = submissions[sid]
            sub.criteria.append(Criterion(
                name=row["criterion"].strip(),
                description=row.get("description", "").strip(),
                max_points=float(row["max_points"]),
            ))
            sub.instructor.append(float(row["instructor_mark"]))
    return list(submissions.values())


def build_evidence(sub: Submission) -> Evidence:
    evidence = Evidence()
    if sub.code_dir:
        evidence.code_reports = analyze_directory(sub.code_dir)
        evidence.code_sources = read_sources(sub.code_dir, max_chars_per_file=FULL_SOURCE_LIMIT,
                                             max_total_chars=FULL_SOURCE_LIMIT)
    if sub.report_path:
        evidence.report = analyze_report(sub.report_path)
    return evidence


def grade_all(subs: list[Submission], grader) -> list[list[float]]:
    """Model marks per submission, aligned with each submission's criteria."""
    model_marks = []
    for sub in subs:
        result = grader.grade(sub.criteria, build_evidence(sub))
        model_marks.append([c.score for c in result.criteria])
        print(f"graded {sub.submission_id} ({len(sub.criteria)} criteria)", file=sys.stderr)
    return model_marks


def metrics(pairs: list[tuple[float, float]]) -> dict[str, float]:
    """pairs: (model, instructor)."""
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    errors = [abs(m - i) for m, i in pairs]
    return {
        "n": n,
        "mae": sum(errors) / n,
        "within_1": sum(e <= 1 for e in errors) / n,
        "bias": sum(m - i for m, i in pairs) / n,
        "false_zeros": sum(1 for m, i in pairs if m == 0 and i > 0),
    }


def fit_line(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """Least squares for instructor = a * model + b."""
    n = len(pairs)
    mx = sum(m for m, _ in pairs) / n
    my = sum(i for _, i in pairs) / n
    var = sum((m - mx) ** 2 for m, _ in pairs)
    a = sum((m - mx) * (i - my) for m, i in pairs) / var if var else 1.0
    return a, my - a * mx


def show(title: str, stats: dict) -> None:
    if not stats.get("n"):
        print(f"{title}: no data")
        return
    print(f"{title}: n={stats['n']}  MAE={stats['mae']:.2f}  within-1={stats['within_1']:.0%}  "
          f"bias={stats['bias']:+.2f}  false zeros={stats['false_zeros']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--backend", choices=["ollama", "heuristic"], default="ollama")
    parser.add_argument("--model", default=None, help="Ollama model (default: OLLAMA_MODEL / qwen3:4b)")
    parser.add_argument("--calibrate", action="store_true",
                        help="fit a linear correction on the first half, report on the second half")
    args = parser.parse_args()

    subs = load_rows(args.csv)
    if not subs:
        sys.exit("no rows in the CSV")

    if args.backend == "heuristic":
        grader = HeuristicRubricGrader()
    else:
        grader = OllamaRubricGrader(model=args.model) if args.model else OllamaRubricGrader()
    print(f"grader: {grader.name}" + (f" ({grader.model})" if hasattr(grader, "model") else ""))

    model_marks = grade_all(subs, grader)
    pairs = [(m, i) for sub, marks in zip(subs, model_marks)
             for m, i in zip(marks, sub.instructor)]
    show("all criteria", metrics(pairs))

    if args.calibrate:
        half = len(subs) // 2
        train = [(m, i) for sub, marks in zip(subs[:half], model_marks[:half])
                 for m, i in zip(marks, sub.instructor)]
        test = [(m, i) for sub, marks in zip(subs[half:], model_marks[half:])
                for m, i in zip(marks, sub.instructor)]
        a, b = fit_line(train)
        print(f"calibration fitted on {len(train)} criteria: instructor ~ {a:.3f} * model {b:+.3f}")
        show("held-out, raw", metrics(test))
        show("held-out, calibrated", metrics([(max(0.0, a * m + b), i) for m, i in test]))


if __name__ == "__main__":
    main()
