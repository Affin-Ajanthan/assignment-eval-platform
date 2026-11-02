"""Model outputs kept on disk between restarts: one ``.npz`` file of named
arrays per key, written atomically and pruned oldest-first to a byte cap.

Shared by the code check's UniXcoder vectors (app/similarity/semantic.py) and
the report check's MiniLM vectors (app/evaluator/semantic_consistency.py).
Each caller builds its own key -- covering the model revision, its chunking
and a format version, so nothing stale is read after any of them change -- and
checks what it reads back; this module only stores arrays. Best effort: any
failure is logged and treated as a miss, never as a failed check.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

MISSING = object()  # get(): nothing stored under that key
_OFF = {"", "0", "off", "false", "no", "none"}


class DiskArrayCache:
    def __init__(self, directory: Path | str, max_bytes: int, label: str = "embedding"):
        self.directory = Path(directory)
        self.max_bytes = max_bytes
        self.label = label  # for log messages: "semantic", "report embedding"
        self.prune()

    def path(self, key: str) -> Path:
        # 32 hex characters (128 bits of a SHA-256) keep the file name short: with the full 64
        # a deeply nested project folder can pass Windows' 260-character path limit and every write fails.
        return self.directory / f"{key[:32]}.npz"

    def get(self, key: str):
        """The arrays stored under `key` ({name: array}), None when "nothing" was
        stored (put(key, None)), or MISSING. A damaged file is deleted."""
        path = self.path(key)
        try:
            import numpy as np

            with np.load(path, allow_pickle=False) as stored:  # closed promptly: an open npz locks the file on Windows
                arrays = None if "empty" in stored.files else {name: stored[name] for name in stored.files}
            try:
                os.utime(path)  # a hit keeps the file young for oldest-first pruning
            except OSError:
                pass
            return arrays
        except FileNotFoundError:
            return MISSING
        except Exception as exc:
            log.warning("Ignoring unreadable %s cache file %s (%s: %s)", self.label, path.name,
                        exc.__class__.__name__, exc)
            self.discard(key)
            return MISSING

    def put(self, key: str, arrays: dict | None) -> None:
        """Store `arrays` ({name: array}) under `key`; None stores "nothing"."""
        tmp_name = None
        try:
            import numpy as np

            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".tmp", delete=False) as tmp:
                tmp_name = tmp.name
                if arrays is None:
                    np.savez(tmp, empty=np.array(1))
                else:
                    np.savez(tmp, **{name: np.asarray(a) for name, a in arrays.items()})
            os.replace(tmp_name, self.path(key))  # atomic: a reader never sees half a file
            tmp_name = None
        except Exception as exc:  # disk full, permissions, a reader holding the file open on Windows...
            log.warning("Could not write the %s cache (%s: %s); continuing without it", self.label,
                        exc.__class__.__name__, exc)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def discard(self, key: str) -> None:
        """Delete what is stored under `key` (the caller found it invalid)."""
        try:
            self.path(key).unlink()
        except OSError:
            pass

    def prune(self) -> None:
        """Delete the oldest files until the folder fits the byte cap (and any
        leftover temp file from a crashed write)."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            entries = []
            for p in self.directory.iterdir():
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
                if total <= self.max_bytes:
                    break
                try:
                    p.unlink()
                    total -= size
                except OSError:
                    pass
        except Exception as exc:
            log.warning("Could not prune the %s cache (%s: %s)", self.label, exc.__class__.__name__, exc)


def cache_dir_setting(env_name: str, folder: str) -> Path | None:
    """Where a cache lives: ``cache/<folder>`` next to the database (it follows
    PORTAL_DATA_DIR), or the folder in `env_name`; "off" there keeps everything
    in memory (None)."""
    raw = os.environ.get(env_name)
    if raw is not None:
        return None if raw.strip().lower() in _OFF else Path(raw)
    from .db import BASE_DIR  # imported here: it creates the uploads folder, which the caches otherwise never need

    return BASE_DIR / "cache" / folder


def max_bytes_setting(env_name: str, default_bytes: int) -> int:
    """A cache's byte cap from `env_name` in megabytes, else `default_bytes`."""
    try:
        return int(float(os.environ.get(env_name, "")) * 1024 * 1024)
    except ValueError:
        return default_bytes
