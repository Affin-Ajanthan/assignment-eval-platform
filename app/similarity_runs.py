"""The comparisons behind both the instructor's similarity checks and the
student self-checks. Nothing here stores results: the instructor's check
stores flags (app/main.py), a self-check stores only its own record
(app/routers/self_checks.py)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import self_checks as _self_checks
from .common import ANALYZED_EXTENSIONS, norm_name
from .db import BASE_DIR
from .evaluator.document_extraction import extract_report_text, load_extraction
from .models import Assignment, Submission
from .notebook import read_code
from .similarity import report_similarity as _report_sim
from .similarity.core import Fingerprint, compare_all, fingerprint_source, subtract_starter
from .similarity.python_cleanup import names_in
from .similarity.semantic import apply_semantic_signal, get_semantic_service, normalize_code, submissions_needing_semantic


@dataclass
class CodeSimilarityRun:
    pairs: list
    batch: object
    stats: dict
    starter_fp: object
    fingerprints: dict
    files_by_submission: dict  # submission id -> [self_checks.OwnFile]


def display_name(code_dir: Path, path: Path, name: str) -> str:
    """The file's path inside the submission, keeping the tokenizer's name
    (a notebook's code cells are read as "<name>.ipynb.py")."""
    rel = path.relative_to(code_dir).as_posix()
    return rel + name[len(path.name):] if name.startswith(path.name) else rel


def code_similarity_run(db: Session, subject_id: int, assignment_name: str,
                        submissions: list) -> CodeSimilarityRun:
    """Token (Winnowing) + semantic (UniXcoder) comparison of every pair of
    code submissions. Stores nothing: the instructor's check stores flags,
    a student self-check never does."""
    # Starter code every student was given is subtracted from each file's
    # fingerprint (same extension only) so shared boilerplate can't flag a
    # pair on its own. The semantic path below still sees the full files.
    assignment = next(
        (a for a in db.query(Assignment).filter(Assignment.subject_id == subject_id).all()
         if norm_name(a.name) == norm_name(assignment_name)),
        None,
    )
    starter_fp = None
    if assignment and assignment.starter_code and assignment.starter_code_filename:
        starter_fp = fingerprint_source("starter", assignment.starter_code_filename, assignment.starter_code)

    # 1-4: read + normalize each submission once, fingerprint it, and
    # compare every unordered pair (A-B only, never B-A) on tokens.
    fingerprints: dict[str, "Fingerprint"] = {}
    files_by_submission: dict[str, list] = {}
    semantic_sources: dict[str, str] = {}
    for submission in submissions:
        code_dir = BASE_DIR / submission.code_path
        merged = Fingerprint(submission_id=str(submission.id), filename="(all files)", token_count=0)
        normalized_files: list[str] = []
        files = []
        if code_dir.is_dir():
            # (name, source) per file; a notebook is its code cells as "<name>.ipynb.py".
            files = [(path, *read_code(path)) for path in sorted(code_dir.rglob("*"))
                     if path.is_file() and path.suffix.lower() in ANALYZED_EXTENSIONS]
        # Names each code file uses, so a top-level constant read by
        # another file isn't removed as "unused" before the semantic check.
        py_names = {path: names_in(source) for path, _, source in files}
        own_files = []
        for path, name, source in files:
            fp = subtract_starter(fingerprint_source(str(submission.id), name, source), starter_fp)
            merged.hashes |= fp.hashes
            own_files.append(_self_checks.OwnFile(name=display_name(code_dir, path, name),
                                                  source=source, hashes=set(fp.hashes)))
            merged.token_count += fp.token_count
            external = set().union(*(names for other, names in py_names.items() if other != path))
            normalized_files.append(normalize_code(source, name, external))
        fingerprints[str(submission.id)] = merged
        files_by_submission[str(submission.id)] = own_files
        semantic_sources[str(submission.id)] = "\n".join(f for f in normalized_files if f)

    pairs = compare_all(fingerprints)

    # 5-7: UniXcoder as an extra signal. The expensive step -- model
    # inference -- runs once per submission (cached by content), and
    # only for submissions in at least one pair the token check didn't
    # already flag; pair scores are then cosine similarities between
    # the stored vectors. A failure here leaves the token results intact.
    needed = submissions_needing_semantic(pairs)
    batch = get_semantic_service().embed_submissions(
        {sid: text for sid, text in semantic_sources.items() if sid in needed}
    )
    stats = apply_semantic_signal(pairs, batch.embeddings) if batch.status == "ok" else {}
    return CodeSimilarityRun(pairs=pairs, batch=batch, stats=stats, starter_fp=starter_fp,
                             fingerprints=fingerprints, files_by_submission=files_by_submission)


def report_similarity_text(submission: Submission) -> tuple[Optional[str], Optional[str]]:
    """(text, None) for a report the similarity check can compare, else
    (None, why not). PDFs are read page by page (so running headers and
    footers are dropped); DOCX reports through the MarkItDown extraction."""
    if not submission.report_path:
        return None, "No report submitted"
    path = BASE_DIR / submission.report_path
    if not path.is_file():
        return None, "Report file not found"
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _report_sim.clean_report_pages(_report_sim.extract_pdf_pages(path))
        elif suffix == ".docx":
            extraction = load_extraction(path) or extract_report_text(path)
            if not extraction.ok:
                return None, f"Could not read the DOCX ({extraction.status})"
            text = _report_sim.clean_report_pages([extraction.text])
        else:
            return None, f"Report is not a PDF or DOCX ({suffix or 'no extension'})"
    except Exception as exc:  # corrupt / encrypted document: compare the rest
        return None, f"Could not read the {suffix.lstrip('.').upper()} ({exc.__class__.__name__})"
    if len(text.split()) < _report_sim.MIN_REPORT_WORDS:
        return None, (f"Too little text to compare (under {_report_sim.MIN_REPORT_WORDS} words; "
                      "a scanned PDF has no extractable text)")
    return text, None
