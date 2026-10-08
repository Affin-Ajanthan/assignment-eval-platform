"""
Report text extraction with Microsoft MarkItDown
(https://github.com/microsoft/markitdown, the ``markitdown`` package).

MarkItDown is ONLY the document-conversion layer here: PDF/DOCX in,
Markdown out. It does not grade, score similarity or judge anything. Its
output feeds the cross-modal semantic consistency check
(``semantic_consistency.py``), which does the comparing with MiniLM:

    PDF / DOCX -> MarkItDown -> Markdown -> plain text -> chunks -> all-MiniLM-L6-v2

The existing report analysis (``report_analysis.py``: AI-text heuristic,
figure/image check, the text the rubric grader sees) keeps its own
PyMuPDF/python-docx extraction, so grading is unaffected by this module.

Uploaded reports are untrusted input:

- only ``.pdf`` / ``.docx`` are accepted, and the file's actual bytes must
  match (``%PDF-`` header, or a ZIP containing ``word/document.xml``);
- size is capped (``REPORT_MAX_BYTES``, default 25 MB), and a DOCX's
  uncompressed size is capped too (zip-bomb guard);
- conversion is local and offline: MarkItDown runs with only its PDF and
  DOCX converters registered (no plugins, no LLM client, no Azure
  Document Intelligence), via ``convert_local`` (no URL fetching);
  nothing in the document is executed;
- conversion runs with a time limit (``REPORT_EXTRACTION_TIMEOUT``,
  default 60 s) so a pathological file can't stall an evaluation.

``extract_report_text`` never raises: every problem becomes a status
("empty", "failed", "unsupported") that the instructor sees, and the rest
of the evaluation carries on without the report text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

BACKEND = "markitdown"
SUPPORTED_REPORT_EXTENSIONS = {".pdf", ".docx"}
# Browsers vary (and some send octet-stream), so the MIME type is only
# checked against this allow-list; the file's bytes are the real check.
ALLOWED_REPORT_MIME_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "application/zip",
    "application/x-zip-compressed",
    "",
}
DOCX_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

# Sidecar files written next to an upload (uploads/<uuid>/...).
EXTRACTED_MARKDOWN_NAME = "report_extracted.md"
EXTRACTION_META_NAME = "report_extraction.json"


def report_max_bytes() -> int:
    return _env_int("REPORT_MAX_BYTES", 25 * 1024 * 1024)


def extraction_timeout() -> float:
    return float(_env_int("REPORT_EXTRACTION_TIMEOUT", 60))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --------------------------------------------------------------------------
# Validation (used at upload time, and again before conversion)
# --------------------------------------------------------------------------


class ReportValidationError(ValueError):
    """Raised with a message that is safe to show the student."""


def sniff_report_type(path: Path) -> str | None:
    """'pdf' or 'docx' from the file's bytes, or None if it's neither."""
    path = Path(path)
    with path.open("rb") as f:
        head = f.read(1024)
    if b"%PDF-" in head:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                total = sum(info.file_size for info in zf.infolist())
        except (zipfile.BadZipFile, OSError):
            return None
        if "word/document.xml" in names and "[Content_Types].xml" in names and total <= DOCX_MAX_UNCOMPRESSED_BYTES:
            return "docx"
    return None


def validate_report_file(path: Path, filename: str, content_type: str | None = None) -> None:
    """Check an uploaded report; raises ``ReportValidationError``."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_REPORT_EXTENSIONS:
        raise ReportValidationError("Report must be a PDF or DOCX file.")
    if (content_type or "").split(";")[0].strip().lower() not in ALLOWED_REPORT_MIME_TYPES:
        raise ReportValidationError("Report must be a PDF or DOCX file.")
    size = Path(path).stat().st_size
    if size == 0:
        raise ReportValidationError("The report file is empty.")
    if size > report_max_bytes():
        raise ReportValidationError(f"The report is too large (limit {report_max_bytes() // (1024 * 1024)} MB).")
    if sniff_report_type(path) != ext.lstrip("."):
        raise ReportValidationError("The report file doesn't look like a valid PDF or DOCX document.")


# --------------------------------------------------------------------------
# Markdown -> plain text for embedding
# --------------------------------------------------------------------------

_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_TABLE_RULE_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`+|~~)(?=\S)(.+?)(?<=\S)\1")


def markdown_to_text(markdown: str) -> str:
    """Strip Markdown syntax but keep every word of content: image alt text
    and link text stay, URLs, table rules, heading/list markers, emphasis
    and HTML tags go. Line structure is kept for the next cleanup step."""
    lines = []
    for line in markdown.splitlines():
        if _TABLE_RULE_RE.match(line):
            continue
        line = _IMAGE_RE.sub(r"\1", line)
        line = _LINK_RE.sub(r"\1", line)
        line = _HTML_TAG_RE.sub(" ", line)
        line = _HEADING_RE.sub("", line)
        line = _LIST_RE.sub("", line)
        line = line.replace("|", " ")
        for _ in range(2):  # nested emphasis, e.g. **_bold italic_**
            line = _EMPHASIS_RE.sub(r"\2", line)
        line = line.strip()
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        lines.append(line)
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


@dataclass
class ReportExtraction:
    status: str  # "ok" | "empty" | "failed" | "unsupported"
    backend: str = BACKEND
    text: str = ""  # plain text for embedding (not stored in the meta file)
    chars: int = 0
    words: int = 0
    error: str | None = None
    extracted_at: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def meta(self) -> dict:
        """Everything except the text itself (for API responses / storage)."""
        d = asdict(self)
        d.pop("text")
        return d


_converter = None
_converter_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="markitdown")


def _get_converter():
    """One shared MarkItDown instance with ONLY its PDF and DOCX converters
    registered: no plugins, no LLM client, no cloud document service.

    Restricting the converters matters: with all built-ins enabled, a
    corrupted PDF that the PDF converter rejects falls through to the
    plain-text converter, which "succeeds" by returning the file's raw
    bytes as the report text. It also keeps every other converter
    (HTML, ZIP, audio, ...) out of reach of uploaded files."""
    global _converter
    with _converter_lock:
        if _converter is None:
            from markitdown import MarkItDown
            from markitdown.converters import DocxConverter, PdfConverter

            converter = MarkItDown(enable_builtins=False, enable_plugins=False)
            converter.register_converter(PdfConverter())
            converter.register_converter(DocxConverter())
            _converter = converter
        return _converter


def _convert(path: Path) -> str:
    from markitdown import StreamInfo

    result = _get_converter().convert_local(path, stream_info=StreamInfo(extension=path.suffix.lower()))
    return result.text_content or ""


def extract_report_text(path: Path) -> ReportExtraction:
    """Convert a PDF/DOCX report to text with MarkItDown. Never raises."""
    path = Path(path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        ext = path.suffix.lower()
        if ext not in SUPPORTED_REPORT_EXTENSIONS:
            return ReportExtraction("unsupported", error=f"unsupported report type '{ext or '(none)'}'",
                                    extracted_at=now)
        if not path.is_file():
            return ReportExtraction("failed", error="report file not found", extracted_at=now)
        if path.stat().st_size > report_max_bytes():
            return ReportExtraction("unsupported", error="report exceeds the size limit", extracted_at=now)
        if sniff_report_type(path) != ext.lstrip("."):
            return ReportExtraction("unsupported", error=f"file content is not a valid {ext[1:].upper()} document",
                                    extracted_at=now)

        future = _executor.submit(_convert, path)
        try:
            markdown = future.result(timeout=extraction_timeout())
        except FutureTimeout:
            return ReportExtraction("failed", error=f"conversion timed out after {extraction_timeout():.0f}s",
                                    extracted_at=now)
    except Exception as exc:
        # MarkItDown's message is "File conversion failed...:\n - <Converter> threw <Error>..."; the
        # second line is the informative one.
        lines = str(exc).strip().splitlines()
        detail = next((l.strip(" -") for l in lines[1:] if l.strip()), lines[0] if lines else "")
        log.warning("MarkItDown could not convert %s: %s", path.name, exc)
        return ReportExtraction("failed", error=f"{exc.__class__.__name__}: {detail}"[:300], extracted_at=now)

    text = markdown_to_text(markdown)
    words = len(text.split())
    if not words:
        return ReportExtraction("empty", error="no extractable text (the document may be scanned images only)",
                                extracted_at=now)
    return ReportExtraction("ok", text=text, chars=len(text), words=words, extracted_at=now)


# --------------------------------------------------------------------------
# Sidecar storage next to an upload
# --------------------------------------------------------------------------


def _sidecar_dir(report_path: Path) -> Path:
    # uploads/<uuid>/report/<file>  ->  uploads/<uuid>/
    return Path(report_path).parent.parent


def save_extraction(report_path: Path, extraction: ReportExtraction) -> None:
    folder = _sidecar_dir(report_path)
    (folder / EXTRACTION_META_NAME).write_text(json.dumps(extraction.meta()), encoding="utf-8")
    if extraction.ok:
        (folder / EXTRACTED_MARKDOWN_NAME).write_text(extraction.text, encoding="utf-8")


def load_extraction(report_path: Path) -> ReportExtraction | None:
    """The extraction stored at upload time, or None if there isn't one
    (older submission, or the background task hasn't finished)."""
    folder = _sidecar_dir(report_path)
    try:
        meta = json.loads((folder / EXTRACTION_META_NAME).read_text(encoding="utf-8"))
        text = (folder / EXTRACTED_MARKDOWN_NAME).read_text(encoding="utf-8") if meta.get("status") == "ok" else ""
        return ReportExtraction(text=text, **meta)
    except (OSError, ValueError, TypeError):
        return None


def extract_and_store(report_path: Path) -> ReportExtraction:
    """Background task run after upload: extract once and keep the result."""
    extraction = extract_report_text(report_path)
    try:
        save_extraction(report_path, extraction)
    except OSError as exc:
        log.warning("Could not store report extraction for %s: %s", report_path, exc)
    return extraction
