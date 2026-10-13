"""
Fixtures and result recording for the UniXcoder basic-functionality suite.

- The production encoder (``app.similarity.semantic.UniXcoderEncoder``) is
  loaded ONCE for the whole session and shared by every test. If it can't be
  loaded, every test errors with the load failure -- nothing is skipped.
- Each test carries ``@pytest.mark.tc(...)`` metadata and fills in
  ``record["actual"]``; after the run a table of ID / language / description /
  expected / actual / status / error is written to ``last_report.md`` here.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

REPORT_PATH = Path(__file__).parent / "last_report.md"
_results: list[dict] = []


def pytest_configure(config):
    config.addinivalue_line("markers", "tc(id, lang, desc, expected): UniXcoder basic test-case metadata")


@pytest.fixture(scope="session")
def encoder(request):
    """The real production encoder, loaded once per run (CPU only) and shared
    with tests/unixcoder_invariance through the pytest config."""
    cached = getattr(request.config, "_unixcoder_encoder", None)
    if cached is not None:
        return cached
    from app.similarity.semantic import UniXcoderEncoder

    started = time.perf_counter()
    try:
        enc = UniXcoderEncoder(device="cpu")
    except Exception as exc:  # fail loudly: never a silent skip
        pytest.fail(f"UniXcoder could not be loaded: {type(exc).__name__}: {exc}", pytrace=False)
    enc.load_seconds = time.perf_counter() - started
    request.config._unixcoder_encoder = enc
    return enc


@pytest.fixture
def record(request):
    """Per-test scratchpad: tests put a human-readable result in ``actual``."""
    data = {"actual": ""}
    request.node._tc_record = data
    return data


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("tc")
    if marker is None:
        return
    # Record the call phase, or a setup failure (e.g. the model didn't load).
    if report.when == "call" or (report.when == "setup" and report.failed):
        error = ""
        if report.failed:
            error = str(call.excinfo.value).strip().splitlines()[0] if call.excinfo else report.longreprtext[:300]
        _results.append({
            **marker.kwargs,
            "actual": getattr(item, "_tc_record", {}).get("actual", "") or ("(not reached)" if report.when == "setup" else ""),
            "status": "PASS" if report.passed else "FAIL",
            "error": error.replace("|", "\\|")[:300],
        })


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    rows = sorted(_results, key=lambda r: r["id"])
    passed = sum(r["status"] == "PASS" for r in rows)
    lines = [
        "# UniXcoder basic-functionality report",
        "",
        f"Model: `microsoft/unixcoder-base-nine` (pinned revision, CPU). Passed {passed} / {len(rows)}, "
        f"failed {len(rows) - passed}.",
        "",
        "| ID | Language | Description | Expected | Actual | Status | Error |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cells = [r["id"], r["lang"], r["desc"], r["expected"], r["actual"], r["status"], r["error"] or "—"]
        lines.append("| " + " | ".join(str(c).replace("\n", " ") for c in cells) + " |")
    lines += ["", "An embedding being produced for a language shows the pipeline runs on that input; "
                  "it does not by itself show the model officially supports the language."]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
