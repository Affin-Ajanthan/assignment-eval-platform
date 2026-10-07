"""
One process-wide lock for loading the local ML models (UniXcoder in
``app/similarity/semantic.py``, MiniLM in ``app/evaluator/semantic_consistency.py``).

Both models are preloaded in background threads at startup. ``transformers``
initialises its package lazily, and that isn't safe to do from two threads
at once: while ``sentence_transformers`` is part-way through importing
``transformers`` in one thread, ``from transformers import AutoModel`` in
the other fails with "ImportError: cannot import name 'AutoModel'". Holding
this lock while importing and loading makes the two loads run one after
the other.
"""

from __future__ import annotations

import threading

MODEL_LOAD_LOCK = threading.RLock()
