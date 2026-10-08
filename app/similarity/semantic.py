"""
Semantic code similarity with Microsoft's UniXcoder (``microsoft/unixcoder-base``).

The winnowing fingerprints in ``core.py`` catch literal and lightly
renamed copies, but a submission that was rewritten -- sections
reordered, loops restructured, helpers inlined -- can share very few
k-grams with its source while still implementing the same logic. This
module adds a second, independent signal for that case:

  1. Each submission's code is normalized (comments stripped,
     identifiers anonymized, whitespace collapsed -- see
     ``normalize_code``) and split into overlapping token windows
     that fit UniXcoder's input size, so long files are covered in
     full instead of silently truncated to the first 512 tokens.
  2. Every chunk is encoded ONCE per submission (batched, CPU-friendly)
     into an L2-normalized mean-pooled vector, using UniXcoder's
     ``<encoder-only>`` input format. Results are cached by content
     hash, so re-running a check never re-encodes an unchanged
     submission.
  3. A pair's score is a symmetric best-match average over chunk
     cosine similarities (each chunk of A matched to its closest chunk
     of B and vice versa, weighted by chunk length) -- independent of
     the order sections appear in, which is exactly what a reordered
     copy changes.

The semantic score is EVIDENCE FOR HUMAN REVIEW, never proof of
copying: two students independently solving the same assignment will
legitimately write semantically similar code. That's why
``apply_semantic_signal`` only raises a "review" flag when the score is
both high in absolute terms and an outlier relative to the rest of the
cohort's pairs (see ``SemanticThresholds``), and why token-based flags
remain the only "high" ones.

If the model can't be loaded (no network on first run, missing
``torch``/``transformers``, disabled via ``SEMANTIC_SIMILARITY=0``) or
inference fails, every function here degrades to "semantic analysis
unavailable" and the fingerprint/Jaccard/containment results are
returned unchanged.
"""

from __future__ import annotations

import builtins
import hashlib
import keyword
import logging
import os
import re
import statistics
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .core import _GENERIC_KEYWORDS, PairResult

log = logging.getLogger(__name__)

MODEL_NAME = "microsoft/unixcoder-base"

# UniXcoder's encoder-only input is [CLS] <encoder-only> [SEP] code [SEP].
_SPECIAL_TOKENS = 4
MAX_SEQ_LEN = 512
CHUNK_TOKENS = MAX_SEQ_LEN - _SPECIAL_TOKENS
CHUNK_OVERLAP = 64
# Submissions with less normalized code than this have too little to
# say anything meaningful semantically (a few lines of boilerplate
# embed close to almost anything).
MIN_CODE_TOKENS = 16


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

_HASH_COMMENT_LANGS = {".py", ".rb"}
_STRING_PATTERNS = (
    r'"""[\s\S]*?"""', r"'''[\s\S]*?'''",
    r'"(?:\\.|[^"\\\n])*"', r"'(?:\\.|[^'\\\n])*'",
)
_HASH_COMMENT_RE = re.compile("|".join(
    f"(?P<s{i}>{p})" for i, p in enumerate(_STRING_PATTERNS)
) + r"|(?P<comment>#[^\n]*)")
_C_COMMENT_RE = re.compile("|".join(
    f"(?P<s{i}>{p})" for i, p in enumerate(_STRING_PATTERNS[2:] + (r"`(?:\\.|[^`\\])*`",))
) + r"|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)")


# Names that carry language/library meaning and are never anonymized.
_KEEP_NAMES = (
    set(keyword.kwlist) | set(dir(builtins)) | _GENERIC_KEYWORDS
    | {"self", "this", "super", "System", "Math", "console", "std", "cout", "cin", "printf", "main"}
)
_STRING_OR_IDENT_RE = re.compile(
    r'(?P<str>"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`)'
    r"|(?P<id>[A-Za-z_][A-Za-z0-9_]*)"
)


def anonymize_identifiers(code: str) -> str:
    """Replace user-chosen names with positional placeholders (v0, v1,
    ...), consistently within one submission. Keywords, builtins and
    ``.attribute`` names (library calls like ``.split`` or ``.append``)
    are kept, string literals are left untouched.

    Renaming is the cheapest way to disguise a copy, and on raw code
    UniXcoder's embedding is dominated by identifier vocabulary: in
    calibration, honest same-task solutions that happened to pick
    similar names outscored renamed copies. Anonymized, copies and
    rewrites separate cleanly from independent solutions."""
    mapping: dict[str, str] = {}

    def substitute(m: re.Match) -> str:
        if m.lastgroup == "str":
            return m.group()
        name = m.group()
        if name in _KEEP_NAMES or (m.start() > 0 and code[m.start() - 1] == "."):
            return name
        return mapping.setdefault(name, f"v{len(mapping)}")

    return _STRING_OR_IDENT_RE.sub(substitute, code)


def normalize_code(source: str, filename: str = "") -> str:
    """Prepare code for embedding: strip comments (keeping string
    literals intact), anonymize identifiers, collapse whitespace.
    Comments and names are the cheapest things to change when
    disguising a copy, so leaving them in would let them dominate the
    embedding over the code's actual structure."""
    pattern = _HASH_COMMENT_RE if Path(filename).suffix.lower() in _HASH_COMMENT_LANGS else _C_COMMENT_RE
    stripped = pattern.sub(lambda m: "" if m.lastgroup == "comment" else m.group(), source)
    return " ".join(anonymize_identifiers(stripped).split())


# --------------------------------------------------------------------------
# Embeddings + pair scoring
# --------------------------------------------------------------------------


@dataclass
class SubmissionEmbedding:
    """One submission's chunk vectors (rows L2-normalized) and the
    number of new tokens each chunk covers, used as its weight."""

    vectors: "object"  # numpy.ndarray, shape (n_chunks, hidden)
    weights: list[int]
    token_count: int

    @property
    def chunk_count(self) -> int:
        return len(self.weights)


def semantic_similarity(a: SubmissionEmbedding, b: SubmissionEmbedding) -> float:
    """Symmetric best-match cosine similarity between two submissions.

    For every chunk of A take its best-matching chunk of B (and vice
    versa), weight by chunk length, and average both directions. With a
    single chunk each this is plain cosine similarity; with many it
    rewards submissions whose every part has a close counterpart
    somewhere in the other, regardless of order. Clipped to [0, 1].
    """
    import numpy as np

    sims = np.asarray(a.vectors) @ np.asarray(b.vectors).T
    wa = np.asarray(a.weights, dtype=float)
    wb = np.asarray(b.weights, dtype=float)
    a_to_b = float((sims.max(axis=1) * wa).sum() / wa.sum())
    b_to_a = float((sims.max(axis=0) * wb).sum() / wb.sum())
    return max(0.0, min(1.0, (a_to_b + b_to_a) / 2))


class CodeEncoder(Protocol):
    """Anything that turns normalized submissions into embeddings.
    ``UniXcoderEncoder`` is the real one; tests inject fakes."""

    def encode_many(self, texts: list[str]) -> list[SubmissionEmbedding | None]: ...


class UniXcoderEncoder:
    """Loads ``microsoft/unixcoder-base`` once and encodes submissions
    in batches of chunks. Construction downloads the model on first use
    (cached afterwards under the Hugging Face cache directory)."""

    def __init__(self, model_name: str = MODEL_NAME, device: str = "cpu",
                 batch_size: int = 8, chunk_tokens: int = CHUNK_TOKENS,
                 overlap: int = CHUNK_OVERLAP):
        from ..model_loading import MODEL_LOAD_LOCK

        # Serialized with the MiniLM load: importing transformers from two
        # threads at once makes this import fail (see app/model_loading.py).
        with MODEL_LOAD_LOCK:
            import torch
            from transformers import AutoModel, AutoTokenizer
            from transformers.utils import logging as hf_logging

            self._torch = torch
            # The checkpoint carries an unused `position_ids` buffer that makes
            # transformers print a harmless "UNEXPECTED key" load report.
            verbosity = hf_logging.get_verbosity()
            hf_logging.set_verbosity_error()
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                self.model = AutoModel.from_pretrained(model_name)
            finally:
                hf_logging.set_verbosity(verbosity)
        self.model.to(device)
        self.model.eval()
        self.device = device
        self.batch_size = batch_size
        self.chunk_tokens = chunk_tokens
        self.stride = chunk_tokens - overlap
        self._prefix = [self.tokenizer.cls_token, "<encoder-only>", self.tokenizer.sep_token]
        self._suffix = [self.tokenizer.sep_token]

    def _chunks(self, text: str) -> tuple[list[list[str]], list[int], int]:
        """Overlapping windows over the WHOLE token stream; each window's
        weight is the number of tokens it adds beyond the previous one,
        so overlapping tokens aren't double-counted."""
        tokens = self.tokenizer.tokenize(text)
        if not tokens:
            return [], [], 0
        chunks, weights, start, covered = [], [], 0, 0
        while True:
            end = min(start + self.chunk_tokens, len(tokens))
            chunks.append(tokens[start:end])
            weights.append(end - covered)
            covered = end
            if end >= len(tokens):
                break
            start += self.stride
        return chunks, weights, len(tokens)

    def _encode_chunks(self, chunks: list[list[str]]):
        import numpy as np

        torch = self._torch
        pad_id = self.tokenizer.pad_token_id
        out = []
        for i in range(0, len(chunks), self.batch_size):
            batch = [
                self.tokenizer.convert_tokens_to_ids(self._prefix + c + self._suffix)
                for c in chunks[i:i + self.batch_size]
            ]
            width = max(len(ids) for ids in batch)
            ids = torch.tensor([b + [pad_id] * (width - len(b)) for b in batch], device=self.device)
            mask = ids.ne(pad_id)
            with torch.inference_mode():
                hidden = self.model(input_ids=ids, attention_mask=mask).last_hidden_state
            pooled = (hidden * mask.unsqueeze(-1)).sum(1) / mask.sum(-1, keepdim=True)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(pooled.cpu().numpy())
        return np.concatenate(out, axis=0)

    def encode_many(self, texts: list[str]) -> list[SubmissionEmbedding | None]:
        # Chunk everything first, then run all chunks of all submissions
        # through the model in shared batches.
        import numpy as np

        plans = [self._chunks(t) for t in texts]
        all_chunks = [c for chunks, _, _ in plans for c in chunks]
        vectors = self._encode_chunks(all_chunks) if all_chunks else np.zeros((0, 0))
        results: list[SubmissionEmbedding | None] = []
        offset = 0
        for chunks, weights, token_count in plans:
            if not chunks:
                results.append(None)
                continue
            results.append(SubmissionEmbedding(
                vectors=vectors[offset:offset + len(chunks)], weights=weights, token_count=token_count,
            ))
            offset += len(chunks)
        return results


# --------------------------------------------------------------------------
# Service: load once, cache embeddings, never break the caller
# --------------------------------------------------------------------------


@dataclass
class SemanticBatch:
    """Result of embedding one cohort of submissions."""

    status: str  # "ok" | "unavailable" | "disabled"
    embeddings: dict[str, SubmissionEmbedding] = field(default_factory=dict)
    skipped_too_small: list[str] = field(default_factory=list)
    encoded: int = 0  # submissions actually run through the model this call
    cache_hits: int = 0
    warning: str | None = None


def _semantic_enabled() -> bool:
    return os.environ.get("SEMANTIC_SIMILARITY", "1").strip().lower() not in {"0", "false", "no", "off"}


class SemanticSimilarityService:
    """Process-wide owner of the UniXcoder model.

    The model is loaded at most once (``load`` is thread-safe and
    idempotent; ``preload_in_background`` lets the app start serving
    while the first download happens). Embeddings are cached in an LRU
    keyed by a hash of the normalized code, so the same submission is
    never encoded twice -- within one check or across repeated checks.
    """

    def __init__(self, encoder_factory: Callable[[], CodeEncoder] | None = None,
                 cache_size: int = 1024, min_tokens: int = MIN_CODE_TOKENS,
                 enabled: bool | None = None):
        self._factory = encoder_factory or UniXcoderEncoder
        self._encoder: CodeEncoder | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, SubmissionEmbedding] = OrderedDict()
        self._cache_size = cache_size
        self.min_tokens = min_tokens
        self.enabled = _semantic_enabled() if enabled is None else enabled
        self.status = "not_loaded" if self.enabled else "disabled"  # | ready | unavailable
        self.error: str | None = None

    def load(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            if self._encoder is not None:
                return True
            if self.status == "unavailable":
                return False
            try:
                self._encoder = self._factory()
                self.status = "ready"
                return True
            except Exception as exc:  # ImportError, network/download errors, OOM...
                self.status = "unavailable"
                self.error = f"{exc.__class__.__name__}: {exc}"
                log.warning("UniXcoder semantic similarity unavailable: %s", self.error)
                return False

    def preload_in_background(self) -> threading.Thread | None:
        if not self.enabled:
            return None
        thread = threading.Thread(target=self.load, name="unixcoder-preload", daemon=True)
        thread.start()
        return thread

    def retry(self) -> None:
        """Forget a previous load failure so the next call tries again
        (e.g. after network access is restored)."""
        with self._lock:
            if self._encoder is None:
                self.status, self.error = "not_loaded", None

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(f"{MODEL_NAME}|{CHUNK_TOKENS}|{CHUNK_OVERLAP}|{text}".encode()).hexdigest()

    def embed_submissions(self, sources: dict[str, str]) -> SemanticBatch:
        """Embed each submission's normalized code once. ``sources``
        maps submission id -> normalized code. Never raises."""
        if not self.load():
            if self.status == "disabled":
                return SemanticBatch(status="disabled",
                                     warning="Semantic similarity is disabled on this server (SEMANTIC_SIMILARITY=0).")
            return SemanticBatch(status="unavailable", warning=(
                "Semantic similarity (UniXcoder) is unavailable -- the model could not be loaded "
                f"({self.error}). Token-based results below are unaffected."))

        batch = SemanticBatch(status="ok")
        pending: dict[str, str] = {}
        for sid, text in sources.items():
            if not text.strip():
                batch.skipped_too_small.append(sid)
                continue
            key = self._key(text)
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
            if cached is not None:
                batch.embeddings[sid] = cached
                batch.cache_hits += 1
            else:
                pending[sid] = text

        if pending:
            ids = list(pending)
            try:
                results = self._encoder.encode_many([pending[i] for i in ids])
            except Exception as exc:
                log.warning("UniXcoder inference failed: %s", exc)
                batch.status = "unavailable"
                batch.embeddings = {}
                batch.warning = (f"Semantic similarity (UniXcoder) failed during inference "
                                 f"({exc.__class__.__name__}: {exc}). Token-based results below are unaffected.")
                return batch
            for sid, emb in zip(ids, results):
                if emb is None or emb.token_count < self.min_tokens:
                    batch.skipped_too_small.append(sid)
                    continue
                batch.embeddings[sid] = emb
                batch.encoded += 1
                with self._lock:
                    self._cache[self._key(pending[sid])] = emb
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
        return batch


_service: SemanticSimilarityService | None = None
_service_lock = threading.Lock()


def get_semantic_service() -> SemanticSimilarityService:
    global _service
    with _service_lock:
        if _service is None:
            _service = SemanticSimilarityService()
        return _service


def set_semantic_service(service: SemanticSimilarityService | None) -> None:
    """Swap the process-wide service (tests use this to inject a fake encoder)."""
    global _service
    with _service_lock:
        _service = service


# --------------------------------------------------------------------------
# Combining the semantic signal with the token-based result
# --------------------------------------------------------------------------


@dataclass
class SemanticThresholds:
    """Calibrated by hand against tests/semantic_samples.py plus five
    independently written solutions to the same task (anonymized
    identifiers, symmetric best-match score):

        renamed / restructured copies        0.82 - 0.91
        independent same-task solutions      median 0.68, max 0.78
        unrelated programs                   0.27 - 0.39

    That's a small sample, so treat these as starting values and
    re-check them against a real cohort before relying on them."""

    # Absolute floor: below this a pair is never semantically flagged.
    review: float = 0.80
    # Cohort-relative bar (only used with >= min_cohort_pairs pairs): a
    # pair must ALSO sit this many robust standard deviations (MAD-based)
    # above the cohort median. Everyone in a class solves the same
    # problem, so a fairly high raw score is normal; an unusually high
    # one relative to classmates is what's worth a look.
    outlier_z: float = 2.0
    min_cohort_pairs: int = 10


def needs_semantic(pair: PairResult) -> bool:
    """A pair the token comparison already flags is conclusive on its
    own; every other pair is where a rewritten copy could hide."""
    return not pair.token_flagged


def submissions_needing_semantic(pairs: Iterable[PairResult]) -> set[str]:
    ids: set[str] = set()
    for p in pairs:
        if needs_semantic(p):
            ids.update((p.submission_a, p.submission_b))
    return ids


def apply_semantic_signal(pairs: list[PairResult], embeddings: dict[str, SubmissionEmbedding],
                          thresholds: SemanticThresholds | None = None) -> dict:
    """Fill ``semantic_similarity`` and the combined flag on every pair
    whose two submissions both have embeddings (cosine on cached
    vectors -- no model inference happens here). Returns cohort stats
    for display. Pairs keep their token-based metrics untouched."""
    thresholds = thresholds or SemanticThresholds()
    for p in pairs:
        a, b = embeddings.get(p.submission_a), embeddings.get(p.submission_b)
        if a is not None and b is not None:
            p.semantic_similarity = round(semantic_similarity(a, b), 4)

    scores = [p.semantic_similarity for p in pairs if p.semantic_similarity is not None]
    median = statistics.median(scores) if scores else None
    mad = statistics.median(abs(s - median) for s in scores) if scores else None
    use_cohort = len(scores) >= thresholds.min_cohort_pairs
    # 1.4826 * MAD estimates the standard deviation for normal data;
    # floor it so a near-identical cohort doesn't make every pair an outlier.
    robust_sd = max(1.4826 * mad, 0.02) if use_cohort else None
    cohort_bar = (median + thresholds.outlier_z * robust_sd) if use_cohort else None
    bar = max(thresholds.review, cohort_bar) if cohort_bar is not None else thresholds.review

    for p in pairs:
        s = p.semantic_similarity
        if p.token_flagged:
            p.flag_level = "high"
            p.flag_reason = "High token/fingerprint overlap"
            if s is not None and s >= thresholds.review:
                p.flag_reason += " and high semantic similarity"
        elif s is not None and s >= bar:
            p.flag_level = "review"
            p.flag_reason = "High semantic similarity despite low token overlap"
            if use_cohort:
                p.flag_reason += f" (cohort median {median:.0%})"
        else:
            p.flag_level = None
            p.flag_reason = None

    return {
        "semantic_pairs_compared": len(scores),
        "cohort_median": round(median, 4) if median is not None else None,
        "review_threshold": round(bar, 4),
    }
