"""Write the Whisper transcript of a video as subtitles, to see exactly what
the auto-evaluation's cross-modal check reads.

Uses the same transcriber as the pipeline (faster-whisper "small", GPU when
available). Writes next to the video, or into --out:
  <name>.srt  subtitles with timestamps (open with the video in VLC, or in Notepad)
  <name>.txt  the plain transcript text the consistency check compares

Usage:
  python scripts/transcribe_video.py "uploads/<folder>/video/<file>.mp4"
  python scripts/transcribe_video.py --submission 117
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.evaluator.video_analysis import build_default_transcriber  # noqa: E402


def _timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(segments: list[dict]) -> str:
    blocks = [f"{i}\n{_timestamp(s['start'])} --> {_timestamp(s['end'])}\n{s['text']}\n"
              for i, s in enumerate(segments, 1)]
    return "\n".join(blocks)


def _submission_video(submission_id: int) -> Path:
    db = sqlite3.connect(f"file:{ROOT / 'portal.db'}?mode=ro", uri=True)  # read-only
    row = db.execute("SELECT video_path FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    if not row:
        sys.exit(f"No submission #{submission_id}")
    if not row[0]:
        sys.exit(f"Submission #{submission_id} has no video")
    return ROOT / row[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", nargs="?", help="path to the video file")
    parser.add_argument("--submission", type=int, help="use this submission's uploaded video instead")
    parser.add_argument("--out", help="folder for the .srt/.txt files (default: next to the video)")
    args = parser.parse_args()
    if not args.video and args.submission is None:
        parser.error("give a video path or --submission ID")

    video = _submission_video(args.submission) if args.submission is not None else Path(args.video)
    if not video.is_file():
        sys.exit(f"Video not found: {video}")
    out_dir = Path(args.out) if args.out else video.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Transcribing {video} ...")
    started = time.perf_counter()
    result = build_default_transcriber().transcribe(video)
    if result.error:
        sys.exit(f"Transcription failed: {result.error}")

    srt = out_dir / f"{video.stem}.srt"
    txt = out_dir / f"{video.stem}.txt"
    srt.write_text(to_srt(result.segments), encoding="utf-8")
    txt.write_text(result.text + "\n", encoding="utf-8")
    print(f"Done in {time.perf_counter() - started:.0f} s with {result.backend}: "
          f"{len(result.segments)} lines, {len(result.text.split())} words")
    print(f"  subtitles:  {srt}")
    print(f"  plain text: {txt}")


if __name__ == "__main__":
    main()
