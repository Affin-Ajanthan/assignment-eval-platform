import textwrap

from app.similarity.ai_heuristics import score_source
from app.similarity.core import (
    containment_similarity,
    fingerprint_source,
    jaccard_similarity,
)

ORIGINAL = textwrap.dedent(
    """
    def bubble_sort(items):
        n = len(items)
        for i in range(n):
            for j in range(0, n - i - 1):
                if items[j] > items[j + 1]:
                    items[j], items[j + 1] = items[j + 1], items[j]
        return items
    """
)

RENAMED = textwrap.dedent(
    """
    def sort_list(values):
        length = len(values)
        for a in range(length):
            for b in range(0, length - a - 1):
                if values[b] > values[b + 1]:
                    values[b], values[b + 1] = values[b + 1], values[b]
        return values
    """
)

DIFFERENT = textwrap.dedent(
    """
    def fibonacci(n):
        a, b = 0, 1
        result = []
        for _ in range(n):
            result.append(a)
            a, b = b, a + b
        return result
    """
)


def test_identical_sources_are_fully_similar():
    fp1 = fingerprint_source("s1", "a.py", ORIGINAL)
    fp2 = fingerprint_source("s2", "a.py", ORIGINAL)
    assert jaccard_similarity(fp1.hashes, fp2.hashes) == 1.0


def test_renamed_variables_still_flagged_as_similar():
    fp1 = fingerprint_source("s1", "a.py", ORIGINAL)
    fp2 = fingerprint_source("s2", "a.py", RENAMED)
    similarity = jaccard_similarity(fp1.hashes, fp2.hashes)
    assert similarity > 0.6, f"expected renamed copy to score high, got {similarity}"


def test_different_algorithms_score_low():
    fp1 = fingerprint_source("s1", "a.py", ORIGINAL)
    fp2 = fingerprint_source("s2", "a.py", DIFFERENT)
    similarity = jaccard_similarity(fp1.hashes, fp2.hashes)
    assert similarity < 0.3, f"expected unrelated code to score low, got {similarity}"


def test_containment_computable_without_error():
    snippet = "\n".join(ORIGINAL.splitlines()[1:4])
    fp_full = fingerprint_source("s1", "a.py", ORIGINAL)
    fp_snip = fingerprint_source("s2", "a.py", snippet)
    c = containment_similarity(fp_full.hashes, fp_snip.hashes)
    assert 0.0 <= c <= 1.0


def test_empty_source_does_not_crash():
    fp = fingerprint_source("s1", "a.py", "")
    assert fp.hashes == set()
    assert jaccard_similarity(fp.hashes, fp.hashes) == 0.0


def test_ai_heuristic_runs_and_returns_bounded_score():
    result = score_source("s1", ORIGINAL)
    assert 0 <= result.score <= 100
    assert result.signal in {"low", "medium", "high"}
    assert result.reasons
