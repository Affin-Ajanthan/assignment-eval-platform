"""
UniXcoder basic-functionality suite (TC01-TC15) for the production encoder in
``app/similarity/semantic.py`` (model ``microsoft/unixcoder-base-nine``).

Everything goes through the production code path:
``normalize_code`` (comment stripping, identifier anonymisation, whitespace
collapsing) -> ``UniXcoderEncoder.encode_many`` (RoBERTa BPE tokenizer,
``[CLS] <encoder-only> [SEP] code [SEP]``, mean pooling, L2 normalisation)
-> ``semantic_similarity`` (chunk best-match cosine). The model is loaded
once (session fixture in conftest.py) and runs on CPU.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.similarity.core import PairResult
from app.similarity.semantic import (
    MODEL_NAME,
    MODEL_REVISION,
    InvalidEmbeddingError,
    SubmissionEmbedding,
    apply_semantic_signal,
    normalize_code,
    semantic_similarity,
)

tc = pytest.mark.tc

SAMPLES = {
    "Python": ("calc.py", 'def add(a, b):\n    """Return the sum."""\n    return a + b\n'),
    "Java": ("Calc.java", "public class Calc {\n  // sum\n  static int add(int a, int b) { return a + b; }\n}\n"),
    "JavaScript": ("calc.js", "// sum\nfunction add(a, b) {\n  return a + b;\n}\nmodule.exports = { add };\n"),
    "C": ("calc.c", "#include <stdio.h>\n/* sum */\nint add(int a, int b) { return a + b; }\n"),
    "C++": ("calc.cpp", "#include <iostream>\ntemplate <typename T> T add(T a, T b) { return a + b; }\n"),
    "C#": ("Calc.cs", "using System;\nclass Calc { static int Add(int a, int b) => a + b; }\n"),
    "Go": ("calc.go", "package calc\n\n// Add returns a + b\nfunc Add(a int, b int) int {\n\treturn a + b\n}\n"),
    "PHP": ("calc.php", "<?php\n// sum\nfunction add($a, $b) {\n    return $a + $b;\n}\n"),
    "Ruby": ("calc.rb", "# sum\ndef add(a, b)\n  a + b\nend\n"),
}
HIDDEN = 768


def embed(encoder, filename: str, source: str):
    """Production path: normalise, then encode. Returns SubmissionEmbedding or None."""
    return encoder.encode_many([normalize_code(source, filename)])[0]


def describe(emb) -> str:
    if emb is None:
        return "no embedding (None)"
    v = np.asarray(emb.vectors)
    norms = np.linalg.norm(v, axis=1)
    return (f"shape {v.shape}, {emb.token_count} tokens, {emb.chunk_count} chunk(s), "
            f"L2 norm {norms.min():.4f}-{norms.max():.4f}, finite={bool(np.isfinite(v).all())}")


def assert_valid_embedding(emb):
    assert emb is not None, "no embedding was produced"
    v = np.asarray(emb.vectors)
    assert v.ndim == 2 and v.shape[0] >= 1 and v.shape[1] == HIDDEN, f"unexpected shape {v.shape}"
    assert np.isfinite(v).all(), "embedding contains NaN or infinity"
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-4), "rows are not unit length"
    assert emb.token_count > 0 and len(emb.weights) == v.shape[0]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


@tc(id="TC01", lang="n/a", desc="Load the model", expected="RobertaModel loads on CPU in eval mode, 768-d, 12 layers")
def test_tc01_model_loads(encoder, record):
    model = encoder.model
    cfg = model.config
    record["actual"] = (f"{type(model).__name__}, revision {MODEL_REVISION[:8]}, device "
                        f"{next(model.parameters()).device}, hidden {cfg.hidden_size}, layers "
                        f"{cfg.num_hidden_layers}, {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M params, "
                        f"loaded in {encoder.load_seconds:.1f}s")
    assert MODEL_NAME == "microsoft/unixcoder-base-nine"
    assert type(model).__name__ == "RobertaModel"
    assert str(next(model.parameters()).device) == "cpu"
    assert cfg.hidden_size == HIDDEN and cfg.num_hidden_layers == 12


@tc(id="TC02", lang="n/a", desc="Load the tokenizer",
    expected="RoBERTa BPE tokenizer with <encoder-only>, CLS/SEP/PAD ids, tokenises code")
def test_tc02_tokenizer_loads(encoder, record):
    tok = encoder.tokenizer
    pieces = tok.tokenize("def add(a, b): return a + b")
    ids = tok.convert_tokens_to_ids(encoder._prefix + pieces + encoder._suffix)
    record["actual"] = (f"{type(tok).__name__}, vocab {len(tok)}, <encoder-only> id "
                        f"{tok.convert_tokens_to_ids('<encoder-only>')}, pad id {tok.pad_token_id}, "
                        f"{len(pieces)} pieces for a one-line function")
    assert "<encoder-only>" in tok.get_vocab()
    assert tok.cls_token and tok.sep_token and tok.pad_token_id is not None
    assert pieces and tok.unk_token_id not in ids
    assert encoder._prefix == [tok.cls_token, "<encoder-only>", tok.sep_token]


# --------------------------------------------------------------------------
# Embedding generation per language
# --------------------------------------------------------------------------


@tc(id="TC03", lang="Python", desc="Embed a short Python function", expected="One finite, unit-length 768-d vector")
def test_tc03_python(encoder, record):
    emb = embed(encoder, *SAMPLES["Python"])
    record["actual"] = describe(emb)
    assert_valid_embedding(emb)


@tc(id="TC04", lang="Java", desc="Embed a Java function", expected="One finite, unit-length 768-d vector")
def test_tc04_java(encoder, record):
    emb = embed(encoder, *SAMPLES["Java"])
    record["actual"] = describe(emb)
    assert_valid_embedding(emb)


@tc(id="TC05", lang="JavaScript", desc="Embed a JavaScript function", expected="One finite, unit-length 768-d vector")
def test_tc05_javascript(encoder, record):
    emb = embed(encoder, *SAMPLES["JavaScript"])
    record["actual"] = describe(emb)
    assert_valid_embedding(emb)


@tc(id="TC06", lang="C, C++, C#, Go, PHP, Ruby", desc="Embed one function in each of six more languages",
    expected="A finite, unit-length 768-d vector for every language (mechanics only, not proof of support)")
def test_tc06_other_languages(encoder, record):
    langs = ["C", "C++", "C#", "Go", "PHP", "Ruby"]
    embs = encoder.encode_many([normalize_code(SAMPLES[l][1], SAMPLES[l][0]) for l in langs])
    record["actual"] = "; ".join(f"{l}: {e.token_count} tokens" if e is not None else f"{l}: None"
                                 for l, e in zip(langs, embs))
    failures = []
    for lang, emb in zip(langs, embs):
        try:
            assert_valid_embedding(emb)
        except AssertionError as exc:
            failures.append(f"{lang}: {exc}")
    assert not failures, "; ".join(failures)


# --------------------------------------------------------------------------
# Edge-case inputs
# --------------------------------------------------------------------------


@tc(id="TC07", lang="n/a (empty file)", desc="Process an empty source file",
    expected="No exception; no embedding (None), so it is never compared")
def test_tc07_empty(encoder, record):
    emb = embed(encoder, "empty.py", "")
    record["actual"] = f"no exception; {describe(emb)}"
    assert emb is None


@tc(id="TC08", lang="n/a (whitespace)", desc="Process whitespace-only input",
    expected="No exception; no embedding (None)")
def test_tc08_whitespace(encoder, record):
    emb = embed(encoder, "blank.py", "   \n\t\n    \r\n  ")
    record["actual"] = f"no exception; {describe(emb)}"
    assert emb is None


@tc(id="TC09", lang="Python, Java", desc="Process malformed source code",
    expected="No exception; a finite embedding (the pipeline doesn't parse code)")
def test_tc09_malformed(encoder, record):
    broken = {
        "broken.py": "def broken(:\n    return [1, 2,\n  if x ==\n    print('unterminated\n",
        "Broken.java": "public class { void m( { int x = ; } } }}} /* unclosed comment",
    }
    embs = encoder.encode_many([normalize_code(src, name) for name, src in broken.items()])
    record["actual"] = "; ".join(f"{n}: {describe(e)}" for n, e in zip(broken, embs))
    for emb in embs:
        assert_valid_embedding(emb)


@tc(id="TC10", lang="Python, JavaScript", desc="Handle Unicode in identifiers, strings and comments",
    expected="No exception; finite embeddings; non-ASCII text survives normalisation")
def test_tc10_unicode(encoder, record):
    py = 'def grüße(名前):\n    # コメント\n    return f"こんにちは {名前} 😀 مرحبا"\n'
    js = "const café = (x) => `naïve ${x} — ✓ 🚀`; // ünïcödé\n"
    normalized = [normalize_code(py, "u.py"), normalize_code(js, "u.js")]
    embs = encoder.encode_many(normalized)
    record["actual"] = "; ".join(describe(e) for e in embs) + f"; kept '😀': {'😀' in normalized[0]}"
    for emb in embs:
        assert_valid_embedding(emb)
    assert "こんにちは" in normalized[0] and "😀" in normalized[0]  # string literals are kept


# --------------------------------------------------------------------------
# Determinism, validity, similarity
# --------------------------------------------------------------------------


@tc(id="TC11", lang="Python", desc="Embed the same source repeatedly",
    expected="Identical vectors every time (max abs difference <= 1e-6)")
def test_tc11_repeated(encoder, record):
    runs = [np.asarray(embed(encoder, *SAMPLES["Python"]).vectors) for _ in range(3)]
    diff = max(float(np.abs(runs[0] - r).max()) for r in runs[1:])
    record["actual"] = f"3 runs, max abs difference {diff:.2e}"
    assert diff <= 1e-6


@tc(id="TC12", lang="All 9 + malformed + Unicode", desc="Embedding values are finite",
    expected="No NaN or infinity in any embedding; all rows unit length")
def test_tc12_finite(encoder, record):
    texts = [normalize_code(src, name) for name, src in SAMPLES.values()]
    texts += [normalize_code("def broken(:\n  return [", "b.py"), normalize_code("x = '😀 名前'", "u.py")]
    embs = encoder.encode_many(texts)
    values = np.concatenate([np.asarray(e.vectors) for e in embs if e is not None])
    record["actual"] = (f"{len(embs)} inputs, {values.size} values, NaN {int(np.isnan(values).sum())}, "
                        f"inf {int(np.isinf(values).sum())}, value range {values.min():.3f}..{values.max():.3f}")
    assert all(e is not None for e in embs)
    assert np.isfinite(values).all()
    assert np.allclose(np.linalg.norm(values, axis=1), 1.0, atol=1e-4)


@tc(id="TC13", lang="Python, Java", desc="Cosine similarity on valid embeddings",
    expected="self = 1.0, symmetric, within [0, 1], equals the plain dot product for single-chunk inputs")
def test_tc13_cosine(encoder, record):
    a, b = encoder.encode_many([normalize_code(SAMPLES["Python"][1], "a.py"),
                                normalize_code(SAMPLES["Java"][1], "A.java")])
    s_aa, s_ab, s_ba = semantic_similarity(a, a), semantic_similarity(a, b), semantic_similarity(b, a)
    manual = float(np.dot(a.vectors[0], b.vectors[0]))
    record["actual"] = f"self {s_aa:.6f}, A-B {s_ab:.6f}, B-A {s_ba:.6f}, manual dot {manual:.6f}"
    assert s_aa == pytest.approx(1.0, abs=1e-5)
    assert s_ab == pytest.approx(s_ba, abs=1e-6)
    assert 0.0 <= s_ab <= 1.0
    assert s_ab == pytest.approx(min(1.0, max(0.0, manual)), abs=1e-5)


def _emb(vectors, weights=None):
    v = np.asarray(vectors, dtype=float)
    return SubmissionEmbedding(v, list(weights) if weights is not None else [10] * v.shape[0], 10 * v.shape[0])


def _unit(seed: int, rows: int = 1, dim: int = HIDDEN):
    v = np.random.default_rng(seed).normal(size=(rows, dim))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


GOOD = _emb(np.eye(1, HIDDEN))
NAN_ROW = np.eye(1, HIDDEN); NAN_ROW[0, 5] = np.nan
POS_INF_ROW = np.eye(1, HIDDEN); POS_INF_ROW[0, 5] = np.inf
NEG_INF_ROW = np.eye(1, HIDDEN); NEG_INF_ROW[0, 5] = -np.inf

INVALID_CASES = {
    "NaN value": _emb(NAN_ROW),
    "positive infinity": _emb(POS_INF_ROW),
    "negative infinity": _emb(NEG_INF_ROW),
    "zero-norm vector": _emb(np.zeros((1, HIDDEN))),
    "zero-norm chunk among valid ones": _emb(np.vstack([np.eye(1, HIDDEN), np.zeros((1, HIDDEN))])),
    "empty vectors": SubmissionEmbedding(np.zeros((0, HIDDEN)), [], 0),
    "zero weight": _emb(np.eye(1, HIDDEN), [0]),
    "negative weight": _emb(np.eye(1, HIDDEN), [-3]),
    "NaN weight": _emb(np.eye(1, HIDDEN), [float("nan")]),
    "infinite weight": _emb(np.eye(1, HIDDEN), [float("inf")]),
    "weight count mismatch": _emb(np.eye(1, HIDDEN), [5, 5]),
    "dimension mismatch (384 vs 768)": _emb(_unit(1, dim=384)),
}


@tc(id="TC14", lang="n/a (synthetic vectors)", desc="Empty or invalid embeddings handled safely",
    expected="Every invalid input raises InvalidEmbeddingError (never a score); the pipeline skips a missing "
             "embedding")
def test_tc14_invalid_embeddings(record):
    outcomes, unsafe = [], []
    for name, bad in INVALID_CASES.items():
        for args in ((bad, GOOD), (GOOD, bad)):  # invalid on either side
            try:
                value = semantic_similarity(*args)
            except InvalidEmbeddingError:
                continue
            except Exception as exc:  # some other error type is not the contract
                unsafe.append(f"{name}: raised {type(exc).__name__}, not InvalidEmbeddingError")
                break
            unsafe.append(f"{name} -> returned {value!r}")
            break
        else:
            outcomes.append(name)
    pair = PairResult("a", "b", 0.1, 0.1, 0)
    apply_semantic_signal([pair], {"a": GOOD})
    record["actual"] = (f"{len(outcomes)}/{len(INVALID_CASES)} invalid inputs rejected with InvalidEmbeddingError "
                        f"on both sides ({', '.join(outcomes)}); pipeline with a missing embedding: score "
                        f"{pair.semantic_similarity!r}")
    assert pair.semantic_similarity is None
    assert not unsafe, "; ".join(unsafe)


# ---- TC14 regression tests (fast, no model) --------------------------------


@pytest.mark.parametrize("name", list(INVALID_CASES))
def test_tc14_regression_invalid_input_raises(name):
    with pytest.raises(InvalidEmbeddingError):
        semantic_similarity(INVALID_CASES[name], GOOD)
    with pytest.raises(InvalidEmbeddingError):
        semantic_similarity(GOOD, INVALID_CASES[name])


def test_tc14_regression_error_is_a_valueerror_with_a_clear_message():
    with pytest.raises(ValueError, match="NaN or infinite"):
        semantic_similarity(INVALID_CASES["NaN value"], GOOD)
    with pytest.raises(ValueError, match="zero-norm"):
        semantic_similarity(GOOD, INVALID_CASES["zero-norm vector"])
    with pytest.raises(ValueError, match="weights must be finite and greater than 0"):
        semantic_similarity(INVALID_CASES["zero weight"], GOOD)


def _reference_similarity(a, b):
    """The calculation exactly as it was before the fix (no validation)."""
    sims = np.asarray(a.vectors) @ np.asarray(b.vectors).T
    wa = np.asarray(a.weights, dtype=float)
    wb = np.asarray(b.weights, dtype=float)
    a_to_b = float((sims.max(axis=1) * wa).sum() / wa.sum())
    b_to_a = float((sims.max(axis=0) * wb).sum() / wb.sum())
    return max(0.0, min(1.0, (a_to_b + b_to_a) / 2))


@pytest.mark.parametrize("rows_a,rows_b", [(1, 1), (1, 4), (3, 5), (6, 6)])
def test_tc14_regression_valid_inputs_unchanged(rows_a, rows_b):
    rng = np.random.default_rng(rows_a * 10 + rows_b)
    a = _emb(_unit(rows_a, rows_a), rng.integers(1, 509, rows_a))
    b = _emb(_unit(100 + rows_b, rows_b), rng.integers(1, 509, rows_b))
    assert semantic_similarity(a, b) == _reference_similarity(a, b)
    assert semantic_similarity(a, a) == pytest.approx(1.0, abs=1e-12)
    # Opposite vectors still clip to 0, as before.
    assert semantic_similarity(_emb(np.eye(1, HIDDEN)), _emb(-np.eye(1, HIDDEN))) == 0.0


@tc(id="TC15", lang="Python", desc="Evaluation mode and consistent inference",
    expected="Every module in eval mode (dropout off); inference under no-grad; identical repeated outputs")
def test_tc15_eval_mode_consistency(encoder, record):
    import torch

    model = encoder.model
    training_modules = [name for name, m in model.named_modules() if m.training]
    grad_enabled_before = torch.is_grad_enabled()
    first = np.asarray(embed(encoder, *SAMPLES["Python"]).vectors)
    second = np.asarray(embed(encoder, *SAMPLES["Python"]).vectors)
    record["actual"] = (f"modules in training mode: {len(training_modules)}; grad mode unchanged: "
                        f"{torch.is_grad_enabled() == grad_enabled_before}; repeat max abs diff "
                        f"{float(np.abs(first - second).max()):.2e}")
    assert not model.training and not training_modules
    assert torch.is_grad_enabled() == grad_enabled_before
    assert np.array_equal(first, second)
