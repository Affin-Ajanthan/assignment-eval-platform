"""The comparisons behind both the instructor's similarity checks and the
student self-checks. Nothing here stores results: the instructor's check
stores flags (app/main.py), a self-check stores only its own record
(app/routers/self_checks.py)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import self_checks as _self_checks
from .common import ANALYZED_EXTENSIONS, norm_name, on_flag
from .db import BASE_DIR
from .evaluator.document_extraction import extract_report_text, load_extraction
from .models import Assignment, Submission
from .notebook import read_code
from .similarity import report_similarity as _report_sim
from .similarity.core import (Fingerprint, common_hashes, compare_all, fingerprint_source, matched_line_ranges,
                              subtract_starter)
from .similarity.python_cleanup import names_in
from .similarity.semantic import (apply_semantic_signal, get_semantic_service, normalize_code, strip_junk,
                                  submissions_needing_semantic)


@dataclass
class CodeSimilarityRun:
    pairs: list
    batch: object
    stats: dict
    starter_fp: object
    fingerprints: dict
    files_by_submission: dict  # submission id -> [self_checks.OwnFile]
    common_removed: int = 0  # distinct fingerprints dropped as common to the class


def remove_common_code(fingerprints: dict, files_by_submission: dict) -> int:
    """Drop the fingerprints most submissions share (core.common_hashes, the
    rule the report check uses too) -- the patterns every solution to the task
    shares (menu loops, input helpers, file saving). Returns how many distinct
    ones went."""
    common = common_hashes([fp.hashes for fp in fingerprints.values()])
    for fp in fingerprints.values():
        fp.hashes -= common
    for files in files_by_submission.values():
        for f in files:
            f.hashes -= common
    return len(common)


def display_name(code_dir: Path, path: Path, name: str) -> str:
    """The file's path inside the submission, keeping the tokenizer's name
    (a notebook's code cells are read as "<name>.ipynb.py")."""
    rel = path.relative_to(code_dir).as_posix()
    return rel + name[len(path.name):] if name.startswith(path.name) else rel


def find_assignment(db: Session, subject_id: int, assignment_name: str,
                    submissions: list) -> Optional[Assignment]:
    """The assignment these submissions were made to (its settings: starter
    code, template PDF, ignore common code), or None. Read from the
    submissions' own ``assignment_id``; by name only for submissions made
    before assignments existed, which have none."""
    ids = Counter(s.assignment_id for s in submissions if s.assignment_id is not None)
    for assignment_id, _ in ids.most_common():
        assignment = db.get(Assignment, assignment_id)
        if assignment is not None and assignment.subject_id == subject_id:
            return assignment
    return next(
        (a for a in db.query(Assignment).filter(Assignment.subject_id == subject_id).all()
         if norm_name(a.name) == norm_name(assignment_name)),
        None,
    )


def code_similarity_run(db: Session, subject_id: int, assignment_name: str,
                        submissions: list) -> CodeSimilarityRun:
    """Token (Winnowing) + semantic (UniXcoder) comparison of every pair of
    code submissions. Stores nothing: the instructor's check stores flags,
    a student self-check never does. Code most of the class shares is left
    out when the assignment's ``ignore_common_code`` option is on (default)."""
    starter_fp, remove_common = _code_settings(db, subject_id, assignment_name, submissions)
    return code_similarity_for_dirs({str(s.id): BASE_DIR / s.code_path for s in submissions}, starter_fp,
                                    remove_common=remove_common)


def _code_settings(db: Session, subject_id: int, assignment_name: str, submissions: list):
    """(starter-code fingerprint or None, whether to drop code most of the class shares) for this assignment.
    Starter code every student was given is subtracted from each file's fingerprint (same extension only) so
    shared boilerplate can't flag a pair on its own; the semantic path still sees the full files."""
    assignment = find_assignment(db, subject_id, assignment_name, submissions)
    starter_fp = None
    if assignment and assignment.starter_code and assignment.starter_code_filename:
        starter_fp = fingerprint_source("starter", assignment.starter_code_filename, assignment.starter_code)
    return starter_fp, (on_flag(assignment.ignore_common_code) if assignment else True)


def code_similarity_for_dirs(code_dirs: dict[str, Path], starter_fp=None,
                             remove_common: bool = False) -> CodeSimilarityRun:
    """The comparison itself, on code folders keyed by submission id: what
    code_similarity_run uses, and what scripts/evaluate_self_check.py runs on
    labelled test sets without a database."""
    # 1-4: read + normalize each submission once, fingerprint it, and
    # compare every unordered pair (A-B only, never B-A) on tokens.
    fingerprints, files_by_submission, semantic_sources, common_removed = _fingerprint_dirs(
        code_dirs, starter_fp, remove_common)
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
                             fingerprints=fingerprints, files_by_submission=files_by_submission,
                             common_removed=common_removed)


def _fingerprint_dirs(code_dirs: dict[str, Path], starter_fp, remove_common: bool):
    """Each submission's files read once and fingerprinted: (fingerprints, files_by_submission,
    semantic_sources, common_removed). The token part of the check, without the model."""
    fingerprints: dict[str, "Fingerprint"] = {}
    files_by_submission: dict[str, list] = {}
    semantic_sources: dict[str, str] = {}
    for sid, code_dir in code_dirs.items():
        merged = Fingerprint(submission_id=sid, filename="(all files)", token_count=0)
        normalized_files: list[str] = []
        files = []
        if code_dir.is_dir():
            # (name, source) per file; a notebook is its code cells as "<name>.ipynb.py".
            files = [(path, *read_code(path)) for path in sorted(code_dir.rglob("*"))
                     if path.is_file() and path.suffix.lower() in ANALYZED_EXTENSIONS]
        # Names each code file uses, so a top-level constant read by
        # another file isn't removed as "unused" by the junk-code cleanup.
        py_names = {path: names_in(source) for path, _, source in files}
        own_files = []
        for path, name, source in files:
            external = set().union(*(names for other, names in py_names.items() if other != path))
            # Fingerprints come from the code without junk (unused variables,
            # dead branches), so padding a copy doesn't lower its Jaccard. Removed
            # code leaves its line breaks, so highlights keep the original line numbers.
            cleaned = strip_junk(source, name, external, keep_lines=True)
            fp = subtract_starter(fingerprint_source(sid, name, cleaned), starter_fp)
            merged.hashes |= fp.hashes
            own_files.append(_self_checks.OwnFile(name=display_name(code_dir, path, name),
                                                  source=source, hashes=set(fp.hashes),
                                                  fingerprinted=cleaned))
            merged.token_count += fp.token_count
            normalized_files.append(normalize_code(source, name, external))
        fingerprints[sid] = merged
        files_by_submission[sid] = own_files
        semantic_sources[sid] = "\n".join(f for f in normalized_files if f)

    common_removed = remove_common_code(fingerprints, files_by_submission) if remove_common else 0
    return fingerprints, files_by_submission, semantic_sources, common_removed


# The compare view shows at most this many lines of one file; the matched ranges are given for the whole file.
MAX_COMPARE_LINES = 2000


def code_pair_matches(db: Session, subject_id: int, assignment_name: str, submissions: list,
                      a_id: int, b_id: int) -> dict:
    """Two submissions' code side by side, for the instructor: each file with the line ranges that carry a
    fingerprint the other submission has too. Fingerprinted exactly as the check does (the whole class, so
    code most of it shares is left out the same way), but without the semantic model."""
    starter_fp, remove_common = _code_settings(db, subject_id, assignment_name, submissions)
    fingerprints, files_by_submission, _, common_removed = _fingerprint_dirs(
        {str(s.id): BASE_DIR / s.code_path for s in submissions}, starter_fp, remove_common)
    a, b = str(a_id), str(b_id)
    shared = fingerprints[a].hashes & fingerprints[b].hashes

    def side(sid: str) -> list[dict]:
        out = []
        for f in files_by_submission[sid]:
            lines = f.source.splitlines()
            fingerprinted = f.source if f.fingerprinted is None else f.fingerprinted
            ranges = matched_line_ranges(fingerprinted, f.name, shared & f.hashes)
            out.append({"name": f.name, "source": "\n".join(lines[:MAX_COMPARE_LINES]), "line_count": len(lines),
                        "truncated": len(lines) > MAX_COMPARE_LINES,
                        "ranges": [{"start": start, "end": end} for start, end in ranges]})
        return out

    return {"shared_fingerprints": len(shared), "common_code_removed": common_removed,
            "a_files": side(a), "b_files": side(b)}


def report_similarity_text(submission: Submission) -> tuple[Optional[str], Optional[str]]:
    """(text, None) for a report the similarity check can compare, else
    (None, why not). PDFs are read page by page (so running headers and
    footers are dropped); DOCX reports through the MarkItDown extraction."""
    if not submission.report_path:
        return None, "No report submitted"
    return report_text_for_path(BASE_DIR / submission.report_path)


def report_text_for_path(path: Path) -> tuple[Optional[str], Optional[str]]:
    """report_similarity_text for a file path (no database needed)."""
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


@dataclass
class ReportSimilarityRun:
    texts: dict                 # submission id -> report text, for the reports that can be compared
    skipped: list               # (submission, why its report can't be compared)
    assignment: Optional[Assignment]
    comparison: Optional[object] = None  # report_similarity.ReportComparison; None with under 2 reports


def report_similarity_run(db: Session, subject_id: int, assignment_name: str,
                          submissions: list) -> ReportSimilarityRun:
    """Word (Winnowing) + semantic (MiniLM) comparison of every pair of
    readable reports, with the assignment's template PDF cut out first: what
    both the instructor's report check and a student's report self-check
    run, so the two can't drift apart. Stores nothing."""
    from .evaluator.semantic_consistency import get_consistency_service

    texts: dict[str, str] = {}
    skipped: list = []
    for submission in sorted(submissions, key=lambda s: s.id):
        text, reason = report_similarity_text(submission)
        if text is None:
            skipped.append((submission, reason))
        else:
            texts[str(submission.id)] = text
    assignment = find_assignment(db, subject_id, assignment_name, submissions)
    run = ReportSimilarityRun(texts=texts, skipped=skipped, assignment=assignment)
    if len(texts) >= 2:
        template = assignment.report_template_text if assignment else None
        run.comparison = _report_sim.compare_reports(texts, get_consistency_service(), template_text=template)
    return run
