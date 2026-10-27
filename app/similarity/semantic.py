"""
Semantic code similarity with Microsoft's UniXcoder (``microsoft/unixcoder-base-nine``).

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
     hash -- in memory, and on disk (see ``SemanticSimilarityService``) so
     a server restart does not pay for them again -- so re-running a check
     never re-encodes an unchanged submission.
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
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .core import _GENERIC_KEYWORDS, PairResult
from .python_cleanup import strip_python_dead_code
from .ts_cleanup import LANGUAGE_BY_EXTENSION, strip_dead_code

log = logging.getLogger(__name__)

# Bump when the on-disk layout of a cached embedding changes: old files then
# stop matching (the version is part of every cache key) and age out by size.
CACHE_FORMAT = 1
DEFAULT_CACHE_MAX_BYTES = 500 * 1024 * 1024
_MISSING = object()

# The nine-language UniXcoder (Python, Java, JavaScript, PHP, Ruby, Go, C,
# C++, C#), pinned to one revision so a re-download can never silently change
# the model the review thresholds were calibrated with.
MODEL_NAME = "microsoft/unixcoder-base-nine"
MODEL_REVISION = "5f0dc256eb0904af496d427451da5d7f90261676"

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


# `.name = ...` (not `==`): a field the submission itself assigns.
_FIELD_ASSIGN_RE = re.compile(r"\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")


def anonymize_identifiers(code: str) -> str:
    """Replace user-chosen names with positional placeholders (v0, v1,
    ...), consistently within one submission. Keywords, builtins and
    library attributes (``.split``, ``.append``) are kept, string
    literals are left untouched.

    Renaming is the cheapest way to disguise a copy, and on raw code
    UniXcoder's embedding is dominated by identifier vocabulary: in
    calibration, honest same-task solutions that happened to pick
    similar names outscored renamed copies. Anonymized, copies and
    rewrites separate cleanly from independent solutions.

    Attribute names are anonymized too when the submission defines them:
    assigned as ``.name =`` or used as a plain name somewhere (a declared
    field or method). Keeping them let renamed fields (``self.stock`` ->
    ``self.inventory``) decide the score once everything else was
    anonymized (tests/unixcoder_renaming).

    Numbered placeholders were kept deliberately. A single shared
    placeholder stops one inserted variable from renumbering every later
    name, and scored better on the small tests/unixcoder_* programs, but on
    the realistic samples in tests/semantic_samples.py it spread honest
    same-task scores out, which raised the cohort-outlier bar above a
    restructured copy and dropped a renamed C copy below 0.80."""

    def is_attribute(m: re.Match) -> bool:
        return m.start() > 0 and code[m.start() - 1] == "."

    user_names = {
        m.group() for m in _STRING_OR_IDENT_RE.finditer(code)
        if m.lastgroup == "id" and m.group() not in _KEEP_NAMES and not is_attribute(m)
    }
    user_names |= {n for n in _FIELD_ASSIGN_RE.findall(code) if n not in _KEEP_NAMES}
    mapping: dict[str, str] = {}

    def substitute(m: re.Match) -> str:
        if m.lastgroup == "str":
            return m.group()
        name = m.group()
        if name in _KEEP_NAMES or (is_attribute(m) and name not in user_names):
            return name
        return mapping.setdefault(name, f"v{len(mapping)}")

    return _STRING_OR_IDENT_RE.sub(substitute, code)


def normalize_code(source: str, filename: str = "", external_names: set[str] | None = None) -> str:
    """Prepare code for embedding: strip comments (keeping string
    literals intact), anonymize identifiers, collapse whitespace.
    Comments and names are the cheapest things to change when
    disguising a copy, so leaving them in would let them dominate the
    embedding over the code's actual structure.

    Python files first lose code that does nothing (unused variables and
    imports, dead branches, unreachable statements; see python_cleanup):
    otherwise one inserted junk variable renumbers every later placeholder
    and an exact copy scores like different code. `external_names`: the
    names used by the submission's other files (see python_cleanup)."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".py":
        source = strip_python_dead_code(source, external_names)
    elif suffix in LANGUAGE_BY_EXTENSION:  # Java, JavaScript (tree-sitter; see ts_cleanup)
        source = strip_dead_code(source, LANGUAGE_BY_EXTENSION[suffix], external_names)
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


class InvalidEmbeddingError(ValueError):
    """An embedding that can't be compared (NaN/inf, zero-norm, bad weights...)."""


def _validate_embedding(emb: SubmissionEmbedding, label: str) -> None:
    """Reject input that would otherwise produce a meaningless score. Without
    this, NaN or infinite vectors and zero weights came out as similarity 1.0
    ("identical"), because the final clip turns NaN into 1.0."""
    import numpy as np

    vectors = np.asarray(emb.vectors, dtype=float)
    weights = np.asarray(emb.weights, dtype=float)
    if vectors.ndim != 2 or vectors.shape[0] == 0 or vectors.shape[1] == 0:
        raise InvalidEmbeddingError(f"embedding {label} has no vectors (shape {vectors.shape})")
    if not np.isfinite(vectors).all():
        raise InvalidEmbeddingError(f"embedding {label} contains NaN or infinite values")
    if (np.linalg.norm(vectors, axis=1) == 0).any():
        raise InvalidEmbeddingError(f"embedding {label} has a zero-norm vector; cosine similarity is undefined")
    if weights.shape != (vectors.shape[0],):
        raise InvalidEmbeddingError(
            f"embedding {label} has {weights.size} weight(s) for {vectors.shape[0]} vector(s)")
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise InvalidEmbeddingError(f"embedding {label} weights must be finite and greater than 0: {emb.weights}")


def semantic_similarity(a: SubmissionEmbedding, b: SubmissionEmbedding) -> float:
    """Symmetric best-match cosine similarity between two submissions.

    For every chunk of A take its best-matching chunk of B (and vice
    versa), weight by chunk length, and average both directions. With a
    single chunk each this is plain cosine similarity; with many it
    rewards submissions whose every part has a close counterpart
    somewhere in the other, regardless of order. Clipped to [0, 1].

    Raises InvalidEmbeddingError for input that can't be compared.
    """
    import numpy as np

    _validate_embedding(a, "A")
    _validate_embedding(b, "B")
    if np.asarray(a.vectors).shape[1] != np.asarray(b.vectors).shape[1]:
        raise InvalidEmbeddingError(
            f"embeddings have different dimensions ({np.asarray(a.vectors).shape[1]} vs "
            f"{np.asarray(b.vectors).shape[1]})")
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
    """Loads ``microsoft/unixcoder-base-nine`` once and encodes submissions
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
                revision = MODEL_REVISION if model_name == MODEL_NAME else None
                self.tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
                self.model = AutoModel.from_pretrained(model_name, revision=revision)
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
    while the first download happens). Embeddings are cached by a hash
    of the normalized code, so the same submission is never encoded
    twice -- within one check, across repeated checks, and (with a
    ``cache_dir``) across server restarts:

      1. an in-memory LRU, then
      2. one ``.npz`` file per submission in ``cache_dir``, written
         atomically and pruned oldest-first to ``cache_max_bytes``.

    The cache key covers the model revision, the chunking parameters and a
    format version, so nothing stale is ever read after any of them change.
    The model is only loaded when something is actually missing, and only
    one thread at a time runs inference: when several students check at the
    same moment, the first encodes the class and the rest read its results
    instead of every one of them encoding it again.

    A service built without ``cache_dir`` (tests, fakes) is memory-only;
    ``get_semantic_service()`` gives the real one a directory.
    """

    def __init__(self, encoder_factory: Callable[[], CodeEncoder] | None = None,
                 cache_size: int = 1024, min_tokens: int = MIN_CODE_TOKENS,
                 enabled: bool | None = None, cache_dir: Path | str | None = None,
                 cache_max_bytes: int = DEFAULT_CACHE_MAX_BYTES):
        self._factory = encoder_factory or UniXcoderEncoder
        self._encoder: CodeEncoder | None = None
        self._lock = threading.Lock()          # guards the in-memory LRU and load state; held only briefly
        self._encode_lock = threading.Lock()   # one inference pass at a time; never taken while holding _lock
        self._cache: OrderedDict[str, SubmissionEmbedding | None] = OrderedDict()
        self._cache_size = cache_size
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._cache_max_bytes = cache_max_bytes
        self.min_tokens = min_tokens
        self.enabled = _semantic_enabled() if enabled is None else enabled
        self.status = "not_loaded" if self.enabled else "disabled"  # | ready | unavailable
        self.error: str | None = None
        if self._cache_dir is not None:
            self._prune_disk_cache()

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
        return hashlib.sha256(
            f"{CACHE_FORMAT}|{MODEL_NAME}|{MODEL_REVISION}|{CHUNK_TOKENS}|{CHUNK_OVERLAP}|{text}".encode()
        ).hexdigest()

    # ---- the disk cache (best effort: any failure just means a cache miss) ----

    def _disk_path(self, key: str) -> Path:
        # 32 hex characters (128 bits of the SHA-256) keep the file name short: with the full 64
        # a deeply nested project folder can pass Windows' 260-character path limit and every write fails.
        return self._cache_dir / f"{key[:32]}.npz"

    def _disk_get(self, key: str):
        """(embedding or None, True) when stored, _MISSING when not. A damaged
        or invalid file is deleted and reported as missing."""
        if self._cache_dir is None:
            return _MISSING
        path = self._disk_path(key)
        try:
            import numpy as np

            with np.load(path, allow_pickle=False) as stored:  # closed promptly: an open npz locks the file on Windows
                if "empty" in stored.files:
                    result = None
                else:
                    result = SubmissionEmbedding(vectors=stored["vectors"], weights=[int(w) for w in stored["weights"]],
                                                 token_count=int(stored["token_count"]))
            if result is not None:
                _validate_embedding(result, key[:8])
            try:
                os.utime(path)  # a hit keeps the file young for oldest-first pruning
            except OSError:
                pass
            return result
        except FileNotFoundError:
            return _MISSING
        except Exception as exc:
            log.warning("Ignoring unreadable semantic cache file %s (%s: %s)", path.name, exc.__class__.__name__, exc)
            try:
                path.unlink()
            except OSError:
                pass
            return _MISSING

    def _disk_put(self, key: str, emb: SubmissionEmbedding | None) -> None:
        if self._cache_dir is None:
            return
        tmp_name = None
        try:
            import numpy as np

            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._cache_dir, suffix=".tmp", delete=False) as tmp:
                tmp_name = tmp.name
                if emb is None:
                    np.savez(tmp, empty=np.array(1))
                else:
                    np.savez(tmp, vectors=np.asarray(emb.vectors), weights=np.asarray(emb.weights, dtype=np.int64),
                             token_count=np.array(int(emb.token_count)))
            os.replace(tmp_name, self._disk_path(key))  # atomic: a reader never sees half a file
            tmp_name = None
        except Exception as exc:  # disk full, permissions, a reader holding the file open on Windows...
            log.warning("Could not write the semantic cache (%s: %s); continuing without it", exc.__class__.__name__, exc)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def _prune_disk_cache(self) -> None:
        """Delete the oldest cached files until the folder fits the byte cap
        (and any leftover temp file from a crashed write)."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            entries = []
            for p in self._cache_dir.iterdir():
                try:
                    st = p.stat()
                except OSError:
                    continue
                if p.suffix == ".tmp":
                    if time.time() - st.st_mtime > 3600:
                        p.unlink(missing_ok=True)
                elif p.suffix == ".npz":
                    entries.append((st.st_mtime, st.st_size, p))
            total = sum(size for _, size, _ in entries)
            for _, size, p in sorted(entries):
                if total <= self._cache_max_bytes:
                    break
                try:
                    p.unlink()
                    total -= size
                except OSError:
                    pass
        except Exception as exc:
            log.warning("Could not prune the semantic cache (%s: %s)", exc.__class__.__name__, exc)

    # ---- lookups ------------------------------------------------------------

    def _lookup(self, key: str):
        """Memory, then disk. Returns the cached value (None = stored "nothing to
        embed") or _MISSING."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        found = self._disk_get(key)
        if found is not _MISSING:
            self._remember(key, found)
        return found

    def _remember(self, key: str, emb: SubmissionEmbedding | None) -> None:
        with self._lock:
            self._cache[key] = emb
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def _place(self, batch: SemanticBatch, sid: str, emb: SubmissionEmbedding | None, fresh: bool) -> None:
        """Put one result in the batch. Everything is cached as encoded and judged on
        the way out, so a changed ``min_tokens`` takes effect without re-encoding."""
        if emb is None or emb.token_count < self.min_tokens:
            batch.skipped_too_small.append(sid)
            return
        batch.embeddings[sid] = emb
        if fresh:
            batch.encoded += 1
        else:
            batch.cache_hits += 1

    def embed_submissions(self, sources: dict[str, str]) -> SemanticBatch:
        """Embed each submission's normalized code once. ``sources``
        maps submission id -> normalized code. Never raises."""
        if not self.enabled:
            return SemanticBatch(status="disabled",
                                 warning="Semantic similarity is disabled on this server (SEMANTIC_SIMILARITY=0).")

        batch = SemanticBatch(status="ok")
        keys: dict[str, str] = {}
        pending: dict[str, str] = {}
        for sid, text in sources.items():
            if not text.strip():
                batch.skipped_too_small.append(sid)
                continue
            keys[sid] = self._key(text)
            found = self._lookup(keys[sid])
            if found is _MISSING:
                pending[sid] = text
            else:
                self._place(batch, sid, found, fresh=False)
        if not pending:
            return batch  # everything was cached: the model is not even loaded

        if not self.load():
            return SemanticBatch(status="unavailable", warning=(
                "Semantic similarity (UniXcoder) is unavailable -- the model could not be loaded "
                f"({self.error}). Token-based results below are unaffected."))

        with self._encode_lock:
            # Another thread may have finished some of these while we waited: read, don't redo.
            todo: dict[str, str] = {}
            for sid, text in pending.items():
                found = self._lookup(keys[sid])
                if found is _MISSING:
                    todo[sid] = text
                else:
                    self._place(batch, sid, found, fresh=False)
            if todo:
                ids = list(todo)
                try:
                    results = self._encoder.encode_many([todo[i] for i in ids])
                except Exception as exc:
                    log.warning("UniXcoder inference failed: %s", exc)
                    batch.status = "unavailable"
                    batch.embeddings = {}
                    batch.warning = (f"Semantic similarity (UniXcoder) failed during inference "
                                     f"({exc.__class__.__name__}: {exc}). Token-based results below are unaffected.")
                    return batch
                for sid, emb in zip(ids, results):
                    self._remember(keys[sid], emb)
                    self._disk_put(keys[sid], emb)
                    self._place(batch, sid, emb, fresh=True)
        return batch


_service: SemanticSimilarityService | None = None
_service_lock = threading.Lock()


def default_cache_dir() -> Path | None:
    """Where the real service keeps embeddings between restarts: ``cache/unixcoder``
    next to the database (it follows PORTAL_DATA_DIR), or SEMANTIC_CACHE_DIR; set
    that to "off" to keep everything in memory."""
    raw = os.environ.get("SEMANTIC_CACHE_DIR")
    if raw is not None:
        return None if raw.strip().lower() in {"", "0", "off", "false", "no", "none"} else Path(raw)
    from ..db import BASE_DIR  # imported here: it creates the uploads folder, which this module otherwise never needs

    return BASE_DIR / "cache" / "unixcoder"


def _cache_max_bytes() -> int:
    try:
        return int(float(os.environ.get("SEMANTIC_CACHE_MAX_MB", "")) * 1024 * 1024)
    except ValueError:
        return DEFAULT_CACHE_MAX_BYTES


def get_semantic_service() -> SemanticSimilarityService:
    global _service
    with _service_lock:
        if _service is None:
            _service = SemanticSimilarityService(cache_dir=default_cache_dir(), cache_max_bytes=_cache_max_bytes())
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
