"""
Optional sandboxed execution of student Python code.

The LLM grader can only *read* code, so it cannot tell whether it runs.
This module runs each ``.py`` file in a throw-away Docker container and
reports the real exit code / stdout / stderr, which the grading prompt then
presents as an EXECUTION RESULT the model may cite.

Safety rules -- student code is untrusted:

- **Off by default.** Enable with ``CODE_SANDBOX=docker``.
- **Docker only.** If Docker is not usable, nothing is executed
  (``SandboxUnavailable``); there is deliberately no "just run it locally"
  fallback.
- The container has no network, a read-only root filesystem, the code
  mounted read-only, all Linux capabilities dropped, an unprivileged user,
  and CPU / memory / process limits, plus a hard time limit.

The command runner is injectable so the logic is unit-tested without
Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_IMAGE = os.environ.get("CODE_SANDBOX_IMAGE", "python:3.12-slim")
DEFAULT_TIMEOUT = 10  # seconds the student's program may run
MAX_FILES = 3  # run at most this many .py files per submission
MAX_OUTPUT_CHARS = 1000  # per stream, so a noisy program cannot flood the prompt

# runner(command, timeout_seconds) -> (returncode, stdout, stderr); may raise
# subprocess.TimeoutExpired.
Runner = Callable[[list[str], float], tuple[int, str, str]]


class SandboxUnavailable(RuntimeError):
    """Docker is not installed or its engine is not running."""


@dataclass
class ExecutionResult:
    filename: str
    status: str  # ok | error | timeout
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""


def sandbox_enabled() -> bool:
    return os.environ.get("CODE_SANDBOX", "off").strip().lower() == "docker"


def _subprocess_runner(command: list[str], timeout: float) -> tuple[int, str, str]:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


def docker_available(runner: Runner = _subprocess_runner) -> bool:
    if runner is _subprocess_runner and shutil.which("docker") is None:
        return False
    try:
        code, _out, _err = runner(["docker", "version", "--format", "{{.Server.Version}}"], 10)
    except Exception:
        return False
    return code == 0


def build_command(name: str, code_dir: Path, relative_file: str, timeout: int, image: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
        "--read-only", "--tmpfs", "/tmp",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{code_dir}:/work:ro", "-w", "/work",
        image,
        "timeout", str(timeout), "python", relative_file,
    ]


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n... [truncated]"


def run_python_files(code_dir: Path, *, runner: Runner = _subprocess_runner, timeout: int = DEFAULT_TIMEOUT,
                     image: str = DEFAULT_IMAGE) -> list[ExecutionResult]:
    """Run each .py file under `code_dir` in the sandbox. Raises
    SandboxUnavailable (and runs nothing) when Docker cannot be used."""
    if not docker_available(runner):
        raise SandboxUnavailable("Docker is not available, so the code was not executed")

    code_dir = Path(code_dir).resolve()
    files = [p for p in sorted(code_dir.rglob("*.py")) if p.is_file()][:MAX_FILES]
    results: list[ExecutionResult] = []
    for path in files:
        rel = path.relative_to(code_dir).as_posix()
        name = f"sandbox-{uuid.uuid4().hex[:12]}"
        command = build_command(name, code_dir, rel, timeout, image)
        try:
            code, out, err = runner(command, timeout + 30)  # slack for container start-up
        except subprocess.TimeoutExpired:
            try:  # the CLI timed out, not necessarily the container: stop it
                runner(["docker", "kill", name], 10)
            except Exception:
                pass
            results.append(ExecutionResult(rel, "timeout", None, "", f"no result within {timeout + 30}s"))
            continue
        if code == 124:  # coreutils `timeout` -> the program hit its time limit
            status = "timeout"
        else:
            status = "ok" if code == 0 else "error"
        results.append(ExecutionResult(rel, status, code, _clip(out), _clip(err)))
    return results


def format_for_prompt(results: list[ExecutionResult]) -> str:
    lines = []
    for r in results:
        head = {"ok": "ran without errors", "error": f"crashed (exit code {r.exit_code})",
                "timeout": "did not finish within the time limit"}[r.status]
        lines.append(f"--- {r.filename}: {head} ---")
        if r.stdout:
            lines.append(f"stdout:\n{r.stdout}")
        if r.stderr:
            lines.append(f"stderr:\n{r.stderr}")
    return "\n".join(lines)
