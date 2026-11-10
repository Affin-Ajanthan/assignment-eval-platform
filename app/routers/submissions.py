"""Students' submissions, and downloading the files in them.

Moved out of app/main.py (Submissions, Submitted files). Included in app/main.py."""

from __future__ import annotations

import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import code_languages as _langs
from ..auth import get_current_user, instructor_subject_ids, require_student, student_subject_ids
from ..common import ANALYZED_EXTENSIONS as _ANALYZED_EXTENSIONS, norm_name as _norm_name, utcnow_naive as _utcnow_naive
from ..db import BASE_DIR, UPLOAD_DIR, get_db
from ..evaluator.document_extraction import (
    ReportValidationError,
    SUPPORTED_REPORT_EXTENSIONS,
    extract_and_store,
    report_max_bytes,
    validate_report_file,
)
from ..models import Assignment, Submission, User
from ..route_helpers import _discard_derived_results, _marks_released, _remove_upload_part
from ..schemas import SubmissionFileOut, SubmissionOut


router = APIRouter()


def _can_view_submission(user: User, submission: Submission, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return submission.student_id == user.id
    if user.role == "instructor":
        return submission.subject_id in instructor_subject_ids(db, user)
    return False


def _student_submission_out(submission: Submission, now: datetime) -> SubmissionOut:
    """A submission as its student sees it: no mark before the release date."""
    out = SubmissionOut.model_validate(submission)
    if not _marks_released(submission, now):
        out = out.model_copy(update={"status": "submitted", "final_mark": None, "max_mark": None, "raw_mark": None})
    return out


# Uploads are untrusted input: every file is checked for type and size,
# saved under a sanitized name inside its own uploads/<uuid>/ folder, and
# never executed. A rejected upload removes everything already written.
# Only languages the code checks actually read: a file type that is stored but
# never compared (TypeScript, Kotlin, Swift, Rust, JSX, ...) would leave a
# submission silently unchecked, so it is refused at upload instead.
_UPLOAD_CODE_EXTENSIONS = _ANALYZED_EXTENSIONS | {".zip"}


_ACCEPTED_LANGUAGES_TEXT = (
    "Python (.py, .ipynb), Java (.java), JavaScript (.js), C (.c, .h), "
    "C++ (.cpp, .cc, .cxx, .h, .hpp, .hh, .hxx), C# (.cs), Go (.go), Ruby (.rb), PHP (.php)"
)


_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


_CODE_MAX_BYTES = 50 * 1024 * 1024


_ZIP_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


_ZIP_MAX_ENTRIES = 5000


_VIDEO_MAX_BYTES = 1024 * 1024 * 1024


_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


class _UploadRejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _submission_dir(submission_uuid: str) -> Path:
    d = UPLOAD_DIR / submission_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(name: Optional[str], fallback: str = "upload") -> str:
    """Last path component only (either slash style), restricted to a
    plain character set, never a dotfile -- so a crafted name like
    '../../app/main.py' or 'C:/Windows/x' can only ever land inside the
    submission's own folder."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = _UNSAFE_NAME_CHARS.sub("_", base).strip(" .")
    return base or fallback


def _write_limited(file: UploadFile, dest: Path, limit: int, what: str) -> None:
    written = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                raise _UploadRejected(413, f"The {what} is too large (limit {limit // (1024 * 1024)} MB).")
            out.write(chunk)


def _wrong_language(assignment: Assignment, what: str) -> _UploadRejected:
    return _UploadRejected(
        400,
        f"'{assignment.name}' must be written in {_langs.describe(assignment.code_languages)}. "
        f"{what} Upload your code in the required language.",
    )


def _save_code_upload(file: UploadFile, submission_uuid: str, assignment: Optional[Assignment] = None) -> str:
    """Saves the code upload under uploads/<uuid>/code/. A .zip is
    extracted in place so the evaluator's static/similarity analysis
    (which walks a directory) works the same whether the student
    uploaded one file or a whole project. When the assignment requires
    particular languages, code in any other language is refused."""
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in _UPLOAD_CODE_EXTENSIONS:
        raise _UploadRejected(
            400,
            f"'{filename}' can't be checked: {suffix or 'files without an extension'} is not a supported "
            f"language. Upload a .zip or a single file in one of: {_ACCEPTED_LANGUAGES_TEXT}.",
        )
    allowed = _langs.allowed_extensions(assignment.code_languages if assignment else None)
    if allowed is not None and suffix != ".zip" and suffix not in allowed:
        raise _wrong_language(assignment, f"'{filename}' is {_langs.language_of(suffix)}.")
    code_dir = _submission_dir(submission_uuid) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)

    if filename.lower().endswith(".zip"):
        zip_path = _submission_dir(submission_uuid) / "code-upload.zip"
        _write_limited(file, zip_path, _CODE_MAX_BYTES, "code archive")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                infos = zf.infolist()
                if len(infos) > _ZIP_MAX_ENTRIES or sum(i.file_size for i in infos) > _ZIP_MAX_UNCOMPRESSED_BYTES:
                    raise _UploadRejected(413, "The code archive is too large once unpacked.")
                root = code_dir.resolve()
                for info in infos:
                    target = (code_dir / info.filename).resolve()
                    if info.is_dir() or not target.is_relative_to(root):
                        continue  # skip directories and any entry pointing outside code/
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile:
            raise _UploadRejected(400, "The code archive is not a valid .zip file.")
        finally:
            zip_path.unlink(missing_ok=True)
        # Other files (README, data, images) may come along, but at least one
        # file must be code the checks can read.
        if not any(p.is_file() and p.suffix.lower() in _ANALYZED_EXTENSIONS for p in code_dir.rglob("*")):
            raise _UploadRejected(
                400,
                f"'{filename}' contains no code in a supported language, so it can't be checked. "
                f"Include your source files in one of: {_ACCEPTED_LANGUAGES_TEXT}.",
            )
        if allowed is not None:
            # Non-code files (README, data) are fine; code in another language is not.
            others = sorted(
                p.relative_to(code_dir).as_posix() for p in code_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in _ANALYZED_EXTENSIONS and p.suffix.lower() not in allowed
            )
            if others:
                shown = ", ".join(f"{name} ({_langs.language_of(Path(name).suffix.lower())})" for name in others[:5])
                more = f" and {len(others) - 5} more" if len(others) > 5 else ""
                raise _wrong_language(assignment, f"'{filename}' contains code in another language: {shown}{more}.")
    else:
        _write_limited(file, code_dir / filename, _CODE_MAX_BYTES, "code file")

    return str(code_dir.relative_to(BASE_DIR))


def _save_file_upload(file: UploadFile, submission_uuid: str, kind: str, limit: int, what: str) -> Path:
    sub_dir = _submission_dir(submission_uuid) / kind
    sub_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_dir / _safe_filename(file.filename, fallback=kind)
    _write_limited(file, dest, limit, what)
    return dest


def _save_report_upload(file: UploadFile, submission_uuid: str) -> str:
    if Path(_safe_filename(file.filename)).suffix.lower() not in SUPPORTED_REPORT_EXTENSIONS:
        raise _UploadRejected(400, "Report must be a PDF or DOCX file.")
    dest = _save_file_upload(file, submission_uuid, "report", report_max_bytes(), "report")
    try:
        validate_report_file(dest, dest.name, file.content_type)
    except ReportValidationError as exc:
        raise _UploadRejected(400, str(exc))
    return str(dest.relative_to(BASE_DIR))


def _save_video_upload(file: UploadFile, submission_uuid: str) -> str:
    if Path(_safe_filename(file.filename)).suffix.lower() not in _VIDEO_EXTENSIONS:
        raise _UploadRejected(400, "Presentation video must be an MP4, MOV, AVI, MKV, WEBM or M4V file.")
    dest = _save_file_upload(file, submission_uuid, "video", _VIDEO_MAX_BYTES, "video")
    return str(dest.relative_to(BASE_DIR))


_TYPE_LABELS = {"code": "code (.zip or a source file)", "report": "report (PDF or DOCX)", "video": "video"}


def _accepted_label(assignment: Assignment) -> str:
    return ", ".join(_TYPE_LABELS[t] for t in assignment.accepted_types())


def _reject_unaccepted_types(assignment: Assignment, **uploads) -> None:
    """Refuse files of a kind the instructor did not enable for this assignment."""
    accepted = set(assignment.accepted_types())
    rejected = [kind for kind, upload in uploads.items() if upload and kind not in accepted]
    if rejected:
        raise HTTPException(
            400,
            f"'{assignment.name}' accepts only: {_accepted_label(assignment)}. "
            f"Remove the {', '.join(rejected)} file(s) you uploaded.",
        )


@router.post("/submissions", response_model=SubmissionOut)
def create_submission(
    background_tasks: BackgroundTasks,
    subject_id: int = Form(...),
    # Either identifies the assignment; assignment_name is matched against
    # the subject's assignments (case/spacing-insensitive).
    assignment_id: Optional[int] = Form(None),
    assignment_name: Optional[str] = Form(None),
    code: Optional[UploadFile] = File(None),
    report: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    if subject_id not in student_subject_ids(db, student):
        raise HTTPException(403, "You are not enrolled in this subject")
    assignment = _resolve_assignment_for_submission(db, subject_id, assignment_id, assignment_name)
    _require_open(assignment)
    if len(assignment.questions) > 1:
        # Each task is answered by its own file, which only the challenge's own code page makes.
        raise HTTPException(
            400, "This code challenge has several tasks: answer them on its code page, one at a time.")
    code, report, video = (f if f is not None and f.filename else None for f in (code, report, video))
    if not (code or report or video):
        raise HTTPException(400, f"Upload at least one file: {_accepted_label(assignment)}.")
    _reject_unaccepted_types(assignment, code=code, report=report, video=video)
    existing = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id, Submission.student_id == student.id)
        .first()
    )
    if existing:
        raise HTTPException(409, "You have already submitted this assignment. Use Edit submission to change your files.")

    submission_uuid = uuid.uuid4().hex[:8]
    # code_path points at a DIRECTORY (uploads/<uuid>/code/); report_path
    # and video_path point at the uploaded FILE itself.
    try:
        code_path = _save_code_upload(code, submission_uuid, assignment) if code else None
        report_path = _save_report_upload(report, submission_uuid) if report else None
        video_path = _save_video_upload(video, submission_uuid) if video else None
    except _UploadRejected as exc:
        shutil.rmtree(UPLOAD_DIR / submission_uuid, ignore_errors=True)
        raise HTTPException(exc.status, exc.message)

    submission = Submission(
        student_id=student.id,
        subject_id=subject_id,
        assignment_name=assignment.name,
        assignment_id=assignment.id,
        code_path=code_path,
        report_path=report_path,
        video_path=video_path,
    )
    submission.apply_lateness(assignment, _utcnow_naive())
    db.add(submission)
    db.commit()
    db.refresh(submission)
    if report_path:
        # Convert the report to text (MarkItDown) after the response is sent;
        # the student never waits for it or sees its outcome.
        background_tasks.add_task(extract_and_store, BASE_DIR / report_path)
    return submission


def _resolve_assignment_for_submission(
    db: Session, subject_id: int, assignment_id: Optional[int], assignment_name: Optional[str]
) -> Assignment:
    if assignment_id is not None:
        assignment = db.get(Assignment, assignment_id)
        if not assignment or assignment.subject_id != subject_id:
            raise HTTPException(404, "Assignment not found in this subject")
        return assignment
    if not (assignment_name or "").strip():
        raise HTTPException(400, "Choose the assignment you are submitting to.")
    for assignment in db.query(Assignment).filter(Assignment.subject_id == subject_id).all():
        if _norm_name(assignment.name) == _norm_name(assignment_name):
            return assignment
    raise HTTPException(404, f"There is no assignment called '{assignment_name.strip()}' in this subject.")


def _require_open(assignment: Assignment) -> None:
    """The deadline check every student write goes through. Work is taken until the deadline, then through the
    grace period and up to the accept-late-until date, when the instructor set them (it is then marked late)."""
    now = _utcnow_naive()
    if assignment.status_at(now) == "upcoming":
        raise HTTPException(403, f"'{assignment.name}' is not open for submissions yet.")
    if now > assignment.accept_until:
        raise HTTPException(403, f"The submission deadline for '{assignment.name}' has passed.")


def _own_changeable_submission(db: Session, student: User, submission_id: int, *,
                               deleting: bool = False) -> Submission:
    """The student's own submission, if they may still change it. A code challenge's code can never be
    replaced; with `deleting` it can be withdrawn while the assignment is open (it is marked from its tests at
    once, so "graded" does not stop it) unless the instructor graded it."""
    submission = db.get(Submission, submission_id)
    if not submission or submission.student_id != student.id:
        raise HTTPException(404, "Submission not found")  # never confirm other students' submissions exist
    if submission.assignment is None:
        raise HTTPException(409, "This submission isn't linked to an open assignment, so it can't be changed.")
    if submission.assignment.kind == "code_challenge":
        if not deleting:
            raise HTTPException(409, "A code challenge's code can't be changed once it is submitted. "
                                     "Delete the submission to do it again.")
        if submission.latest_grade is not None:
            raise HTTPException(409, "This submission has already been graded by your instructor and can no "
                                     "longer be deleted.")
        if submission.assignment.is_timed:
            raise HTTPException(409, "This code challenge has time limits, so a submission to it can't be deleted.")
    elif submission.status == "graded":
        raise HTTPException(409, "This submission has already been graded and can no longer be changed.")
    _require_open(submission.assignment)
    return submission


@router.put("/submissions/{submission_id}", response_model=SubmissionOut)
def update_submission(
    submission_id: int,
    background_tasks: BackgroundTasks,
    code: Optional[UploadFile] = File(None),
    report: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """Replace one or more files of the student's own submission while the
    assignment is open and before it's graded. Files not sent are kept.
    Not for a code challenge: its code cannot be replaced once it is submitted (delete it to start again)."""
    submission = _own_changeable_submission(db, student, submission_id)
    code, report, video = (f if f is not None and f.filename else None for f in (code, report, video))
    if not (code or report or video):
        raise HTTPException(400, "Choose at least one file to replace.")
    _reject_unaccepted_types(submission.assignment, code=code, report=report, video=video)

    batch = uuid.uuid4().hex[:8]
    try:
        new_code = _save_code_upload(code, batch, submission.assignment) if code else None
        new_report = _save_report_upload(report, batch) if report else None
        new_video = _save_video_upload(video, batch) if video else None
    except _UploadRejected as exc:
        shutil.rmtree(UPLOAD_DIR / batch, ignore_errors=True)
        raise HTTPException(exc.status, exc.message)

    replaced = []
    if new_code:
        replaced.append((submission.code_path, "code"))
        submission.code_path = new_code
    if new_report:
        replaced.append((submission.report_path, "report"))
        submission.report_path = new_report
    if new_video:
        replaced.append((submission.video_path, "video"))
        submission.video_path = new_video
    submission.submitted_at = datetime.now(timezone.utc)
    submission.apply_lateness(submission.assignment, _utcnow_naive())  # replacing files late makes the work late
    _discard_derived_results(db, submission.id)
    db.commit()
    db.refresh(submission)
    for rel_path, kind in replaced:
        _remove_upload_part(rel_path, kind)
    if new_report:
        background_tasks.add_task(extract_and_store, BASE_DIR / new_report)
    return submission


@router.delete("/submissions/{submission_id}")
def delete_submission(submission_id: int, student: User = Depends(require_student), db: Session = Depends(get_db)):
    """Withdraw the student's own submission while the assignment is open
    and before it's graded (a graded submission is an academic record).
    A code challenge may be deleted (and then done again) while it is open, even though its tests
    marked it at once, unless the instructor graded it."""
    submission = _own_changeable_submission(db, student, submission_id, deleting=True)
    parts = [(submission.code_path, "code"), (submission.report_path, "report"), (submission.video_path, "video")]
    _discard_derived_results(db, submission.id)
    db.delete(submission)
    db.commit()
    for rel_path, kind in parts:
        _remove_upload_part(rel_path, kind)
    return {"status": "deleted"}


@router.get("/submissions", response_model=list[SubmissionOut])
def list_submissions(
    subject_id: Optional[int] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Submission)
    if user.role == "student":
        query = query.filter(Submission.student_id == user.id)
    elif user.role == "instructor":
        allowed = instructor_subject_ids(db, user)
        query = query.filter(Submission.subject_id.in_(allowed))
    # admin sees everything

    if subject_id is not None:
        query = query.filter(Submission.subject_id == subject_id)
    if user.role == "student":
        # Filter by the status the student is shown, after held-back grades
        # are hidden, so the filter cannot reveal them either.
        now = _utcnow_naive()
        shown = [_student_submission_out(s, now) for s in query.order_by(Submission.submitted_at.desc()).all()]
        return [s for s in shown if not status or s.status == status]
    if status:
        query = query.filter(Submission.status == status)
    return query.order_by(Submission.submitted_at.desc()).all()


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not _can_view_submission(user, submission, db):
        raise HTTPException(403, "You cannot view this submission")
    if user.role == "student":
        return _student_submission_out(submission, _utcnow_naive())
    return submission


#
# Uploaded files are untrusted: they're only ever sent as downloads
# (Content-Disposition: attachment, nosniff), and anything that a browser
# could execute or render (HTML, SVG, JS, ...) is sent as text/plain.

_SUBMISSION_KINDS = ("code", "report", "video")


_SAFE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".zip": "application/zip",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
}


def _viewable_submission(db: Session, user: User, submission_id: int) -> Submission:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not _can_view_submission(user, submission, db):
        raise HTTPException(403, "You cannot view this submission")
    return submission


def _kind_root(submission: Submission, kind: str) -> Optional[Path]:
    """The folder holding one part of a submission (code dir, or the folder
    containing the single report/video file), or None if it wasn't submitted."""
    rel = {"code": submission.code_path, "report": submission.report_path, "video": submission.video_path}.get(kind)
    if not rel:
        return None
    path = BASE_DIR / rel
    return path if kind == "code" else path.parent


def _kind_files(submission: Submission, kind: str) -> list[Path]:
    root = _kind_root(submission, kind)
    if root is None or not root.is_dir():
        return []
    if kind == "code":
        return sorted(p for p in root.rglob("*") if p.is_file())
    stored = BASE_DIR / (submission.report_path if kind == "report" else submission.video_path)
    return [stored] if stored.is_file() else []


@router.get("/submissions/{submission_id}/files", response_model=list[SubmissionFileOut])
def list_submission_files(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    submission = _viewable_submission(db, user, submission_id)
    out = []
    for kind in _SUBMISSION_KINDS:
        root = _kind_root(submission, kind)
        for path in _kind_files(submission, kind):
            out.append(SubmissionFileOut(kind=kind, path=path.relative_to(root).as_posix(), name=path.name,
                                         size=path.stat().st_size))
    return out


@router.get("/submissions/{submission_id}/files/{kind}/{file_path:path}")
def download_submission_file(
    submission_id: int, kind: str, file_path: str,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    submission = _viewable_submission(db, user, submission_id)
    if kind not in _SUBMISSION_KINDS:
        raise HTTPException(404, "File not found")
    root = _kind_root(submission, kind)
    if root is None:
        raise HTTPException(404, "File not found")
    target = (root / file_path).resolve()
    # Only files that belong to this part of this submission; never a path outside it.
    if target not in {p.resolve() for p in _kind_files(submission, kind)}:
        raise HTTPException(404, "File not found")
    media_type = _SAFE_MEDIA_TYPES.get(target.suffix.lower(), "text/plain; charset=utf-8")
    return FileResponse(target, media_type=media_type, filename=target.name,
                        headers={"X-Content-Type-Options": "nosniff"})
