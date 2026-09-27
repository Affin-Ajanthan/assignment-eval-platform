"""
Core algorithms for the pre-submission similarity checker.

Implements a MOSS/JPlag-style approach:
  1. Tokenize source code, normalizing identifiers/literals so that
     variable-renaming and minor refactors don't defeat detection.
  2. Break the normalized token stream into overlapping k-grams and
     hash each one.
  3. Winnow the hash sequence down to a compact, position-independent
     fingerprint set (Schleimer, Wilkerson & Aiken, 2003).
  4. Compare fingerprint sets pairwise with Jaccard and containment
     similarity to flag likely-copied submissions.

This is a *pre-submission self-check*: it runs fast, needs no network
access or paid API, and is meant to give students (and instructors) an
early signal, not a final verdict. See README.md for the accuracy
caveats also called out in the platform plan's Risks section.
"""

from __future__ import annotations

import io
import keyword
import re
import tokenize as py_tokenize
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Tokenization / normalization
# --------------------------------------------------------------------------

_PY_KEEP_KEYWORDS = set(keyword.kwlist)

_GENERIC_TOKEN_RE = re.compile(
    r"""
    (?P<comment_line>//.*?$|\#.*?$)                  |
    (?P<comment_block>/\*.*?\*/)                     |
    (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')  |
    (?P<number>\b\d+\.\d+\b|\b\d+\b)                 |
    (?P<ident>[A-Za-z_][A-Za-z0-9_]*)                |
    (?P<op>[^\sA-Za-z0-9_])
    """,
    re.VERBOSE | re.MULTILINE | re.DOTALL,
)

_GENERIC_KEYWORDS = {
    "if", "else", "elif", "for", "while", "do", "switch", "case", "break",
    "continue", "return", "function", "def", "class", "public", "private",
    "protected", "static", "void", "int", "float", "double", "boolean",
    "bool", "string", "String", "var", "let", "const", "new", "try",
    "catch", "finally", "throw", "throws", "import", "package", "namespace",
    "using", "include", "struct", "enum", "interface", "extends",
    "implements", "true", "false", "null", "None", "True", "False", "and",
    "or", "not", "in", "is", "lambda", "yield", "async", "await",
}


def _normalize_python(source: str) -> list[str]:
    """Tokenize Python with the stdlib tokenizer; fold identifiers,
    numbers and strings down to generic placeholders so renamed
    variables and changed literals still match structurally."""
    tokens: list[str] = []
    try:
        reader = io.StringIO(source).readline
        for tok in py_tokenize.generate_tokens(reader):
            tok_type, tok_string = tok.type, tok.string
            if tok_type in (py_tokenize.COMMENT, py_tokenize.NL,
                             py_tokenize.NEWLINE, py_tokenize.INDENT,
                             py_tokenize.DEDENT, py_tokenize.ENCODING,
                             py_tokenize.ENDMARKER):
                continue
            if tok_type == py_tokenize.NAME:
                tokens.append(tok_string if tok_string in _PY_KEEP_KEYWORDS
                              else "ID")
            elif tok_type == py_tokenize.NUMBER:
                tokens.append("NUM")
            elif tok_type == py_tokenize.STRING:
                tokens.append("STR")
            else:
                tokens.append(tok_string)
    except (py_tokenize.TokenError, IndentationError, SyntaxError):
        return _normalize_generic(source)
    return tokens


def _normalize_generic(source: str) -> list[str]:
    """Regex-based fallback tokenizer for non-Python languages (Java,
    JS/TS, C/C++, etc). Strips comments, folds identifiers/numbers/
    strings to placeholders, keeps a small shared keyword set intact."""
    tokens: list[str] = []
    for match in _GENERIC_TOKEN_RE.finditer(source):
        kind = match.lastgroup
        text = match.group()
        if kind in ("comment_line", "comment_block"):
            continue
        if kind == "string":
            tokens.append("STR")
        elif kind == "number":
            tokens.append("NUM")
        elif kind == "ident":
            tokens.append(text if text in _GENERIC_KEYWORDS else "ID")
        else:  # operator / punctuation
            if text.strip():
                tokens.append(text)
    return tokens


_EXT_LANGUAGE = {
    ".py": "python",
}


def normalize_tokens(source: str, filename: str = "") -> list[str]:
    """Dispatch to a language-specific normalizer by file extension."""
    ext = Path(filename).suffix.lower()
    if _EXT_LANGUAGE.get(ext) == "python":
        return _normalize_python(source)
    return _normalize_generic(source)


# --------------------------------------------------------------------------
# Winnowing fingerprints (Schleimer, Wilkerson & Aiken, 2003)
# --------------------------------------------------------------------------

def _kgram_hashes(tokens: list[str], k: int) -> list[int]:
    if len(tokens) < k:
        return [hash(tuple(tokens))] if tokens else []
    return [hash(tuple(tokens[i:i + k])) for i in range(len(tokens) - k + 1)]


def winnow(hashes: list[int], window_size: int) -> set[int]:
    """Select the minimum hash in every window of `window_size`
    consecutive k-gram hashes, ties broken by the rightmost occurrence.
    Guarantees any shared substring of length >= k + window_size - 1
    produces at least one shared fingerprint."""
    if not hashes:
        return set()
    if window_size <= 1:
        return set(hashes)

    selected: set[int] = set()
    last_min_index = -1
    for start in range(0, len(hashes) - window_size + 1):
        window = hashes[start:start + window_size]
        min_value = min(window)
        # rightmost index of the minimum within this window
        min_index = start + max(i for i, v in enumerate(window) if v == min_value)
        if min_index != last_min_index:
            selected.add(min_value)
            last_min_index = min_index
    return selected


@dataclass
class Fingerprint:
    submission_id: str
    filename: str
    token_count: int
    hashes: set[int] = field(default_factory=set)


def fingerprint_source(submission_id: str, filename: str, source: str,
                        k: int = 5, window_size: int = 4) -> Fingerprint:
    tokens = normalize_tokens(source, filename)
    kgram_hashes = _kgram_hashes(tokens, k)
    return Fingerprint(
        submission_id=submission_id,
        filename=filename,
        token_count=len(tokens),
        hashes=winnow(kgram_hashes, window_size),
    )


# --------------------------------------------------------------------------
# Similarity scoring
# --------------------------------------------------------------------------

def jaccard_similarity(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def containment_similarity(a: set[int], b: set[int]) -> float:
    """Fraction of the SMALLER fingerprint set that also appears in the
    other -- catches a short submission copied wholesale into a longer
    one, which Jaccard alone would understate."""
    if not a or not b:
        return 0.0
    smaller = min(len(a), len(b))
    return len(a & b) / smaller


@dataclass
class PairResult:
    submission_a: str
    submission_b: str
    jaccard: float
    containment: float
    shared_fingerprints: int

    @property
    def flagged(self) -> bool:
        return self.jaccard >= 0.6 or self.containment >= 0.75


def compare_all(fingerprints: dict[str, Fingerprint]) -> list[PairResult]:
    """All-pairs comparison across submissions (one Fingerprint per
    student, already merged across that student's files)."""
    ids = sorted(fingerprints)
    results = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            fa, fb = fingerprints[ids[i]], fingerprints[ids[j]]
            results.append(PairResult(
                submission_a=ids[i],
                submission_b=ids[j],
                jaccard=round(jaccard_similarity(fa.hashes, fb.hashes), 4),
                containment=round(containment_similarity(fa.hashes, fb.hashes), 4),
                shared_fingerprints=len(fa.hashes & fb.hashes),
            ))
    results.sort(key=lambda r: max(r.jaccard, r.containment), reverse=True)
    return results
