"""
Tests for the UniXcoder semantic-similarity signal (app/similarity/semantic.py)
and its integration with the existing fingerprint/Jaccard/containment check.

Two kinds of test live here:

- Fast, offline tests that swap in a fake encoder, covering the plumbing:
  normalization, chunking, scoring, flag combination, caching, "model
  loaded once", failure handling, the API, and a 50-student batch.
- Tests marked ``slow`` that load the real ``microsoft/unixcoder-base``
  model (downloaded on first use) and check its actual behavior on the
  code samples in tests/semantic_samples.py. They skip, not fail, when the
  model can't be loaded (e.g. no network on first run).
"""

from __future__ import annotations

import io
import itertools
import threading
import types
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.similarity.core import compare_all, fingerprint_source
from app.similarity.semantic import (
    SemanticSimilarityService,
    SemanticThresholds,
    SubmissionEmbedding,
    UniXcoderEncoder,
    anonymize_identifiers,
    apply_semantic_signal,
    normalize_code,
    semantic_similarity,
    set_semantic_service,
    submissions_needing_semantic,
)
from semantic_samples import (
    DIFFERENT_BANK,
    DIFFERENT_JS,
    DIFFERENT_MAZE,
    GRADES_JAVA,
    GRADES_ORIGINAL,
    GRADES_RENAMED,
    GRADES_RESTRUCTURED,
    INDEPENDENT_SOLUTIONS,
)
from tests.auth_helpers import auth_headers, ensure_assignment, setup_subject_with_users, submit

client = TestClient(app)


# --------------------------------------------------------------------------
# Fakes + helpers
# --------------------------------------------------------------------------


class FakeEncoder:
    """Deterministic stand-in for UniXcoder: hashed bag-of-words vectors,
    one per window of `chunk_words` words. Records every call."""

    def __init__(self, chunk_words: int = 40, dim: int = 64, fail: bool = False):
        self.chunk_words = chunk_words
        self.dim = dim
        self.fail = fail
        self.calls: list[int] = []

    def _vector(self, words: list[str]) -> np.ndarray:
        v = np.zeros(self.dim)
        for w in words:
            v[zlib.crc32(w.encode()) % self.dim] += 1
        return v / (np.linalg.norm(v) or 1.0)

    def encode_many(self, texts):
        self.calls.append(len(texts))
        if self.fail:
            raise RuntimeError("simulated inference failure")
        out = []
        for text in texts:
            words = text.split()
            if not words:
                out.append(None)
                continue
            chunks = [words[i:i + self.chunk_words] for i in range(0, len(words), self.chunk_words)]
            out.append(SubmissionEmbedding(
                vectors=np.stack([self._vector(c) for c in chunks]),
                weights=[len(c) for c in chunks],
                token_count=len(words),
            ))
        return out


class MarkerEncoder:
    """Maps each submission to a fixed vector chosen by a string literal
    marker in its code (string literals survive normalization), so API
    tests can dictate exact semantic scores."""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = {k: np.asarray(v, dtype=float) / np.linalg.norm(v) for k, v in vectors.items()}
        self.calls: list[int] = []

    def encode_many(self, texts):
        self.calls.append(len(texts))
        out = []
        for text in texts:
            marker = next(k for k in self.vectors if k in text)
            out.append(SubmissionEmbedding(vectors=self.vectors[marker][None, :], weights=[50], token_count=50))
        return out


def _service(encoder, **kwargs) -> SemanticSimilarityService:
    return SemanticSimilarityService(encoder_factory=lambda: encoder, enabled=True, **kwargs)


def _run(sources: dict[str, tuple[str, str]], service: SemanticSimilarityService, thresholds=None):
    """The same steps the API endpoint runs: fingerprint, compare every
    unordered pair, embed only what's needed, combine."""
    fingerprints = {sid: fingerprint_source(sid, fn, code) for sid, (fn, code) in sources.items()}
    pairs = compare_all(fingerprints)
    needed = submissions_needing_semantic(pairs)
    batch = service.embed_submissions(
        {sid: normalize_code(code, fn) for sid, (fn, code) in sources.items() if sid in needed}
    )
    stats = apply_semantic_signal(pairs, batch.embeddings, thresholds) if batch.status == "ok" else {}
    return {frozenset((p.submission_a, p.submission_b)): p for p in pairs}, batch, stats


def _emb(*rows, weights=None) -> SubmissionEmbedding:
    vecs = np.asarray(rows, dtype=float)
    vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    return SubmissionEmbedding(vectors=vecs, weights=weights or [10] * len(rows), token_count=10 * len(rows))


@pytest.fixture
def injected_service():
    """Install a service for the API's duration of one test, then restore
    the default (disabled, see conftest.py)."""
    installed = []

    def install(service):
        set_semantic_service(service)
        installed.append(service)
        return service

    yield install
    set_semantic_service(None)


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


def test_normalize_strips_comments_but_keeps_string_contents():
    py = 'x = "# not a comment"  # a real comment\ny = 1'
    assert "real comment" not in normalize_code(py, "a.py")
    assert '"# not a comment"' in normalize_code(py, "a.py")

    c_like = 'String s = "http://x"; // trailing\n/* block\ncomment */ int n = 2;'
    norm = normalize_code(c_like, "A.java")
    assert '"http://x"' in norm
    assert "trailing" not in norm and "block" not in norm


def test_anonymization_is_consistent_and_keeps_language_and_library_names():
    a = anonymize_identifiers("total = 0\nfor value in scores.values():\n    total += value\nprint(len(scores))")
    b = anonymize_identifiers("acc = 0\nfor m in marks.values():\n    acc += m\nprint(len(marks))")
    assert a == b  # renaming every variable changes nothing
    assert ".values()" in a and "print" in a and "len" in a and "for" in a


def test_renamed_copy_normalizes_to_nearly_the_same_text():
    original = normalize_code(GRADES_ORIGINAL, "a.py")
    renamed = normalize_code(GRADES_RENAMED, "a.py")
    # Only the docstring (a string literal, deliberately kept) differs.
    assert original.replace('"""Read one \'name,score\' pair per line."""', "").split() == renamed.split()


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_identical_embeddings_score_one_and_orthogonal_score_zero():
    a = _emb([1, 0, 0])
    assert semantic_similarity(a, a) == pytest.approx(1.0)
    assert semantic_similarity(a, _emb([0, 1, 0])) == pytest.approx(0.0)


def test_chunk_order_does_not_matter():
    a = _emb([1, 0, 0], [0, 1, 0], [0, 0, 1])
    reordered = _emb([0, 0, 1], [1, 0, 0], [0, 1, 0])
    assert semantic_similarity(a, reordered) == pytest.approx(1.0)


def test_score_is_symmetric():
    a = _emb([1, 0, 0], [0, 1, 0])
    b = _emb([1, 1, 0])
    assert semantic_similarity(a, b) == pytest.approx(semantic_similarity(b, a))


def test_partial_copy_scores_between_unrelated_and_identical():
    a = _emb([1, 0, 0], [0, 1, 0])
    half = _emb([1, 0, 0], [0, 0, 1])
    s = semantic_similarity(a, half)
    assert 0.2 < s < 0.9


# --------------------------------------------------------------------------
# Chunking of long files (tokenizer stubbed -- no model needed)
# --------------------------------------------------------------------------


def _stub_encoder(chunk_tokens: int, overlap: int) -> UniXcoderEncoder:
    enc = UniXcoderEncoder.__new__(UniXcoderEncoder)
    enc.tokenizer = types.SimpleNamespace(tokenize=str.split)
    enc.chunk_tokens = chunk_tokens
    enc.stride = chunk_tokens - overlap
    return enc


def test_long_submission_is_chunked_not_truncated():
    enc = _stub_encoder(chunk_tokens=10, overlap=2)
    text = " ".join(f"t{i}" for i in range(95))
    chunks, weights, total = enc._chunks(text)
    assert total == 95
    assert all(len(c) <= 10 for c in chunks)
    assert chunks[-1][-1] == "t94"  # the end of the file is covered
    assert sum(weights) == 95  # every token counted exactly once
    covered = {tok for c in chunks for tok in c}
    assert covered == {f"t{i}" for i in range(95)}


def test_short_submission_is_one_chunk():
    chunks, weights, total = _stub_encoder(10, 2)._chunks("a b c")
    assert chunks == [["a", "b", "c"]] and weights == [3] and total == 3


# --------------------------------------------------------------------------
# Flag combination
# --------------------------------------------------------------------------


def _pair(a, b, jaccard, containment):
    from app.similarity.core import PairResult
    return PairResult(a, b, jaccard, containment, shared_fingerprints=0)


def test_semantic_only_pair_gets_review_flag_with_reason():
    pairs = [_pair("A", "B", 0.08, 0.12)]
    apply_semantic_signal(pairs, {"A": _emb([1, 0]), "B": _emb([1, 0.3])})
    p = pairs[0]
    assert not p.token_flagged
    assert p.flagged and p.flag_level == "review"
    assert p.flag_reason == "High semantic similarity despite low token overlap"


def test_token_flag_stays_high_and_semantic_never_unflags_it():
    pairs = [_pair("A", "B", 0.9, 0.95)]
    apply_semantic_signal(pairs, {"A": _emb([1, 0]), "B": _emb([0, 1])})
    assert pairs[0].flag_level == "high" and pairs[0].flagged


def test_low_semantic_and_low_tokens_is_not_flagged():
    pairs = [_pair("A", "B", 0.05, 0.1)]
    apply_semantic_signal(pairs, {"A": _emb([1, 0]), "B": _emb([0, 1])})
    assert not pairs[0].flagged and pairs[0].flag_reason is None


def test_pairs_without_embeddings_keep_token_only_behavior():
    pairs = [_pair("A", "B", 0.7, 0.8), _pair("A", "C", 0.1, 0.1)]
    apply_semantic_signal(pairs, {})
    assert pairs[0].semantic_similarity is None and pairs[0].flagged
    assert pairs[1].semantic_similarity is None and not pairs[1].flagged


def test_cohort_bar_raises_threshold_when_everyone_is_similar():
    # 6 submissions whose pairwise scores are all ~0.85-0.9 (everyone solved
    # the same task the same way): none is an outlier, none is flagged,
    # even though every score is over the absolute 0.80 floor.
    rng = np.random.default_rng(0)
    base = rng.normal(size=16)
    embs = {str(i): _emb(base + rng.normal(scale=0.35, size=16)) for i in range(6)}
    pairs = [_pair(a, b, 0.1, 0.1) for a, b in itertools.combinations(sorted(embs), 2)]
    stats = apply_semantic_signal(pairs, embs)
    assert stats["cohort_median"] > SemanticThresholds().review
    assert stats["review_threshold"] > stats["cohort_median"]
    assert sum(p.flag_level == "review" for p in pairs) <= 1


# --------------------------------------------------------------------------
# Service: loading once, caching, empty input, failures
# --------------------------------------------------------------------------


def test_model_is_loaded_once_even_with_concurrent_requests():
    created = []

    def factory():
        created.append(1)
        return FakeEncoder()

    service = SemanticSimilarityService(encoder_factory=factory, enabled=True)
    threads = [threading.Thread(target=service.embed_submissions, args=({"a": "x y z " * 10},)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    service.embed_submissions({"b": "p q r " * 10})
    assert len(created) == 1 and service.status == "ready"


def test_each_submission_is_encoded_once_and_reused_from_cache():
    encoder = FakeEncoder()
    service = _service(encoder)
    sources = {str(i): f"def f{i}(): return {i} " * 20 for i in range(5)}
    first = service.embed_submissions(sources)
    assert first.encoded == 5 and first.cache_hits == 0
    assert encoder.calls == [5]  # one batched call, not one per pair
    second = service.embed_submissions(sources)
    assert second.encoded == 0 and second.cache_hits == 5
    assert encoder.calls == [5]


def test_empty_and_tiny_submissions_are_skipped_without_error():
    service = _service(FakeEncoder(), min_tokens=16)
    batch = service.embed_submissions({"empty": "", "blank": "   ", "tiny": "x = 1", "real": "a b c d " * 10})
    assert batch.status == "ok"
    assert set(batch.skipped_too_small) == {"empty", "blank", "tiny"}
    assert set(batch.embeddings) == {"real"}


def test_empty_submissions_in_a_full_run_get_no_semantic_score():
    sources = {"a": ("a.py", ""), "b": ("b.py", "x = 1"), "c": ("c.py", GRADES_ORIGINAL)}
    pairs, batch, _ = _run(sources, _service(FakeEncoder()))
    assert batch.status == "ok"
    assert all(p.semantic_similarity is None for p in pairs.values())
    assert not any(p.flagged for p in pairs.values())


def test_load_failure_reports_unavailable_and_keeps_token_results():
    def broken():
        raise OSError("couldn't reach huggingface.co")

    service = SemanticSimilarityService(encoder_factory=broken, enabled=True)
    sources = {"orig": ("a.py", GRADES_ORIGINAL), "renamed": ("a.py", GRADES_RENAMED), "maze": ("a.py", DIFFERENT_MAZE)}
    pairs, batch, _ = _run(sources, service)
    assert batch.status == "unavailable" and service.status == "unavailable"
    assert "unavailable" in batch.warning and "huggingface.co" in batch.warning
    copied = pairs[frozenset(("orig", "renamed"))]
    assert copied.flagged and copied.token_flagged and copied.semantic_similarity is None
    assert not pairs[frozenset(("orig", "maze"))].flagged


def test_load_failure_is_not_retried_on_every_request_until_reset():
    attempts = []

    def broken():
        attempts.append(1)
        raise ImportError("No module named 'torch'")

    service = SemanticSimilarityService(encoder_factory=broken, enabled=True)
    service.embed_submissions({"a": "x " * 30})
    service.embed_submissions({"a": "x " * 30})
    assert len(attempts) == 1
    service.retry()
    service.embed_submissions({"a": "x " * 30})
    assert len(attempts) == 2


def test_inference_failure_reports_unavailable_without_raising():
    batch = _service(FakeEncoder(fail=True)).embed_submissions({"a": "x y " * 20, "b": "y z " * 20})
    assert batch.status == "unavailable"
    assert batch.embeddings == {}
    assert "inference" in batch.warning


def test_disabled_service_never_loads_a_model():
    created = []
    service = SemanticSimilarityService(encoder_factory=lambda: created.append(1), enabled=False)
    batch = service.embed_submissions({"a": "x " * 30})
    assert batch.status == "disabled" and not created


# --------------------------------------------------------------------------
# 50-student batch
# --------------------------------------------------------------------------


def _fifty_students() -> dict[str, tuple[str, str]]:
    programs = [GRADES_ORIGINAL, DIFFERENT_BANK, DIFFERENT_MAZE, *INDEPENDENT_SOLUTIONS.values()]
    return {
        f"s{i:02d}": ("a.py", programs[i % len(programs)] + f'\nSTUDENT_ID = "student-{i}"\nLIMIT = {i}\n')
        for i in range(50)
    }


def test_fifty_students_compare_each_unordered_pair_once_and_encode_each_submission_once():
    encoder = FakeEncoder()
    service = _service(encoder)
    pairs, batch, stats = _run(_fifty_students(), service)

    assert len(pairs) == 50 * 49 // 2 == 1225  # A-B only, never B-A as well
    assert all(len(key) == 2 for key in pairs)
    assert sum(encoder.calls) <= 50  # inference per submission, not per pair
    assert batch.encoded + len(batch.skipped_too_small) == sum(encoder.calls)
    needed = submissions_needing_semantic(pairs.values())
    expected_semantic = sum(1 for p in pairs.values() if p.submission_a in needed and p.submission_b in needed)
    assert stats["semantic_pairs_compared"] == expected_semantic

    rerun_pairs, rerun_batch, _ = _run(_fifty_students(), service)
    assert rerun_batch.encoded == 0 and rerun_batch.cache_hits == batch.encoded
    assert [p.semantic_similarity for p in rerun_pairs.values()] == [p.semantic_similarity for p in pairs.values()]


# --------------------------------------------------------------------------
# API integration
# --------------------------------------------------------------------------


def _submit(_student_tok, subject_id, assignment, code: str, filename="solution.py"):
    # Each call submits as a fresh student: one student submits an assignment once.
    r = submit(client, subject_id, assignment, {"code": (filename, io.BytesIO(code.encode()), "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()


def _check(subject_id, assignment, instructor_tok):
    r = client.post(
        f"/subjects/{subject_id}/assignments/{assignment}/check-similarity",
        headers=auth_headers(instructor_tok),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _find(body, a_id, b_id):
    return next(p for p in body["pairs"] if {p["submission_a_id"], p["submission_b_id"]} == {a_id, b_id})


def test_api_reports_semantic_review_flag_alongside_token_metrics(injected_service):
    injected_service(_service(MarkerEncoder({
        "ALPHA2": [1.0, 0.25, 0.0], "ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0],
    })))
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Semantic API Assignment"
    s1 = _submit(student_tok, subject["id"], assignment, GRADES_ORIGINAL + '\nTAG = "ALPHA"\n')
    s2 = _submit(student_tok, subject["id"], assignment, GRADES_RESTRUCTURED + '\nTAG = "ALPHA2"\n')
    s3 = _submit(student_tok, subject["id"], assignment, DIFFERENT_BANK + '\nTAG = "BETA"\n')

    body = _check(subject["id"], assignment, instructor_tok)
    assert body["semantic"]["status"] == "ok" and body["semantic"]["warning"] is None
    assert body["semantic"]["model"] == "microsoft/unixcoder-base"

    rewritten = _find(body, s1["id"], s2["id"])
    assert rewritten["jaccard"] < 0.6 and rewritten["containment"] < 0.75 and not rewritten["token_flagged"]
    assert rewritten["semantic_similarity"] > 0.9
    assert rewritten["flagged"] and rewritten["flag_level"] == "review"
    assert rewritten["flag_reason"] == "High semantic similarity despite low token overlap"
    assert rewritten["student_a"] and rewritten["student_b"]

    unrelated = _find(body, s1["id"], s3["id"])
    assert not unrelated["flagged"] and unrelated["flag_level"] is None


def test_api_semantic_unavailable_keeps_token_flags_and_warns(injected_service):
    def broken():
        raise OSError("model download failed")

    injected_service(SemanticSimilarityService(encoder_factory=broken, enabled=True))
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Semantic Down Assignment"
    s1 = _submit(student_tok, subject["id"], assignment, GRADES_ORIGINAL)
    s2 = _submit(student_tok, subject["id"], assignment, GRADES_RENAMED)
    _submit(student_tok, subject["id"], assignment, DIFFERENT_MAZE)

    body = _check(subject["id"], assignment, instructor_tok)
    assert body["semantic"]["status"] == "unavailable"
    assert "model download failed" in body["semantic"]["warning"]
    copied = _find(body, s1["id"], s2["id"])
    assert copied["flagged"] and copied["token_flagged"] and copied["flag_level"] == "high"
    assert copied["semantic_similarity"] is None
    assert all(p["semantic_similarity"] is None for p in body["pairs"])


def test_api_semantic_disabled_by_default_in_tests():
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Semantic Disabled Assignment"
    _submit(student_tok, subject["id"], assignment, GRADES_ORIGINAL)
    _submit(student_tok, subject["id"], assignment, DIFFERENT_BANK)
    body = _check(subject["id"], assignment, instructor_tok)
    assert body["semantic"]["status"] == "disabled"


def test_semantic_review_flag_is_shown_in_auto_evaluation_but_never_caps_the_score(injected_service):
    injected_service(_service(MarkerEncoder({"ALPHA2": [1.0, 0.2], "ALPHA": [1.0, 0.0]})))
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Semantic Auto-eval Assignment"
    rubric = client.post(
        "/rubrics",
        json={"name": "Integrity", "subject_id": subject["id"],
              "criteria": [{"name": "Academic integrity", "description": "original work", "max_points": 20}]},
        headers=auth_headers(instructor_tok),
    ).json()
    s1 = _submit(student_tok, subject["id"], assignment, GRADES_ORIGINAL + '\nTAG = "ALPHA"\n')
    s2 = _submit(student_tok, subject["id"], assignment, GRADES_RESTRUCTURED + '\nTAG = "ALPHA2"\n')
    assert _find(_check(subject["id"], assignment, instructor_tok), s1["id"], s2["id"])["flag_level"] == "review"

    body = client.post(
        f"/submissions/{s1['id']}/auto-evaluate", json={"rubric_id": rubric["id"]},
        headers=auth_headers(instructor_tok),
    ).json()
    assert body["similarity_flagged"] is False
    assert any("potential similarity detected" in f and "lecturer review recommended" in f
               for f in body["review_flags"])
    assert not any("confirmed" in f.lower() for f in body["review_flags"])


def test_api_fifty_students_one_batch(injected_service):
    encoder = FakeEncoder()
    injected_service(_service(encoder))
    subject, instructor_tok, student_tok = setup_subject_with_users(client)
    assignment = "Fifty Student Assignment"
    for _sid, (_fn, code) in _fifty_students().items():
        _submit(student_tok, subject["id"], assignment, code)

    body = _check(subject["id"], assignment, instructor_tok)
    assert body["compared"] == 50
    assert len(body["pairs"]) == 1225
    assert len({frozenset((p["submission_a_id"], p["submission_b_id"])) for p in body["pairs"]}) == 1225
    assert len(encoder.calls) == 1 and encoder.calls[0] <= 50
    assert body["semantic"]["submissions_encoded"] <= 50


def test_add_missing_columns_upgrades_an_existing_table():
    from app.db import add_missing_columns, engine

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS legacy_flags_test")
        conn.exec_driver_sql("CREATE TABLE legacy_flags_test (id INTEGER PRIMARY KEY, jaccard FLOAT)")
        conn.exec_driver_sql("INSERT INTO legacy_flags_test (jaccard) VALUES (0.7)")
    add_missing_columns("legacy_flags_test", {"semantic_similarity": "FLOAT", "flag_level": "VARCHAR"})
    add_missing_columns("legacy_flags_test", {"semantic_similarity": "FLOAT"})  # idempotent
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(legacy_flags_test)")}
        row = conn.exec_driver_sql("SELECT jaccard, semantic_similarity FROM legacy_flags_test").one()
        conn.exec_driver_sql("DROP TABLE legacy_flags_test")
    assert {"semantic_similarity", "flag_level"} <= cols
    assert row == (0.7, None)


# --------------------------------------------------------------------------
# Real UniXcoder model (slow; skips when the model can't be loaded)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def unixcoder():
    service = SemanticSimilarityService(enabled=True)
    if not service.load():
        pytest.skip(f"UniXcoder unavailable: {service.error}")
    return service


def _real_scores(service, named: dict[str, tuple[str, str]]):
    batch = service.embed_submissions({k: normalize_code(code, fn) for k, (fn, code) in named.items()})
    assert batch.status == "ok", batch.warning
    return batch.embeddings


@pytest.mark.slow
def test_real_identical_submissions(unixcoder):
    e = _real_scores(unixcoder, {"a": ("a.py", GRADES_ORIGINAL)})
    assert semantic_similarity(e["a"], e["a"]) == pytest.approx(1.0, abs=1e-4)


@pytest.mark.slow
def test_real_minor_variable_renames_score_high_and_are_token_flagged(unixcoder):
    pairs, batch, _ = _run({"orig": ("a.py", GRADES_ORIGINAL), "renamed": ("a.py", GRADES_RENAMED)}, unixcoder)
    p = pairs[frozenset(("orig", "renamed"))]
    assert p.token_flagged and p.flag_level == "high"
    # The token check is already conclusive, so the first-pass filter
    # skips model inference for this pair entirely...
    assert batch.encoded == 0 and p.semantic_similarity is None
    # ...but the model agrees when asked directly.
    e = _real_scores(unixcoder, {"orig": ("a.py", GRADES_ORIGINAL), "renamed": ("a.py", GRADES_RENAMED)})
    assert semantic_similarity(e["orig"], e["renamed"]) >= 0.85


@pytest.mark.slow
def test_real_restructured_copy_flagged_for_review_but_honest_solutions_are_not(unixcoder):
    """The core scenario: a rewrite with reordered functions and
    restructured loops slips under the token thresholds, while five
    independently written solutions to the same task are in the cohort."""
    cohort = {
        "orig": ("a.py", GRADES_ORIGINAL),
        "restructured": ("a.py", GRADES_RESTRUCTURED),
        **{name: ("a.py", code) for name, code in INDEPENDENT_SOLUTIONS.items()},
    }
    pairs, _, stats = _run(cohort, unixcoder)
    rewritten = pairs[frozenset(("orig", "restructured"))]
    assert not rewritten.token_flagged, (rewritten.jaccard, rewritten.containment)
    assert rewritten.flag_level == "review", (rewritten.semantic_similarity, stats)

    honest = [p for key, p in pairs.items() if key & set(INDEPENDENT_SOLUTIONS) == key]
    assert honest and not any(p.flagged for p in honest), [(sorted(k), p.semantic_similarity)
                                                           for k, p in pairs.items() if p.flagged]


@pytest.mark.slow
def test_real_different_variable_names_equivalent_logic(unixcoder):
    # Renamed AND restructured: no shared names, different structure, same logic.
    e = _real_scores(unixcoder, {"a": ("a.py", GRADES_RENAMED), "b": ("a.py", GRADES_RESTRUCTURED),
                                 "honest": ("a.py", INDEPENDENT_SOLUTIONS["h_dict"])})
    equivalent = semantic_similarity(e["a"], e["b"])
    assert equivalent >= SemanticThresholds().review
    assert equivalent > semantic_similarity(e["a"], e["honest"])


@pytest.mark.slow
def test_real_completely_different_implementations_score_low(unixcoder):
    pairs, _, _ = _run({"grades": ("a.py", GRADES_ORIGINAL), "bank": ("a.py", DIFFERENT_BANK),
                        "maze": ("a.py", DIFFERENT_MAZE)}, unixcoder)
    for p in pairs.values():
        assert p.semantic_similarity < 0.5, (p.submission_a, p.submission_b, p.semantic_similarity)
        assert not p.flagged


@pytest.mark.slow
def test_real_long_submission_is_fully_encoded_and_order_independent(unixcoder):
    blocks = [GRADES_ORIGINAL, DIFFERENT_BANK, DIFFERENT_MAZE]
    long_a = "\n\n".join(blocks * 4)
    long_b = "\n\n".join(list(reversed(blocks)) * 4)
    e = _real_scores(unixcoder, {"a": ("a.py", long_a), "b": ("a.py", long_b), "short": ("a.py", GRADES_ORIGINAL)})
    assert e["a"].chunk_count > 1  # well past the 512-token model limit
    assert sum(e["a"].weights) == e["a"].token_count  # nothing truncated
    assert semantic_similarity(e["a"], e["b"]) >= 0.9
    # The short file is one third of the long one -> clearly less than a full match.
    assert semantic_similarity(e["a"], e["short"]) < semantic_similarity(e["a"], e["b"])


@pytest.mark.slow
def test_real_multiple_languages(unixcoder):
    e = _real_scores(unixcoder, {"py": ("a.py", GRADES_ORIGINAL), "java": ("Grades.java", GRADES_JAVA),
                                 "js": ("util.js", DIFFERENT_JS)})
    assert set(e) == {"py", "java", "js"}
    same_task_cross_language = semantic_similarity(e["py"], e["java"])
    assert same_task_cross_language > semantic_similarity(e["java"], e["js"])
    assert same_task_cross_language > semantic_similarity(e["py"], e["js"])


@pytest.mark.slow
def test_real_fifty_student_batch(unixcoder):
    pairs, batch, stats = _run(_fifty_students(), unixcoder)
    assert len(pairs) == 1225
    assert batch.status == "ok"
    assert batch.encoded + batch.cache_hits + len(batch.skipped_too_small) <= 50
    assert stats["semantic_pairs_compared"] > 0
