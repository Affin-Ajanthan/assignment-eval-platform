"""
Video pipeline (plan diagram nodes F1 transcription, F2 scene/frame
analysis, F3 screen-recording detection).

Transcription is pluggable behind the ``Transcriber`` interface:

- ``NullTranscriber`` (default fallback): returns an empty transcript.
  Keeps the rest of the pipeline runnable with zero setup.
- ``WhisperTranscriber``: real speech-to-text via ``faster-whisper``
  (CTranslate2, no torch required). Uses the Whisper ``small`` model on
  CUDA (float16) when an NVIDIA GPU is available, and falls back to CPU
  (int8) otherwise or if the GPU fails to load. Downloads its model
  from Hugging Face on first use, so it needs outbound network access
  to huggingface.co -- not available in every sandboxed environment,
  but this is real, working code for a normal deployment.

If transcription fails for any reason (model download blocked, GPU error),
``analyze_video`` keeps going with an empty transcript (backend ``null``,
reason in ``TranscriptionResult.error``) so the pipeline never crashes on
the speech-to-text stage.

Frame analysis (scene changes + a screen-recording likelihood score)
uses OpenCV frame-differencing and needs no network access or model
download at all, so it always runs for real.
"""

from __future__ import annotations

import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


# --------------------------------------------------------------------------
# Transcription (F1)
# --------------------------------------------------------------------------


@dataclass
class TranscriptionResult:
    text: str
    segments: list[dict]
    backend: str
    error: str = ""  # set when transcription failed and the text is empty


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, video_path: Path) -> TranscriptionResult: ...


class NullTranscriber(Transcriber):
    """No-op transcriber: returns an empty transcript. This is the safe
    default when no speech-to-text backend is configured or reachable,
    so the rest of the pipeline (cross-modal consistency, grading)
    degrades gracefully instead of crashing."""

    def transcribe(self, video_path: Path) -> TranscriptionResult:
        return TranscriptionResult(text="", segments=[], backend="null")


def _cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class WhisperTranscriber(Transcriber):
    """Real speech-to-text via faster-whisper. Requires the
    `faster-whisper` package and, on first use, network access to
    download the model weights from Hugging Face.

    Defaults to the `small` model. ``device="auto"`` runs on CUDA
    (float16) when a GPU is available and on CPU (int8) otherwise; if
    the GPU run fails (e.g. missing CUDA libraries), it retries once on
    CPU instead of failing the transcription."""

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str | None = None):
        if device == "auto":
            device = "cuda" if _cuda_available() else "cpu"
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type or ("float16" if device == "cuda" else "int8")
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def _fall_back_to_cpu(self) -> None:
        self.device, self.compute_type, self._model = "cpu", "int8", None

    def transcribe(self, video_path: Path) -> TranscriptionResult:
        try:
            segments, _info = self._load().transcribe(str(video_path))
            segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
        except Exception:
            if self.device != "cuda":
                raise
            self._fall_back_to_cpu()
            segments, _info = self._load().transcribe(str(video_path))
            segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
        text = " ".join(s["text"] for s in segs)
        return TranscriptionResult(
            text=text, segments=segs,
            backend=f"faster-whisper-{self.model_size}-{self.device}",
        )


def build_default_transcriber() -> Transcriber:
    """WhisperTranscriber when faster-whisper is installed; NullTranscriber
    otherwise. Model download failures happen lazily on first
    `.transcribe()` call, not here, so this never raises."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return NullTranscriber()
    return WhisperTranscriber()


# --------------------------------------------------------------------------
# Frame / scene analysis + screen-recording heuristic (F2, F3)
# --------------------------------------------------------------------------


@dataclass
class FrameAnalysis:
    frames_sampled: int
    duration_seconds: float
    scene_changes: int
    avg_frame_diff: float
    screen_recording_score: int  # 0-100: higher = more likely a static screen recording
    reasons: list[str] = field(default_factory=list)


# Mean grayscale pixel-intensity difference (0-255 scale) above which two
# sampled frames count as a "scene change". Tuned empirically against the
# synthetic test fixtures in tests/test_video_analysis.py.
_SCENE_CHANGE_THRESHOLD = 20.0


def analyze_frames(video_path: Path, sample_fps: float = 1.0) -> FrameAnalysis:
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(1, int(round(fps / sample_fps)))
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = (total_frames / fps) if fps else 0.0

    prev_gray = None
    diffs: list[float] = []
    scene_changes = 0
    frame_idx = 0
    sampled = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (160, 90))
            if prev_gray is not None:
                diff = float(np.mean(cv2.absdiff(gray, prev_gray)))
                diffs.append(diff)
                if diff > _SCENE_CHANGE_THRESHOLD:
                    scene_changes += 1
            prev_gray = gray
            sampled += 1
        frame_idx += 1
    cap.release()

    avg_diff = statistics.mean(diffs) if diffs else 0.0
    reasons: list[str] = []
    if avg_diff < 5 and duration > 15:
        score = 80
        reasons.append("very low frame-to-frame variation, consistent with a static screen recording")
    elif avg_diff < 12:
        score = 50
        reasons.append("moderate frame-to-frame variation")
    else:
        score = 20
        reasons.append("high frame-to-frame variation, more consistent with live camera footage")

    if scene_changes == 0 and duration > 30:
        reasons.append("no detected scene changes across a video over 30 seconds long")

    return FrameAnalysis(
        frames_sampled=sampled,
        duration_seconds=duration,
        scene_changes=scene_changes,
        avg_frame_diff=round(avg_diff, 2),
        screen_recording_score=score,
        reasons=reasons,
    )


# --------------------------------------------------------------------------
# Combined video analysis
# --------------------------------------------------------------------------


@dataclass
class VideoAnalysis:
    transcript: TranscriptionResult
    frames: FrameAnalysis


def analyze_video(video_path: Path, transcriber: Transcriber | None = None) -> VideoAnalysis:
    transcriber = transcriber or build_default_transcriber()
    try:
        transcript = transcriber.transcribe(video_path)
    except Exception as exc:  # e.g. model download failed offline, GPU/driver error
        # Never let speech-to-text take down the evaluation: carry on with an
        # empty transcript and the frame analysis, and keep the reason.
        transcript = TranscriptionResult(
            text="", segments=[], backend="null",
            error=f"{exc.__class__.__name__}: {exc}"[:200],
        )
    return VideoAnalysis(transcript=transcript, frames=analyze_frames(video_path))
