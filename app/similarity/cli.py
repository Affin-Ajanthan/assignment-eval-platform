"""
Command-line entry point for the pre-submission similarity checker.

Usage:
    python -m app.similarity.cli check <submissions_dir> \\
        [--threshold 0.6] [--out report.html] [--json report.json] [--no-semantic]

<submissions_dir> layout -- one subfolder per student, containing their
source files (any nesting), e.g.:

    submissions/
      alice/solution.py
      bob/src/main.py
      carol/app.js

Semantic (UniXcoder) similarity is added as an extra signal when
torch/transformers are installed and the model can be loaded; pass
--no-semantic to skip it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai_heuristics import score_source
from .core import Fingerprint, compare_all, fingerprint_source
from .semantic import (
    apply_semantic_signal,
    get_semantic_service,
    normalize_code,
    submissions_needing_semantic,
)

CODE_EXTENSIONS = {".py", ".java", ".js", ".ts", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rb"}


def _iter_student_dirs(root: Path):
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            yield entry


def _iter_code_files(student_dir: Path):
    for path in sorted(student_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in CODE_EXTENSIONS:
            yield path


def build_fingerprints(submissions_dir: Path) -> dict[str, Fingerprint]:
    fingerprints: dict[str, Fingerprint] = {}
    for student_dir in _iter_student_dirs(submissions_dir):
        merged = Fingerprint(submission_id=student_dir.name, filename="(all files)", token_count=0)
        for file_path in _iter_code_files(student_dir):
            source = file_path.read_text(encoding="utf-8", errors="ignore")
            fp = fingerprint_source(student_dir.name, file_path.name, source)
            merged.hashes |= fp.hashes
            merged.token_count += fp.token_count
        fingerprints[student_dir.name] = merged
    return fingerprints


def build_semantic_sources(submissions_dir: Path) -> dict[str, str]:
    return {
        student_dir.name: "\n".join(
            normalize_code(path.read_text(encoding="utf-8", errors="ignore"), path.name)
            for path in _iter_code_files(student_dir)
        )
        for student_dir in _iter_student_dirs(submissions_dir)
    }


def build_ai_scores(submissions_dir: Path):
    scores = []
    for student_dir in _iter_student_dirs(submissions_dir):
        combined_source = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
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

    args = parser.parse_args(argv)

    if not args.submissions_dir.is_dir():
        parser.error(f"{args.submissions_dir} is not a directory")

    fingerprints = build_fingerprints(args.submissions_dir)
    if len(fingerprints) < 2:
        print("Need at least 2 student submissions to compare.", file=sys.stderr)
        return 1

    pairs = compare_all(fingerprints)
    scores = build_ai_scores(args.submissions_dir)

    semantic_note = "disabled (--no-semantic)"
    if not args.no_semantic:
        needed = submissions_needing_semantic(pairs)
        sources = {k: v for k, v in build_semantic_sources(args.submissions_dir).items() if k in needed}
        batch = get_semantic_service().embed_submissions(sources)
        if batch.status == "ok":
            apply_semantic_signal(pairs, batch.embeddings)
            semantic_note = f"{batch.encoded} submission(s) encoded with UniXcoder"
        else:
            semantic_note = batch.warning or batch.status
            print(f"Warning: {semantic_note}", file=sys.stderr)

    from .report import render_html
    args.out.write_text(render_html(pairs, scores, args.threshold, semantic_note), encoding="utf-8")
    print(f"Wrote {args.out}")

    if args.json:
        payload = {
            "pairs": [{**p.__dict__, "token_flagged": p.token_flagged, "flagged": p.flagged} for p in pairs],
            "semantic": semantic_note,
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
