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

Vision: a few sampled frames are described by a small local vision model
(Ollama, default ``qwen3-vl:4b``) so a video with no speech can still be
graded from what is on screen. Opt-in (``VIDEO_VISION=auto``), so by default
only the grading model is used. A failure never breaks the analysis.
"""

from __future__ import annotations

import base64
import logging
import os
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .rubric_grading import (OLLAMA_NUM_CTX, OLLAMA_NUM_PREDICT, OLLAMA_SAMPLING, OLLAMA_URL,
                             _ollama_available, _ollama_post)

logger = logging.getLogger(__name__)


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


def _register_nvidia_dlls() -> None:
    """On Windows, let CTranslate2 find the CUDA libraries that pip installs
    (nvidia-cublas-cu12, nvidia-cudnn-cu12) under site-packages/nvidia/*/bin;
    Windows does not search there on its own. No-op elsewhere or when the
    packages are not installed."""
    if os.name != "nt":
        return
    try:
        import nvidia
    except ImportError:
        return
    for root in getattr(nvidia, "__path__", []):
        for bin_dir in sorted(Path(root).glob("*/bin")):
            if str(bin_dir) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                os.add_dll_directory(str(bin_dir))


def _cuda_available() -> bool:
    _register_nvidia_dlls()
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
        except Exception as exc:
            if self.device != "cuda":
                raise
            # Not silent: the CPU retry is several times slower, so say why.
            logger.warning("Whisper on the GPU failed (%s: %s); transcribing on the CPU instead, which is much slower",
                           exc.__class__.__name__, exc)
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
        # grab() advances without converting the frame; only the sampled
        # frames (one per 1/sample_fps seconds) are retrieved.
        if not cap.grab():
            break
        if frame_idx % frame_interval == 0:
            ret, frame = cap.retrieve()
            if not ret:
                break
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
# Vision: describe sampled frames (F4)
# --------------------------------------------------------------------------
#
# A video with no speech has an empty transcript, so the grader would have
# nothing to judge. A small local vision model (Ollama, default qwen3-vl:4b)
# describes a few frames spread across the video and those descriptions are
# given to the grader next to the transcript. Opt-in: set ``VIDEO_VISION=auto``
# (and install the model); off by default. Any failure leaves the
# rest of the analysis intact.

VISION_MODEL = os.environ.get("VISION_MODEL", "qwen3-vl:4b")
FRAMES_TO_DESCRIBE = 4
FRAME_MAX_SIDE = 512  # pixels; keeps requests small and fast

_DESCRIBE_PROMPT = (
    "Describe what is visible in this video frame in one or two plain sentences. "
    "Focus on on-screen text, code, terminals, slides, diagrams, application windows "
    "and people. Describe only what you can actually see; do not guess or invent."
)


@dataclass
class FrameDescription:
    seconds: float
    text: str


def sample_frames(video_path: Path, count: int = FRAMES_TO_DESCRIBE,
                  max_side: int = FRAME_MAX_SIDE) -> list[tuple[float, bytes]]:
    """`count` JPEG frames, one from the middle of each of `count` equal slices
    of the video, as (timestamp_seconds, jpeg_bytes), downscaled to `max_side`."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames: list[tuple[float, bytes]] = []
    for i in range(count if total > 0 else 0):
        index = int(total * (i + 0.5) / count)
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        scale = max_side / max(height, width)
        if scale < 1:
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            frames.append((index / fps, buffer.tobytes()))
    cap.release()
    return frames


class FrameDescriber(ABC):
    model: str

    @abstractmethod
    def describe(self, frames: list[tuple[float, bytes]]) -> list[FrameDescription]: ...


class OllamaFrameDescriber(FrameDescriber):
    """One Ollama chat call per frame. `post` is any callable
    ``(url, payload, timeout) -> dict``; inject a fake in tests."""

    def __init__(self, model: str = VISION_MODEL, url: str = OLLAMA_URL, post=_ollama_post,
                 timeout: float = 180.0):
        self.model = model
        self.url = url.rstrip("/")
        self.post = post
        self.timeout = timeout

    def describe(self, frames: list[tuple[float, bytes]]) -> list[FrameDescription]:
        results: list[FrameDescription] = []
        errors: list[str] = []
        for seconds, jpeg in frames:
            payload = {
                "model": self.model,
                "messages": [{
                    "role": "user",
                    "content": _DESCRIBE_PROMPT,
                    "images": [base64.b64encode(jpeg).decode("ascii")],
                }],
                "stream": False,
                "think": False,
                "options": {**OLLAMA_SAMPLING, "num_ctx": OLLAMA_NUM_CTX,
                            "num_predict": OLLAMA_NUM_PREDICT},
            }
            try:
                reply = self.post(f"{self.url}/api/chat", payload, self.timeout)
                text = str(reply["message"]["content"]).strip()
            except Exception as exc:  # one bad frame should not lose the others
                errors.append(f"{exc.__class__.__name__}: {exc}")
                continue
            if text:
                results.append(FrameDescription(seconds=seconds, text=text))
        if not results and errors:
            raise RuntimeError(errors[0])
        return results


def build_default_describer() -> FrameDescriber | None:
    """None (no frame descriptions) by default, so only the grading model is used.
    With VIDEO_VISION=auto (or on) the Ollama vision describer is used when
    the vision model is installed."""
    if os.environ.get("VIDEO_VISION", "off").strip().lower() not in ("auto", "on"):
        return None
    return OllamaFrameDescriber() if _ollama_available(OLLAMA_URL, VISION_MODEL) else None


# --------------------------------------------------------------------------
# Combined video analysis
# --------------------------------------------------------------------------


@dataclass
class VideoAnalysis:
    transcript: TranscriptionResult
    frames: FrameAnalysis
    frame_descriptions: list[FrameDescription] = field(default_factory=list)
    vision_model: str = ""
    vision_error: str = ""  # set when frame description was attempted and failed


def analyze_video(video_path: Path, transcriber: Transcriber | None = None,
                  describer: FrameDescriber | None = None) -> VideoAnalysis:
    transcriber = transcriber or build_default_transcriber()
    describer = describer or build_default_describer()
    try:
        transcript = transcriber.transcribe(video_path)
    except Exception as exc:  # e.g. model download failed offline, GPU/driver error
        # Never let speech-to-text take down the evaluation: carry on with an
        # empty transcript and the frame analysis, and keep the reason.
        transcript = TranscriptionResult(
            text="", segments=[], backend="null",
            error=f"{exc.__class__.__name__}: {exc}"[:200],
        )
    frames = analyze_frames(video_path)

    descriptions: list[FrameDescription] = []
    vision_model, vision_error = "", ""
    if describer is not None:
        vision_model = describer.model
        try:
            descriptions = describer.describe(sample_frames(video_path))
        except Exception as exc:  # the vision step is optional; keep everything else
            vision_error = f"{exc.__class__.__name__}: {exc}"[:200]
    return VideoAnalysis(transcript=transcript, frames=frames, frame_descriptions=descriptions,
                         vision_model=vision_model, vision_error=vision_error)
