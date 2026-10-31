"""
Command-line entry point for the pre-submission similarity checker.

Usage:
    python -m app.similarity.cli check <submissions_dir> \\
        [--threshold 0.6] [--out report.html] [--json report.json] [--no-semantic] [--keep-common]

<submissions_dir> layout -- one subfolder per student, containing their
source files (any nesting), e.g.:

    submissions/
      alice/solution.py
      bob/src/main.py
      carol/app.js

The comparison is the one the website runs (app/similarity_runs.py): the same
file types, junk code removed before fingerprinting, code most of the class
shares left out (as the assignment option does by default; --keep-common to
compare all code), and UniXcoder semantic similarity as an extra signal when
torch/transformers are installed and the model can be loaded (--no-semantic
to skip it).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..common import ANALYZED_EXTENSIONS
from ..notebook import read_code
from .ai_heuristics import score_source


def _iter_student_dirs(root: Path):
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            yield entry


def _iter_code_files(student_dir: Path):
    for path in sorted(student_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in ANALYZED_EXTENSIONS:
            yield path


def build_ai_scores(submissions_dir: Path):
    scores = []
    for student_dir in _iter_student_dirs(submissions_dir):
        combined_source = "\n".join(
            read_code(path)[1]
            for path in _iter_code_files(student_dir)
        )
        if combined_source.strip():
            scores.append(score_source(student_dir.name, combined_source))
    return scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.similarity.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run a pre-submission self-check")
    check.add_argument("submissions_dir", type=Path)
    check.add_argument("--threshold", type=float, default=0.6)
    check.add_argument("--out", type=Path, default=Path("report.html"))
    check.add_argument("--json", type=Path, default=None)
    check.add_argument("--no-semantic", action="store_true",
                       help="skip the UniXcoder semantic-similarity signal")
    check.add_argument("--keep-common", action="store_true",
                       help="compare all code, including code most of the class shares")

    args = parser.parse_args(argv)

    if not args.submissions_dir.is_dir():
        parser.error(f"{args.submissions_dir} is not a directory")

    dirs = {d.name: d for d in _iter_student_dirs(args.submissions_dir)}
    if len(dirs) < 2:
        print("Need at least 2 student submissions to compare.", file=sys.stderr)
        return 1

    if args.no_semantic:
        os.environ["SEMANTIC_SIMILARITY"] = "0"  # read when the semantic service is first created
    from ..similarity_runs import code_similarity_for_dirs

    run = code_similarity_for_dirs(dirs, remove_common=not args.keep_common)
    pairs, batch = run.pairs, run.batch
    scores = build_ai_scores(args.submissions_dir)

    if args.no_semantic:
        semantic_note = "disabled (--no-semantic)"
    elif batch.status == "ok":
        semantic_note = f"{batch.encoded} submission(s) encoded with UniXcoder"
    else:
        semantic_note = batch.warning or batch.status
        print(f"Warning: {semantic_note}", file=sys.stderr)
    if run.common_removed:
        semantic_note += f"; {run.common_removed} fingerprint(s) shared by most of the class left out"

    from .report import render_html
    args.out.write_text(render_html(pairs, scores, args.threshold, semantic_note), encoding="utf-8")
    print(f"Wrote {args.out}")

    if args.json:
        payload = {
            "pairs": [{**p.__dict__, "token_flagged": p.token_flagged, "flagged": p.flagged} for p in pairs],
            "semantic": semantic_note,
            "common_removed": run.common_removed,
            "ai_scores": [s.__dict__ for s in scores],
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.json}")

    flagged = [p for p in pairs if p.flagged]
    if flagged:
        print(f"\n{len(flagged)} pair(s) with potential similarity -- review recommended:")
        for p in flagged:
            semantic = "n/a" if p.semantic_similarity is None else f"{p.semantic_similarity:.2f}"
            print(f"  {p.submission_a} <-> {p.submission_b}: "
                  f"jaccard={p.jaccard:.2f} containment={p.containment:.2f} semantic={semantic}"
                  f"{' -- ' + p.flag_reason if p.flag_reason else ''}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
