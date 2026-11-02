"""The report check's MiniLM vectors are kept on disk (app/embedding_cache.py,
shared with the code check's UniXcoder cache), so after a restart reports
already seen are not encoded again. A fake encoder counts what is encoded."""

import hashlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.evaluator import semantic_consistency as sc
from app.evaluator.semantic_consistency import SentenceEmbeddingService
from app.embedding_cache import cache_dir_setting
from app.similarity import report_similarity as rs

REPORTS = {
    "1": ("My library program stores books and members in two dictionaries. Borrowing checks the member's limit "
          "first. Returning a book clears its due date and adds a fine when it is late. ") * 4,
    "2": ("The design uses one class per entity and a small menu loop. Every command validates its input before "
          "changing any data. Tests cover the fine calculation and leap years. ") * 4,
    "3": ("I kept the loans in a list sorted by due date so the overdue report is quick. The file is saved after "
          "every change so nothing is lost if the program stops. ") * 4,
}


class CountingEncoder:
    """Deterministic unit vectors from each chunk's text; remembers every call."""

    def __init__(self):
        self.calls: list[int] = []

    def encode(self, texts):
        self.calls.append(len(texts))
        rows = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:4], "little")
            v = np.random.default_rng(seed).normal(size=16)
            rows.append(v / np.linalg.norm(v))
        return np.asarray(rows)


def _service(tmp_path, encoder=None, revision="rev-a"):
    encoder = encoder or CountingEncoder()

    def factory():
        return encoder

    service = SentenceEmbeddingService(encoder_factory=factory, enabled=True, cache_dir=tmp_path,
                                       model_revision=revision)
    assert service.load()
    return service, encoder


def test_a_restart_reads_reports_from_disk_instead_of_encoding_them(tmp_path):
    first, enc1 = _service(tmp_path)
    before = first.embed_chunks(REPORTS)
    assert sum(enc1.calls) > 0 and len(list(tmp_path.glob("*.npz"))) == 3

    second, enc2 = _service(tmp_path)        # a new process: empty memory, same folder
    after = second.embed_chunks(REPORTS)
    assert enc2.calls == [] and second.disk_hits == 3
    for name in REPORTS:
        assert np.array_equal(before[name][0], after[name][0])
        assert np.array_equal(before[name][1], after[name][1])


def test_only_new_reports_are_encoded(tmp_path):
    first, _ = _service(tmp_path)
    first.embed_chunks({k: REPORTS[k] for k in ("1", "2")})
    second, enc = _service(tmp_path)
    second.embed_chunks(REPORTS)
    assert second.disk_hits == 2 and sum(enc.calls) == len(sc.chunk_text(REPORTS["3"]))


def test_another_model_revision_or_format_is_never_read(tmp_path, monkeypatch):
    first, _ = _service(tmp_path, revision="rev-a")
    first.embed_chunks(REPORTS)
    other, enc = _service(tmp_path, revision="rev-b")   # the model was re-downloaded in a newer version
    other.embed_chunks(REPORTS)
    assert other.disk_hits == 0 and sum(enc.calls) > 0
    monkeypatch.setattr(sc, "CACHE_FORMAT", sc.CACHE_FORMAT + 1)
    newer, enc = _service(tmp_path, revision="rev-a")
    newer.embed_chunks(REPORTS)
    assert newer.disk_hits == 0 and sum(enc.calls) > 0


def test_a_damaged_file_is_recomputed_and_replaced(tmp_path):
    first, _ = _service(tmp_path)
    first.embed_chunks({"1": REPORTS["1"]})
    (path,) = tmp_path.glob("*.npz")
    path.write_bytes(b"not a numpy file")
    second, enc = _service(tmp_path)
    second.embed_chunks({"1": REPORTS["1"]})
    assert sum(enc.calls) > 0 and second.disk_hits == 0
    third, enc = _service(tmp_path)
    third.embed_chunks({"1": REPORTS["1"]})
    assert enc.calls == [] and third.disk_hits == 1                  # the rewritten file is good again


def test_nothing_is_stored_before_the_model_is_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "downloaded_revision", lambda model_name=sc.MODEL_NAME: None)
    service, enc = _service(tmp_path, revision=None)
    service.embed_chunks(REPORTS)
    assert list(tmp_path.glob("*.npz")) == [] and sum(enc.calls) > 0


def test_the_report_check_gives_the_same_scores_from_the_disk_cache(tmp_path):
    first, _ = _service(tmp_path)
    fresh = rs.compare_reports(dict(REPORTS), first)
    second, enc = _service(tmp_path)
    cached = rs.compare_reports(dict(REPORTS), second)
    assert enc.calls == []
    assert [(p.submission_a, p.submission_b, p.semantic_similarity) for p in fresh.pairs] == \
        [(p.submission_a, p.submission_b, p.semantic_similarity) for p in cached.pairs]


def test_the_default_folder_follows_the_data_folder_and_can_be_moved_or_turned_off(tmp_path, monkeypatch):
    from app.db import BASE_DIR

    monkeypatch.delenv("MINILM_CACHE_DIR", raising=False)
    assert cache_dir_setting("MINILM_CACHE_DIR", "minilm") == BASE_DIR / "cache" / "minilm"
    monkeypatch.setenv("MINILM_CACHE_DIR", str(tmp_path / "elsewhere"))
    assert cache_dir_setting("MINILM_CACHE_DIR", "minilm") == tmp_path / "elsewhere"
    monkeypatch.setenv("MINILM_CACHE_DIR", "off")
    assert cache_dir_setting("MINILM_CACHE_DIR", "minilm") is None


def test_a_disabled_service_writes_nothing(tmp_path):
    SentenceEmbeddingService(enabled=False, cache_dir=tmp_path / "c")
    assert not (tmp_path / "c").exists()
