"""
Code pipeline: static analysis (plan diagram node D1).

Pure-stdlib (``ast``) static analysis for Python submissions: cyclomatic
complexity, docstring coverage, naming style, and a few common smells.
Produces both machine-readable metrics (fed into rubric grading and
cross-modal consistency) and a human-readable issue list (fed into the
instructor dashboard).

Only Python is analyzed in depth here; other languages fall back to
line-count/comment-density metrics only (the similarity checker's
generic tokenizer already handles cross-language *similarity*, which is
a separate concern from *quality*).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

_SNAKE_CASE_RE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
_DECISION_NODES = (
    ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Assert,
    ast.BoolOp, ast.comprehension,
)


@dataclass
class FunctionInfo:
    name: str
    lineno: int
    complexity: int
    has_docstring: bool
    length: int  # lines of the function body


@dataclass
class CodeReport:
    filename: str
    language: str
    function_count: int = 0
    class_count: int = 0
    functions: list[FunctionInfo] = field(default_factory=list)
    docstring_coverage: float = 0.0
    avg_complexity: float = 0.0
    naming_violations: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    quality_score: int = 0  # 0-100, heuristic
    parse_error: str | None = None

    @property
    def identifiers(self) -> set[str]:
        """Function/class names -- used by cross_modal to check whether
        the report/video mention what the code actually implements."""
        return {f.name for f in self.functions}


def _complexity(node: ast.AST) -> int:
    """McCabe-style cyclomatic complexity: 1 + one per decision point."""
    count = 1
    for child in ast.walk(node):
        if isinstance(child, _DECISION_NODES):
            count += 1
        elif isinstance(child, ast.BoolOp):
            count += len(child.values) - 1
    return count


def analyze_python(source: str, filename: str = "<submission>") -> CodeReport:
    report = CodeReport(filename=filename, language="python")
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        report.parse_error = f"{exc.__class__.__name__}: {exc.msg} (line {exc.lineno})"
        report.issues.append(f"file does not parse as valid Python: {report.parse_error}")
        return report

    functions: list[FunctionInfo] = []
    class_count = 0
    naming_violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_count += 1
            if not _SNAKE_CASE_RE.match(node.name) and not node.name[0].isupper():
                naming_violations.append(f"class '{node.name}' is not PascalCase or snake_case")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            length = max(end_line - node.lineno + 1, 1)
            functions.append(FunctionInfo(
                name=node.name,
                lineno=node.lineno,
                complexity=_complexity(node),
                has_docstring=ast.get_docstring(node) is not None,
                length=length,
            ))
            if not _SNAKE_CASE_RE.match(node.name):
                naming_violations.append(f"function '{node.name}' is not snake_case")
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            report.issues.append(f"bare 'except:' at line {node.lineno} (catches everything, including typos)")

    report.functions = functions
    report.function_count = len(functions)
    report.class_count = class_count
    report.naming_violations = naming_violations
    report.docstring_coverage = (
        sum(1 for f in functions if f.has_docstring) / len(functions) if functions else 0.0
    )
    report.avg_complexity = (
        sum(f.complexity for f in functions) / len(functions) if functions else 0.0
    )

    long_lines = [i + 1 for i, line in enumerate(source.splitlines()) if len(line) > 100]
    if long_lines:
        report.issues.append(f"{len(long_lines)} line(s) over 100 characters")
    todo_count = len(re.findall(r"#\s*(TODO|FIXME)\b", source, re.IGNORECASE))
    if todo_count:
        report.issues.append(f"{todo_count} TODO/FIXME comment(s) left in submitted code")
    high_complexity = [f for f in functions if f.complexity > 10]
    for f in high_complexity:
        report.issues.append(f"function '{f.name}' has high cyclomatic complexity ({f.complexity})")

    # Heuristic 0-100 quality score: start at 100, deduct for smells.
    score = 100
    score -= min(40, len(high_complexity) * 10)
    score -= min(20, len(naming_violations) * 5)
    score -= min(15, int((1 - report.docstring_coverage) * 15)) if functions else 0
    score -= min(15, todo_count * 5)
    score -= min(10, len(long_lines))
    report.quality_score = max(0, score)

    return report


def analyze_generic(source: str, filename: str) -> CodeReport:
    """Lightweight fallback for non-Python files: no AST, just a few
    line-based signals so the pipeline still returns something useful."""
    report = CodeReport(filename=filename, language="generic")
    lines = source.splitlines()
    todo_count = len(re.findall(r"(TODO|FIXME)\b", source))
    if todo_count:
        report.issues.append(f"{todo_count} TODO/FIXME comment(s) left in submitted code")
    long_lines = [i for i, line in enumerate(lines) if len(line) > 120]
    if long_lines:
        report.issues.append(f"{len(long_lines)} line(s) over 120 characters")
    report.quality_score = max(0, 100 - todo_count * 5 - len(long_lines))
    return report


def analyze_file(path: Path) -> CodeReport:
    path = Path(path)
    source = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".py":
        return analyze_python(source, filename=path.name)
    return analyze_generic(source, filename=path.name)


_CODE_EXTENSIONS = {".py", ".java", ".js", ".ts", ".c", ".cpp", ".go", ".rb"}


def read_sources(directory: Path, extensions: set[str] | None = None,
                 max_chars_per_file: int = 4000, max_total_chars: int = 8000) -> dict[str, str]:
    """Source text of every code file under a submission directory, as
    {relative path: text}, truncated so it fits in an LLM prompt. Used to
    show a grader the actual code, not only the metrics."""
    extensions = extensions or _CODE_EXTENSIONS
    directory = Path(directory)
    sources: dict[str, str] = {}
    remaining = max_total_chars
    for path in sorted(directory.rglob("*")):
        if remaining <= 0:
            break
        if path.is_file() and path.suffix.lower() in extensions:
            text = path.read_text(encoding="utf-8", errors="ignore")
            limit = min(max_chars_per_file, remaining)
            if len(text) > limit:
                text = text[:limit] + "\n... [truncated]"
            sources[path.relative_to(directory).as_posix()] = text
            remaining -= limit
    return sources


def analyze_directory(directory: Path, extensions: set[str] | None = None) -> list[CodeReport]:
    """Analyze every code file under a submission directory (recursive)."""
    extensions = extensions or _CODE_EXTENSIONS
    directory = Path(directory)
    reports = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            reports.append(analyze_file(path))
    return reports
