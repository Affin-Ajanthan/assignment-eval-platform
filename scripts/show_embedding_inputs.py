"""Save the exact text the cross-modal semantic check embeds for one
submission, so it can be read and checked.

Nothing is summarised: the model reads the full text of each part, after the
same cleaning and chunking the pipeline does (semantic_consistency.py):
  code       -> docstrings, comments and README; when there are none, the code's
                own text with comments removed (names and printed messages)
  report     -> the report text extracted with MarkItDown
  transcript -> the Whisper transcript of the video

Writes to uploads/embedding_inputs/submission_<ID>/ (git-ignored):
  1_code_documentation.txt  2_report.txt  3_transcript.txt
  chunks.txt  -- each part split into the ~120-word pieces the model actually reads

Usage:
  python scripts/show_embedding_inputs.py 57
  python scripts/show_embedding_inputs.py 57 --transcribe   # also run Whisper on the video
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.evaluator.document_extraction import extract_report_text, load_extraction  # noqa: E402
from app.evaluator.semantic_consistency import (  # noqa: E402
    MIN_WORDS,
    chunk_text,
    clean_text,
    extract_code_documentation,
    extract_code_text,
)


def _paths(submission_id: int) -> tuple[Path | None, Path | None, Path | None]:
    db = sqlite3.connect(f"file:{ROOT / 'portal.db'}?mode=ro", uri=True)  # read-only
    row = db.execute("SELECT code_path, report_path, video_path FROM submissions WHERE id = ?",
                     (submission_id,)).fetchone()
    if not row:
        sys.exit(f"No submission #{submission_id}")
    return tuple(ROOT / p if p else None for p in row)


def _transcript(video: Path | None, transcribe: bool) -> tuple[str | None, str]:
    if not video or not video.is_file():
        return None, "no video submitted"
    saved = video.with_suffix(".txt")  # written by scripts/transcribe_video.py
    if saved.is_file() and not transcribe:
        return saved.read_text(encoding="utf-8"), f"saved transcript {saved.name}"
    if not transcribe:
        return None, "not transcribed -- add --transcribe (runs Whisper on the video)"
    from app.evaluator.video_analysis import build_default_transcriber
    result = build_default_transcriber().transcribe(video)
    if result.error:
        return None, f"transcription failed: {result.error}"
    saved.write_text(result.text + "\n", encoding="utf-8")
    return result.text, f"Whisper ({result.backend})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("submission", type=int, help="submission ID")
    parser.add_argument("--transcribe", action="store_true", help="run Whisper on the video")
    args = parser.parse_args()

    code_dir, report_path, video = _paths(args.submission)
    parts: dict[str, tuple[str | None, str]] = {}

    if code_dir and code_dir.is_dir():
        docs = extract_code_documentation(code_dir)
        if len(clean_text(docs).split()) >= MIN_WORDS:
            parts["code_documentation"] = (docs, "comments, docstrings and README")
        else:
            parts["code_documentation"] = (extract_code_text(code_dir),
                                           "no documentation -- the code's own text, comments removed")
    else:
        parts["code_documentation"] = (None, "no code submitted")

    if report_path and report_path.is_file():
        extraction = load_extraction(report_path) or extract_report_text(report_path)
        parts["report"] = ((extraction.text, f"MarkItDown, {report_path.name}") if extraction.ok
                           else (None, f"extraction {extraction.status}: {extraction.error}"))
    else:
        parts["report"] = (None, "no report submitted")

    parts["transcript"] = _transcript(video, args.transcribe)

    out = ROOT / "uploads" / "embedding_inputs" / f"submission_{args.submission}"
    out.mkdir(parents=True, exist_ok=True)
    chunk_lines = []
    print(f"Submission #{args.submission} -- text the embedding model reads:")
    for i, (name, (raw, source)) in enumerate(parts.items(), 1):
        cleaned = clean_text(raw)
        words = len(cleaned.split())
        (out / f"{i}_{name}.txt").write_text(cleaned + "\n" if cleaned else f"(none: {source})\n", encoding="utf-8")
        chunks = chunk_text(cleaned) if words >= MIN_WORDS else []
        status = f"{words} words, {len(chunks)} chunks" if chunks else f"not compared ({source})"
        print(f"  {name:20s} {status:28s} from {source}")
        chunk_lines.append(f"===== {name} ({status}) =====")
        chunk_lines += [f"--- chunk {n} ({len(c.split())} words) ---\n{c}" for n, c in enumerate(chunks, 1)]
        chunk_lines.append("")
    (out / "chunks.txt").write_text("\n".join(chunk_lines), encoding="utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
