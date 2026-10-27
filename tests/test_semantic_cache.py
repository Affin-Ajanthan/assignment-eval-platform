"""The UniXcoder embedding cache: kept on disk across restarts, the model only
loaded when something is missing, and one inference pass shared by concurrent
checks. Uses fake encoders; the real model is compared in scripts/ (see the
cache measurements in the README of the change)."""

import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.similarity import semantic
from app.similarity.semantic import (
    SemanticSimilarityService,
    SubmissionEmbedding,
    default_cache_dir,
    semantic_similarity,
)


class CountingEncoder:
    """Deterministic vectors from the text; counts calls and submissions encoded."""

    def __init__(self, delay=0.0, token_count=100):
        self.calls = []
        self.delay = delay
        self.token_count = token_count

    def encode_many(self, texts):
        self.calls.append(len(texts))
        time.sleep(self.delay)
        out = []
        for text in texts:
            rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
            vectors = rng.normal(size=(3, 16)).astype(np.float32)
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            out.append(SubmissionEmbedding(vectors=vectors, weights=[100, 80, 60], token_count=self.token_count))
        return out


def _service(cache_dir, encoder=None, **kwargs):
    encoder = encoder or CountingEncoder()
    return SemanticSimilarityService(encoder_factory=lambda: encoder, enabled=True, cache_dir=cache_dir, **kwargs), encoder


def _boom():
    raise RuntimeError("the model must not be loaded")


SOURCES = {str(i): f"def f{i}(x):\n    return x * {i}\n" * 12 for i in range(4)}


def test_a_restart_reads_the_disk_cache_without_loading_the_model(tmp_path):
    first, encoder = _service(tmp_path)
    cold = first.embed_submissions(SOURCES)
    assert cold.status == "ok" and cold.encoded == 4 and cold.cache_hits == 0 and sum(encoder.calls) == 4
    assert len(list(tmp_path.glob("*.npz"))) == 4

    restarted = SemanticSimilarityService(encoder_factory=_boom, enabled=True, cache_dir=tmp_path)  # a new process
    warm = restarted.embed_submissions(SOURCES)
    assert warm.status == "ok" and warm.encoded == 0 and warm.cache_hits == 4
    assert restarted.status == "not_loaded"  # the model was never even loaded

    # exactly the same numbers after the round trip through disk
    for sid in SOURCES:
        assert warm.embeddings[sid].vectors.dtype == cold.embeddings[sid].vectors.dtype
        assert np.array_equal(warm.embeddings[sid].vectors, cold.embeddings[sid].vectors)
        assert warm.embeddings[sid].weights == cold.embeddings[sid].weights
        assert warm.embeddings[sid].token_count == cold.embeddings[sid].token_count
    assert semantic_similarity(warm.embeddings["0"], warm.embeddings["1"]) == \
        semantic_similarity(cold.embeddings["0"], cold.embeddings["1"])


def test_only_the_missing_submissions_are_encoded(tmp_path):
    service, encoder = _service(tmp_path)
    service.embed_submissions({k: SOURCES[k] for k in ("0", "1")})
    restarted, encoder2 = _service(tmp_path)
    batch = restarted.embed_submissions(SOURCES)  # 0 and 1 cached, 2 and 3 new
    assert (batch.cache_hits, batch.encoded) == (2, 2) and encoder2.calls == [2]


def test_a_corrupt_cache_file_is_recomputed_and_replaced(tmp_path):
    first, _ = _service(tmp_path)
    first.embed_submissions({"0": SOURCES["0"]})
    (damaged,) = tmp_path.glob("*.npz")
    damaged.write_bytes(b"this is not an npz file")

    again, encoder = _service(tmp_path)
    batch = again.embed_submissions({"0": SOURCES["0"]})
    assert batch.status == "ok" and batch.encoded == 1 and encoder.calls == [1]
    third, encoder3 = _service(tmp_path)
    assert third.embed_submissions({"0": SOURCES["0"]}).cache_hits == 1 and encoder3.calls == []  # valid file again


def test_a_stored_embedding_with_bad_numbers_is_not_trusted(tmp_path):
    first, _ = _service(tmp_path)
    first.embed_submissions({"0": SOURCES["0"]})
    (path,) = tmp_path.glob("*.npz")
    np.savez(path, vectors=np.full((2, 4), np.nan, dtype=np.float32), weights=np.array([5, 5]),
             token_count=np.array(50))
    again, encoder = _service(tmp_path)
    assert again.embed_submissions({"0": SOURCES["0"]}).encoded == 1 and encoder.calls == [1]


def test_changed_code_model_revision_or_format_is_a_miss(tmp_path, monkeypatch):
    first, _ = _service(tmp_path)
    first.embed_submissions({"0": SOURCES["0"]})

    other, encoder = _service(tmp_path)
    assert other.embed_submissions({"0": SOURCES["0"] + "# edited\nx = 1\n"}).encoded == 1  # code changed

    monkeypatch.setattr(semantic, "MODEL_REVISION", "another-revision")
    revised, encoder_r = _service(tmp_path)
    assert revised.embed_submissions({"0": SOURCES["0"]}).encoded == 1 and encoder_r.calls == [1]
    monkeypatch.undo()

    monkeypatch.setattr(semantic, "CACHE_FORMAT", semantic.CACHE_FORMAT + 1)
    reformatted, encoder_f = _service(tmp_path)
    assert reformatted.embed_submissions({"0": SOURCES["0"]}).encoded == 1 and encoder_f.calls == [1]


def test_too_small_submissions_are_cached_and_judged_when_read(tmp_path):
    first, encoder = _service(tmp_path, CountingEncoder(token_count=5))
    cold = first.embed_submissions({"0": SOURCES["0"]})
    assert cold.skipped_too_small == ["0"] and cold.embeddings == {} and sum(encoder.calls) == 1

    again, encoder2 = _service(tmp_path, CountingEncoder(token_count=5))
    assert again.embed_submissions({"0": SOURCES["0"]}).skipped_too_small == ["0"] and encoder2.calls == []  # not re-encoded

    # stored as encoded, so a lower min_tokens takes effect without encoding again
    lenient, encoder3 = _service(tmp_path, CountingEncoder(token_count=5), min_tokens=1)
    batch = lenient.embed_submissions({"0": SOURCES["0"]})
    assert "0" in batch.embeddings and encoder3.calls == []


def test_an_empty_encoder_result_is_cached_as_nothing_to_embed(tmp_path):
    class NoneEncoder:
        calls = 0

        def encode_many(self, texts):
            NoneEncoder.calls += 1
            return [None for _ in texts]

    first = SemanticSimilarityService(encoder_factory=NoneEncoder, enabled=True, cache_dir=tmp_path)
    assert first.embed_submissions({"0": SOURCES["0"]}).skipped_too_small == ["0"]
    again = SemanticSimilarityService(encoder_factory=NoneEncoder, enabled=True, cache_dir=tmp_path)
    assert again.embed_submissions({"0": SOURCES["0"]}).skipped_too_small == ["0"] and NoneEncoder.calls == 1


def test_concurrent_checks_share_one_inference_pass(tmp_path):
    service, encoder = _service(tmp_path, CountingEncoder(delay=0.4))
    batches = []
    threads = [threading.Thread(target=lambda: batches.append(service.embed_submissions(SOURCES))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert encoder.calls == [4]  # 6 students checking at once: the class is encoded once, not six times
    assert len(batches) == 6 and all(set(b.embeddings) == set(SOURCES) and b.status == "ok" for b in batches)
    assert sum(b.encoded for b in batches) == 4  # exactly one pass did the work; the others read its results


def test_concurrent_checks_share_one_pass_without_a_disk_cache_too():
    service = SemanticSimilarityService(encoder_factory=lambda: encoder, enabled=True)
    encoder = CountingEncoder(delay=0.3)
    threads = [threading.Thread(target=service.embed_submissions, args=(SOURCES,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert encoder.calls == [4]


def test_cached_work_needs_no_model_but_new_work_does(tmp_path):
    seed, _ = _service(tmp_path)
    seed.embed_submissions({"0": SOURCES["0"]})
    broken = SemanticSimilarityService(encoder_factory=_boom, enabled=True, cache_dir=tmp_path)
    assert broken.embed_submissions({"0": SOURCES["0"]}).status == "ok"        # everything cached: fine without the model
    unavailable = broken.embed_submissions({"0": SOURCES["0"], "1": SOURCES["1"]})
    assert unavailable.status == "unavailable" and unavailable.embeddings == {}  # something missing and no model


def test_a_disabled_service_stays_disabled_even_with_a_warm_cache(tmp_path):
    seed, _ = _service(tmp_path)
    seed.embed_submissions({"0": SOURCES["0"]})
    off = SemanticSimilarityService(encoder_factory=_boom, enabled=False, cache_dir=tmp_path)
    assert off.embed_submissions({"0": SOURCES["0"]}).status == "disabled"


def test_a_failing_encoder_leaves_nothing_cached(tmp_path):
    class Failing:
        def encode_many(self, texts):
            raise RuntimeError("out of memory")

    service = SemanticSimilarityService(encoder_factory=Failing, enabled=True, cache_dir=tmp_path)
    batch = service.embed_submissions({"0": SOURCES["0"]})
    assert batch.status == "unavailable" and "out of memory" in batch.warning
    assert list(tmp_path.glob("*.npz")) == []


def test_pruning_keeps_the_cache_under_its_byte_cap_dropping_the_oldest(tmp_path):
    seed, _ = _service(tmp_path)
    seed.embed_submissions(SOURCES)
    files = sorted(tmp_path.glob("*.npz"))
    for age, f in enumerate(files):  # oldest first
        os.utime(f, (time.time() - 1000 + age * 10,) * 2)
    size = files[0].stat().st_size
    SemanticSimilarityService(encoder_factory=_boom, enabled=True, cache_dir=tmp_path, cache_max_bytes=size * 2 + 10)
    left = sorted(tmp_path.glob("*.npz"))
    assert left == files[2:]  # the two oldest went, the two newest stayed


def test_pruning_removes_old_leftover_temp_files(tmp_path):
    stale = tmp_path / "abandoned.tmp"
    stale.write_bytes(b"x")
    os.utime(stale, (time.time() - 7200,) * 2)
    fresh = tmp_path / "in-progress.tmp"
    fresh.write_bytes(b"x")
    SemanticSimilarityService(encoder_factory=_boom, enabled=True, cache_dir=tmp_path)
    assert not stale.exists() and fresh.exists()


def test_services_built_without_a_directory_are_memory_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = SemanticSimilarityService(encoder_factory=CountingEncoder, enabled=True)
    service.embed_submissions(SOURCES)
    assert list(tmp_path.rglob("*.npz")) == []
    again = service.embed_submissions(SOURCES)  # still cached in memory
    assert again.cache_hits == 4


def test_the_default_cache_folder_follows_the_data_folder_and_can_be_moved_or_turned_off(tmp_path, monkeypatch):
    from app.db import BASE_DIR

    monkeypatch.delenv("SEMANTIC_CACHE_DIR", raising=False)
    assert default_cache_dir() == BASE_DIR / "cache" / "unixcoder"
    monkeypatch.setenv("SEMANTIC_CACHE_DIR", str(tmp_path / "elsewhere"))
    assert default_cache_dir() == tmp_path / "elsewhere"
    for off in ("off", "0", "", "none"):
        monkeypatch.setenv("SEMANTIC_CACHE_DIR", off)
        assert default_cache_dir() is None


def test_an_unwritable_cache_folder_does_not_break_a_check(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the cache folder should be")
    service = SemanticSimilarityService(encoder_factory=CountingEncoder, enabled=True, cache_dir=blocker / "cache")
    batch = service.embed_submissions(SOURCES)
    assert batch.status == "ok" and batch.encoded == 4  # computed and served; just not stored on disk
    assert service.embed_submissions(SOURCES).cache_hits == 4  # the in-memory cache still works


def test_cache_file_names_stay_short_so_windows_paths_stay_under_the_limit(tmp_path):
    service, _ = _service(tmp_path)
    service.embed_submissions(SOURCES)
    names = [p.name for p in tmp_path.glob("*.npz")]
    assert len(names) == 4 and all(len(n) == 36 for n in names)  # 32 hex + ".npz"
    # 128 bits of the hash still tell different code apart
    assert len({n for n in names}) == 4
