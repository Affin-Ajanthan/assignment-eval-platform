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

import hashlib
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


def _python_tokens(source: str) -> list[tuple[str, int]]:
    """Tokenize Python with the stdlib tokenizer; fold identifiers,
    numbers and strings down to generic placeholders so renamed
    variables and changed literals still match structurally.
    Each token comes with the source line it starts on."""
    tokens: list[tuple[str, int]] = []
    try:
        reader = io.StringIO(source).readline
        for tok in py_tokenize.generate_tokens(reader):
            tok_type, tok_string, line = tok.type, tok.string, tok.start[0]
            if tok_type in (py_tokenize.COMMENT, py_tokenize.NL,
                             py_tokenize.NEWLINE, py_tokenize.INDENT,
                             py_tokenize.DEDENT, py_tokenize.ENCODING,
                             py_tokenize.ENDMARKER):
                continue
            if tok_type == py_tokenize.NAME:
                tokens.append((tok_string if tok_string in _PY_KEEP_KEYWORDS
                               else "ID", line))
            elif tok_type == py_tokenize.NUMBER:
                tokens.append(("NUM", line))
            elif tok_type == py_tokenize.STRING:
                tokens.append(("STR", line))
            else:
                tokens.append((tok_string, line))
    except (py_tokenize.TokenError, IndentationError, SyntaxError):
        return _generic_tokens(source)
    return tokens


def _generic_tokens(source: str) -> list[tuple[str, int]]:
    """Regex-based fallback tokenizer for languages without a tree-sitter
    parser (TypeScript, Kotlin, ...) or when tree-sitter isn't installed.
    Strips comments, folds identifiers/numbers/
    strings to placeholders, keeps a small shared keyword set intact.
    Each token comes with the source line it starts on."""
    tokens: list[tuple[str, int]] = []
    line, last = 1, 0
    for match in _GENERIC_TOKEN_RE.finditer(source):
        line += source.count("\n", last, match.start())
        last = match.start()
        kind = match.lastgroup
        text = match.group()
        if kind in ("comment_line", "comment_block"):
            continue
        if kind == "string":
            tokens.append(("STR", line))
        elif kind == "number":
            tokens.append(("NUM", line))
        elif kind == "ident":
            tokens.append((text if text in _GENERIC_KEYWORDS else "ID", line))
        else:  # operator / punctuation
            if text.strip():
                tokens.append((text, line))
    return tokens


_IDENT_TEXT_RE = re.compile(r"[$@]{0,2}[A-Za-z_][A-Za-z0-9_]*[?!]?")
# Named leaves that look like a name but are part of the language: kept as text.
_TS_KEYWORD_LEAVES = {
    "primitive_type", "integral_type", "floating_point_type", "boolean_type", "void_type",
    "predefined_type", "implicit_type", "sized_type_specifier", "cast_type", "true", "false", "null",
    "null_literal", "nil", "this", "self", "super", "undefined", "boolean", "iota",
}
_TS_CHAR_LITERALS = {"char_literal", "character_literal", "rune_literal"}


def _tree_sitter_tokens(source: str, language: str) -> list[tuple[str, int]] | None:
    """Tokens of `source` from its tree-sitter parse (the parsers ts_cleanup
    uses), folded like the other tokenizers: names -> ID, numbers -> NUM,
    strings -> STR, comments dropped, keywords and operators kept. Unlike
    the regex, PHP's ``$name``, Go's and JavaScript's backtick strings, C's
    ``#include`` and every language's own keywords are read correctly.
    A name is recognised by its text rather than its node type, so a grammar's
    name node this list doesn't know still folds to ID. Code with syntax
    errors is still tokenized (tree-sitter keeps the parts it can read), so a
    copy with one broken line still matches. None when no parser is available."""
    from .ts_cleanup import _parser

    parser = _parser(language)
    if parser is None:
        return None
    root = parser.parse(source.encode("utf-8")).root_node
    tokens: list[tuple[str, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        kind = node.type
        if node.is_missing or "comment" in kind:
            continue
        if node.is_named and ("string" in kind or kind in _TS_CHAR_LITERALS or kind in ("heredoc", "nowdoc")):
            tokens.append(("STR", node.start_point[0] + 1))  # the whole literal, interpolations included
            continue
        if node.child_count:
            # A contextual keyword used as a name (C#'s `var file = ...`) is an
            # identifier node wrapping a keyword token: still a name.
            if node.is_named and ("identifier" in kind or kind == "name") and \
                    _IDENT_TEXT_RE.fullmatch(node.text.decode("utf-8", errors="replace")):
                tokens.append(("ID", node.start_point[0] + 1))
                continue
            stack.extend(reversed(node.children))
            continue
        text = node.text.decode("utf-8", errors="replace").strip()
        if not text:
            continue  # e.g. Go's newline statement terminators
        line = node.start_point[0] + 1
        if not node.is_named:
            tokens.append((text, line))  # keyword or operator
        elif text[0].isdigit() or (text[0] == "." and text[1:2].isdigit()):
            tokens.append(("NUM", line))
        elif kind in _TS_KEYWORD_LEAVES:
            tokens.append((text, line))
        elif _IDENT_TEXT_RE.fullmatch(text):
            tokens.append(("ID", line))
        else:
            tokens.append((kind, line))  # e.g. PHP's inline HTML, an escape sequence
    return tokens


def _normalize_python(source: str) -> list[str]:
    return [t for t, _ in _python_tokens(source)]


def _normalize_generic(source: str) -> list[str]:
    return [t for t, _ in _generic_tokens(source)]


_EXT_LANGUAGE = {
    ".py": "python",
}


def normalize_tokens_with_lines(source: str, filename: str = "") -> list[tuple[str, int]]:
    """normalize_tokens, with the source line each token starts on."""
    from .ts_cleanup import LANGUAGE_BY_EXTENSION

    ext = Path(filename).suffix.lower()
    if _EXT_LANGUAGE.get(ext) == "python":
        return _python_tokens(source)
    if ext in LANGUAGE_BY_EXTENSION:
        tokens = _tree_sitter_tokens(source, LANGUAGE_BY_EXTENSION[ext])
        if tokens is not None:
            return tokens
    return _generic_tokens(source)


def normalize_tokens(source: str, filename: str = "") -> list[str]:
    """Dispatch to a language-specific normalizer by file extension."""
    return [t for t, _ in normalize_tokens_with_lines(source, filename)]


# --------------------------------------------------------------------------
# Winnowing fingerprints (Schleimer, Wilkerson & Aiken, 2003)
# --------------------------------------------------------------------------

def _stable_hash(gram: list[str]) -> int:
    """64-bit hash that is the same in every process. Python's built-in
    ``hash()`` of strings is randomized per process (PYTHONHASHSEED), which
    changes which k-grams winnowing selects and so made the same two files
    score differently from one run to the next."""
    digest = hashlib.blake2b("".join(gram).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _kgram_hashes(tokens: list[str], k: int) -> list[int]:
    if len(tokens) < k:
        return [_stable_hash(tokens)] if tokens else []
    return [_stable_hash(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]


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


def matched_line_ranges(source: str, filename: str, shared: set[int], k: int = 5) -> list[tuple[int, int]]:
    """Line ranges of ``source`` covered by a k-gram whose fingerprint is in
    ``shared`` (fingerprints this file has in common with other submissions),
    merged where they touch. Uses the same tokens and hashes as
    fingerprint_source, so a range is exactly where a shared fingerprint came from."""
    if not shared:
        return []
    tokens = normalize_tokens_with_lines(source, filename)
    words = [t for t, _ in tokens]
    lines = [ln for _, ln in tokens]
    ranges: list[tuple[int, int]] = []
    if len(words) < k:
        if words and _stable_hash(words) in shared:
            ranges.append((lines[0], lines[-1]))
    else:
        for i in range(len(words) - k + 1):
            if _stable_hash(words[i:i + k]) in shared:
                ranges.append((lines[i], lines[i + k - 1]))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_starter(fp: Fingerprint, starter: Fingerprint | None) -> Fingerprint:
    """Drop instructor starter-code fingerprints from one file's fingerprint.

    Code every student was given is not evidence of copying, but it alone
    pushes containment over the flag threshold for independent solutions.
    Only files with the starter's extension are touched: that's what makes
    both go through the same normalizer in `normalize_tokens`, so their
    hashes are comparable. `token_count` is left as-is (it describes the
    file, not the comparison)."""
    if starter is None or not starter.hashes:
        return fp
    if Path(fp.filename).suffix.lower() != Path(starter.filename).suffix.lower():
        return fp
    return Fingerprint(
        submission_id=fp.submission_id,
        filename=fp.filename,
        token_count=fp.token_count,
        hashes=fp.hashes - starter.hashes,
    )


# Fingerprints found in MORE than half of the submissions (and in at least
# COMMON_MIN_SUBMISSIONS of them) are what the task makes everyone write --
# menu loops, input helpers, the brief pasted into every report -- rather than
# copying. One rule for code (similarity_runs.remove_common_code) and reports
# (report_similarity.remove_common_fingerprints). "At least half" was too
# loose: in a class of 6, three students sharing their answers counted as
# "half" and hid each other.
COMMON_MIN_SUBMISSIONS = 4
COMMON_SHARE = 0.5


def common_hashes(hash_sets: list) -> set[int]:
    """The fingerprints shared by most of `hash_sets` (one set per
    submission), by the rule above; empty below COMMON_MIN_SUBMISSIONS."""
    n = len(hash_sets)
    if n < COMMON_MIN_SUBMISSIONS:
        return set()
    counts: dict[int, int] = {}
    for hashes in hash_sets:
        for h in hashes:
            counts[h] = counts.get(h, 0) + 1
    return {h for h, c in counts.items() if c > n * COMMON_SHARE and c >= COMMON_MIN_SUBMISSIONS}


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
    # Optional extra signal filled in by semantic.apply_semantic_signal;
    # None means semantic analysis wasn't run (or was unavailable) for
    # this pair, in which case the flag is the token-based one alone.
    semantic_similarity: float | None = None
    flag_level: str | None = None  # "high" (token overlap) | "review" (semantic only) | None
    flag_reason: str | None = None

    @property
    def token_flagged(self) -> bool:
        return self.jaccard >= 0.6 or self.containment >= 0.75

    @property
    def flagged(self) -> bool:
        return self.token_flagged or self.flag_level is not None


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
