"""
AI-generated-text signal for reports: Fast-DetectGPT (Bao et al., ICLR 2024,
"Fast-DetectGPT: Efficient Zero-Shot Detection of Machine-Generated Text via
Conditional Probability Curvature"), run locally with a small open language
model (default ``Qwen/Qwen2.5-0.5B``, configurable).

The idea: a language model scores every token of the text. Machine-written
text keeps choosing tokens the model itself rates as likely, so its actual
log-likelihood sits well ABOVE what the model would expect from its own
samples; human text is spikier. The "conditional probability curvature" is

    (sum log p(x_t) - sum E[log p]) / sqrt(sum Var[log p])

computed analytically (the scoring model doubles as the sampling model, so
no sampling is needed). Roughly 0 for human-like text, larger for
machine-like text.

How it's applied here:

- the report is split into fixed 256-token chunks and each chunk is scored
  separately; the report's score is the mean over chunks. (The raw formula
  grows with text length, so scoring one long sequence would make long
  reports look more "AI" just for being long.)
- to bound CPU time, at most ``AI_TEXT_MAX_CHUNKS`` chunks (default 8) are
  scored, sampled evenly across the WHOLE report -- not just its start;
- reports shorter than ~120 tokens are reported as "insufficient text";
- the result uses the same ``TextHeuristicScore`` shape as the old style
  heuristic, which remains the fallback when the model can't be loaded.

THIS IS A REVIEW SIGNAL, NOT A VERDICT. No AI-text detector is reliable
enough to prove anything: false positives are common on formal, template-
like or non-native English writing, and light editing defeats detection.
The thresholds below (``AI_TEXT_MEDIUM`` / ``AI_TEXT_HIGH``) are prototype
values from a small hand-assembled sample and have not been validated on
real student reports.

Calibration (6 AI-written report passages, 12 human-written passages from
older package documentation; mean chunk curvature):

    Qwen2.5-0.5B   AI -1.39 .. 2.52 (median ~0.2)   human -2.50 .. 0.50
    Qwen2.5-1.5B   AI -0.95 .. 0.69                 human -2.74 .. 0.37

The ranges overlap heavily (Fast-DetectGPT works best when the scoring
model resembles the model that wrote the text; modern assistants differ a
lot from small Qwen models), and on this sample it did no better than the
style heuristic. It is therefore OFF by default.

Configuration: ``AI_TEXT_DETECTION=1`` enables the model (otherwise the
style heuristic is used); ``AI_TEXT_DETECTOR_MODEL`` picks another causal
LM (base models work best).
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Protocol

log = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B"
CHUNK_TOKENS = 256
MIN_TOKENS = 120
DEFAULT_MAX_CHUNKS = 8
# Chunk-mean curvature bands (see module docstring: prototype values).
DEFAULT_MEDIUM = 1.0
DEFAULT_HIGH = 2.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _enabled() -> bool:
    # OFF unless AI_TEXT_DETECTION=1: on the calibration sample it did no
    # better than the style heuristic (see module docstring).
    return os.environ.get("AI_TEXT_DETECTION", "0").strip().lower() in {"1", "true", "yes", "on"}


def model_name() -> str:
    return os.environ.get("AI_TEXT_DETECTOR_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


@dataclass
class DetectionResult:
    curvature: float | None  # mean chunk curvature; None if not computed
    chunks_scored: int
    total_tokens: int
    model: str
    status: str  # "ok" | "insufficient_text"


def select_chunks(ids: list, chunk_tokens: int, max_chunks: int) -> list[list]:
    """Fixed-size token chunks; a short tail (< half a chunk) is dropped when
    there are others, and at most ``max_chunks`` are kept, spread evenly
    across the whole document rather than taken from its start."""
    chunks = [ids[i:i + chunk_tokens] for i in range(0, len(ids), chunk_tokens)]
    if len(chunks) > 1 and len(chunks[-1]) < chunk_tokens // 2:
        chunks.pop()  # too noisy to score on its own
    if len(chunks) > max_chunks:
        step = len(chunks) / max_chunks
        chunks = [chunks[int(i * step)] for i in range(max_chunks)]
    return chunks


class CurvatureScorer(Protocol):
    def token_count(self, text: str) -> int: ...

    def chunk_curvatures(self, text: str, chunk_tokens: int, max_chunks: int) -> tuple[list[float], int]: ...


class FastDetectGPTScorer:
    """Loads the scoring model once (CPU) and computes per-chunk curvature."""

    def __init__(self, name: str | None = None, device: str = "cpu"):
        from ..model_loading import MODEL_LOAD_LOCK

        self.name = name or model_name()
        with MODEL_LOAD_LOCK:  # see app/model_loading.py
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from transformers.utils import logging as hf_logging

            self._torch = torch
            verbosity = hf_logging.get_verbosity()
            hf_logging.set_verbosity_error()
            hf_logging.disable_progress_bar()
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.name)
                self.model = AutoModelForCausalLM.from_pretrained(self.name, dtype=torch.float32)
            finally:
                hf_logging.set_verbosity(verbosity)
                hf_logging.enable_progress_bar()
        self.model.to(device)
        self.model.eval()
        self.device = device

    def token_count(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])

    def chunk_curvatures(self, text: str, chunk_tokens: int, max_chunks: int) -> tuple[list[float], int]:
        torch = self._torch
        ids = self.tokenizer(text, add_special_tokens=False)["input_ids"]
        chunks = select_chunks(ids, chunk_tokens, max_chunks)
        scores = []
        with torch.inference_mode():
            for chunk in chunks:
                input_ids = torch.tensor([chunk], device=self.device)
                logits = self.model(input_ids=input_ids).logits[0, :-1].float()
                labels = input_ids[0, 1:]
                lprobs = torch.log_softmax(logits, dim=-1)
                probs = lprobs.exp()
                ll = lprobs.gather(-1, labels.unsqueeze(-1)).squeeze(-1)
                mean_ref = (probs * lprobs).sum(-1)
                var_ref = (probs * lprobs.square()).sum(-1) - mean_ref.square()
                scores.append(float((ll.sum() - mean_ref.sum()) / var_ref.sum().clamp_min(1e-6).sqrt()))
        return scores, len(ids)


class AITextDetector:
    """Process-wide owner of the scoring model: loaded at most once, results
    cached by text hash, never raises from ``detect``."""

    def __init__(self, scorer_factory: Callable[[], CurvatureScorer] | None = None,
                 enabled: bool | None = None, cache_size: int = 256):
        self._factory = scorer_factory or FastDetectGPTScorer
        self._scorer: CurvatureScorer | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, DetectionResult] = OrderedDict()
        self._cache_size = cache_size
        self.enabled = _enabled() if enabled is None else enabled
        self.status = "not_loaded" if self.enabled else "disabled"  # | ready | unavailable
        self.error: str | None = None

    def load(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            if self._scorer is not None:
                return True
            if self.status == "unavailable":
                return False
            try:
                self._scorer = self._factory()
                self.status = "ready"
                return True
            except Exception as exc:
                self.status = "unavailable"
                self.error = f"{exc.__class__.__name__}: {exc}"
                log.warning("AI-text detector unavailable: %s", self.error)
                return False

    def preload_in_background(self) -> threading.Thread | None:
        if not self.enabled:
            return None
        thread = threading.Thread(target=self.load, name="fastdetectgpt-preload", daemon=True)
        thread.start()
        return thread

    def detect(self, text: str) -> DetectionResult | None:
        """None when the detector is disabled/unavailable or inference fails
        (the caller then falls back to the style heuristic)."""
        text = " ".join((text or "").split())
        if not self.load():
            return None
        name = getattr(self._scorer, "name", model_name())
        key = hashlib.sha256(f"{name}|{CHUNK_TOKENS}|{text}".encode()).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        try:
            if self._scorer.token_count(text) < MIN_TOKENS:
                result = DetectionResult(None, 0, self._scorer.token_count(text), name, "insufficient_text")
            else:
                max_chunks = int(_env_float("AI_TEXT_MAX_CHUNKS", DEFAULT_MAX_CHUNKS))
                scores, total = self._scorer.chunk_curvatures(text, CHUNK_TOKENS, max(1, max_chunks))
                if not scores or not all(math.isfinite(s) for s in scores):
                    raise ValueError("model returned no usable scores")
                result = DetectionResult(sum(scores) / len(scores), len(scores), total, name, "ok")
        except Exception as exc:
            log.warning("AI-text detection failed: %s", exc)
            return None
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result


def thresholds() -> tuple[float, float]:
    return _env_float("AI_TEXT_MEDIUM", DEFAULT_MEDIUM), _env_float("AI_TEXT_HIGH", DEFAULT_HIGH)


def to_score(result: DetectionResult):
    """Map a detection to the TextHeuristicScore shape the rest of the
    pipeline already uses (0-100 score, low/medium/high signal, reasons)."""
    from .report_analysis import TextHeuristicScore

    short = result.model.split("/")[-1]
    if result.status == "insufficient_text":
        return TextHeuristicScore(score=0, signal="low", reasons=[
            f"too little text for a reliable AI-text estimate ({result.total_tokens} tokens; "
            f"Fast-DetectGPT needs at least {MIN_TOKENS})"
        ], method=f"fast-detectgpt:{short}")
    medium, high = thresholds()
    c = result.curvature
    signal = "high" if c >= high else "medium" if c >= medium else "low"
    # Smooth 0-100 display score: 50 at the "high" threshold.
    score = round(100 / (1 + math.exp(-2.0 * (c - high))))
    return TextHeuristicScore(score=score, signal=signal, reasons=[
        f"Fast-DetectGPT curvature {c:.2f} (low < {medium:g} <= medium < {high:g} <= high; "
        f"{result.chunks_scored} chunk(s) of {CHUNK_TOKENS} tokens, model {short}) -- "
        "a statistical review signal, not proof"
    ], method=f"fast-detectgpt:{short}")


_detector: AITextDetector | None = None
_detector_lock = threading.Lock()


def get_ai_text_detector() -> AITextDetector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = AITextDetector()
        return _detector


def set_ai_text_detector(detector: AITextDetector | None) -> None:
    global _detector
    with _detector_lock:
        _detector = detector
