"""The request and response models of the API, and the size limits they use.

Moved out of app/main.py, so the routers and their helpers can share them."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .code_languages import CodeLanguage
from .common import UTCDateTime
from .models import SUBMISSION_TYPES


class LoginIn(BaseModel):
    # 254 is the longest e-mail address there can be; no password is anywhere near 1024 characters. Longer input is
    # refused before any work is done (and before the login limiter keeps a copy of the e-mail).
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class SubjectCreate(BaseModel):
    name: str
    code: str
    batch: str = Field(default="", max_length=100)
    instructor_ids: list[int] = []  # the instructors who teach it


class SubjectUpdate(BaseModel):
    """Admin edit of a subject. Fields left out are kept."""
    name: Optional[str] = Field(default=None, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    batch: Optional[str] = Field(default=None, max_length=100)
    instructor_ids: Optional[list[int]] = None  # replaces the instructors who teach it


class SubjectOut(BaseModel):
    id: int
    name: str
    code: str
    batch: str = ""
    # Admin subject endpoints only: the instructors who teach it (empty everywhere else).
    instructor_ids: list[int] = []
    created_at: UTCDateTime

    model_config = ConfigDict(from_attributes=True)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    subjects: list[SubjectOut] = []
    # Admin lists only: how many submissions a student has (shown before
    # deleting the account, which deletes them too).
    submission_count: int = 0
    # A student's batch and register number ("" when not given, and for other roles).
    batch: str = ""
    register_number: str = ""
    # True until the user replaces the password an admin gave them (the frontend then shows the change-password page).
    must_change_password: bool = False

    model_config = ConfigDict(from_attributes=True)


class LoginOut(BaseModel):
    token: str
    user: UserOut


class SubjectIdsIn(BaseModel):
    subject_ids: list[int] = []


class InstructorCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=4)
    subject_ids: list[int] = []


class StudentCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=4)
    subject_ids: list[int] = []
    batch: str = Field(default="", max_length=100)
    register_number: str = Field(default="", max_length=50)


class ImportRowOut(BaseModel):
    """One row of a student import: what would be stored, and what stops it being created (nothing: it can be)."""
    row: int
    full_name: str
    email: str
    batch: str
    register_number: str
    problems: list[str]


class ImportPreviewOut(BaseModel):
    rows: list[ImportRowOut]
    ready: int
    with_problems: int


class ImportResultOut(BaseModel):
    created: list[ImportRowOut]
    skipped: list[ImportRowOut]
    # The list of first passwords, an .xlsx file in base64. Only in this answer: it is kept nowhere. "" if none created.
    passwords_file: str


class UserUpdate(BaseModel):
    """Admin edit of an instructor or student. Fields left out are kept;
    a blank password keeps the current one."""
    email: Optional[str] = Field(default=None, max_length=254)
    full_name: Optional[str] = Field(default=None, max_length=200)
    password: Optional[str] = Field(default=None, max_length=200)
    subject_ids: Optional[list[int]] = None
    # Students only (ignored for an instructor); "" clears them. The register number is TST/<batch>/<number>
    # (e.g. TST/01/001) and needs the batch, which is the middle part.
    batch: Optional[str] = Field(default=None, max_length=100)
    register_number: Optional[str] = Field(default=None, max_length=50)


class Criterion(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    max_points: float = Field(gt=0, le=10_000)


class CriterionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    max_points: Optional[float] = Field(default=None, gt=0, le=10_000)


class RubricCreate(BaseModel):
    name: str = Field(max_length=200)
    subject_id: int
    # A rubric is created with all of its criteria in one record; more can
    # be added later with POST /rubrics/{id}/criteria.
    criteria: list[Criterion] = Field(min_length=1)


class RubricUpdate(BaseModel):
    name: str = Field(max_length=200)


class RubricOut(BaseModel):
    id: int
    name: str
    subject_id: int
    subject_name: str
    subject_code: str = ""  # the rubric's own subject, shown next to its name in the assignment's rubric list
    criteria: list[dict]  # [{"id", "name", "description", "max_points"}, ...]
    max_total: float
    created_at: UTCDateTime
    # Grades recorded against this rubric. Once > 0 its structure (criterion
    # names, points, add/delete) is locked so recorded marks stay meaningful.
    graded_count: int = 0
    locked: bool = False
    assignment_names: list[str] = []


SubmissionType = Literal["code", "report", "video"]


_STARTER_CODE_MAX = 200_000


_TEST_CASES_MAX = 50  # in all, whatever the number of questions


_QUESTIONS_MAX = 20


_STATEMENT_MAX = 10_000


_TASK_STARTER_MAX = 50_000  # the student editor's limit (MAX_CODE_CHARS in app/routers/student_runs.py)


_TEST_TEXT_MAX = 10_000


_TASK_PASSWORD_MAX = 100


_TASK_TIME_MAX = 24 * 3600  # a task's time limit, in seconds


_LATE_GRACE_MAX = 7 * 24 * 60  # the grace period after a deadline, in minutes


_LATE_MARKS_MAX = 1000  # the most marks a late penalty can take (per day or in all)


LatePenaltyUnit = Literal["percent", "marks"]  # what a late penalty is counted in


class SubjectInstructorOut(BaseModel):
    id: int
    name: str
    email: str


class QuestionIn(BaseModel):
    """One task of a code challenge: the question students are asked to answer in code. Its test cases are
    the ones whose ``question`` is its number (its place in the list, from 1). The pages call it a task;
    the API and the database call it a question."""

    title: str = Field(default="", max_length=200)  # blank: "Task 1", "Task 2", ... (when there are several)
    statement: str = Field(default="", max_length=_STATEMENT_MAX)  # the question text, shown above the code box
    # Optional starting code: put in the student's code box when they open the task, for them to write on.
    # (The assignment's own starter_code is a different thing: instructor-only, left out of the similarity check.)
    starter_code: str = Field(default="", max_length=_TASK_STARTER_MAX)
    # Optional time limit in seconds (the page takes minutes and seconds): the student's clock for this task
    # starts when they open it, and when it runs out their code is handed in as it stands. 0: no limit.
    time_limit_seconds: int = Field(default=0, ge=0, le=_TASK_TIME_MAX)


class QuestionOut(QuestionIn):
    id: int


class TestCaseIn(BaseModel):
    """One test for submitted code: ``input`` goes to the program's standard
    input and its output is compared with ``expected_output``."""

    name: str = Field(default="", max_length=200)  # blank: "Test 1", "Test 2", ... (counted within its question)
    # The question this test belongs to (1 is the first); only a challenge with several questions needs it.
    question: int = Field(default=1, ge=1, le=_QUESTIONS_MAX)
    input: str = Field(default="", max_length=_TEST_TEXT_MAX)
    expected_output: str = Field(max_length=_TEST_TEXT_MAX)
    # exact: the whole output (ignoring trailing spaces and line-ending style);
    # contains: the expected text appears somewhere in the output (menu programs).
    match: Literal["exact", "contains"] = "exact"
    visible: bool = False  # visible tests are shown to students; hidden ones never are
    points: float = Field(default=1, gt=0, le=1000)


class TestCaseOut(TestCaseIn):
    id: int


AssignmentType = Literal["submission", "code_challenge"]


class AssignmentIn(BaseModel):
    subject_id: int
    name: str = Field(max_length=200)
    # "submission": students upload files. "code_challenge": code only, run
    # against test_cases. Left out: a code challenge if there are test cases.
    assignment_type: Optional[AssignmentType] = None
    description: str = Field(default="", max_length=10_000)
    # ISO 8601. Times with an offset are converted to UTC; times without
    # one are taken as UTC (the frontend always sends UTC).
    available_from: datetime
    deadline: datetime
    rubric_id: Optional[int] = None
    # Which kinds of file students may submit. Defaults to all of them.
    submission_types: list[SubmissionType] = Field(default_factory=lambda: list(SUBMISSION_TYPES))
    # Optional instructor starter code (one file). Its fingerprints are left
    # out of the token similarity check; the file name's extension decides
    # which submitted files it is subtracted from.
    starter_code: str = Field(default="", max_length=_STARTER_CODE_MAX)
    starter_code_filename: str = Field(default="", max_length=200)
    # Optional: the only languages students may submit code in. Empty = any.
    code_languages: list[CodeLanguage] = Field(default_factory=list)
    # Student self-checks before the deadline; both on by default.
    student_similarity_check: bool = True
    student_ai_check: bool = True
    # Code similarity ignores code most of the class shares (both checks).
    ignore_common_code: bool = True
    # Optional: students see no marks or feedback before this time. None shows
    # each mark as soon as it is saved.
    marks_release_at: Optional[datetime] = None
    # Optional test cases for submitted code; needs "code" in submission_types.
    test_cases: list[TestCaseIn] = Field(default_factory=list, max_length=_TEST_CASES_MAX)
    # The tasks of a code challenge (called questions here), each with its own question text and test
    # cases (a test's ``question`` is the place of its task in this list, from 1). Left out: one task,
    # which all the test cases belong to.
    questions: list[QuestionIn] = Field(default_factory=list, max_length=_QUESTIONS_MAX)
    # The file the tests run (a name or a path in the submission); blank picks it automatically.
    # Only used by a challenge with a single task.
    test_main_file: str = Field(default="", max_length=200)
    # A code challenge's access password: students enter it before they see or do the tasks. Blank: none.
    task_password: str = Field(default="", max_length=_TASK_PASSWORD_MAX)
    # A code challenge's tasks must be handed in in order, the first before the second, and so on.
    tasks_in_order: bool = False
    # Late work. Minutes after the deadline in which work still counts as on time; the late deadline, the date until
    # which late work is accepted at all (None: not after the grace period); and the penalty for every day or part
    # of a day late, at most the maximum: in percent of the mark, or in marks (`late_penalty_unit` says which).
    late_grace_minutes: int = Field(default=0, ge=0, le=_LATE_GRACE_MAX)
    late_until: Optional[datetime] = None
    late_penalty_unit: LatePenaltyUnit = "percent"
    late_penalty_percent: float = Field(default=0, ge=0, le=100)
    late_penalty_max_percent: float = Field(default=100, ge=0, le=100)
    late_penalty_marks: float = Field(default=0, ge=0, le=_LATE_MARKS_MAX)
    late_penalty_max_marks: Optional[float] = Field(default=None, ge=0, le=_LATE_MARKS_MAX)  # None: no limit


class AssignmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    available_from: Optional[datetime] = None
    deadline: Optional[datetime] = None
    rubric_id: Optional[int] = None  # send null explicitly to detach the rubric
    submission_types: Optional[list[SubmissionType]] = None
    starter_code: Optional[str] = Field(default=None, max_length=_STARTER_CODE_MAX)  # "" removes it
    starter_code_filename: Optional[str] = Field(default=None, max_length=200)
    code_languages: Optional[list[CodeLanguage]] = None  # [] removes the restriction
    student_similarity_check: Optional[bool] = None  # can be changed at any time
    student_ai_check: Optional[bool] = None
    ignore_common_code: Optional[bool] = None  # can be changed at any time
    marks_release_at: Optional[datetime] = None  # send null explicitly to release marks now
    # Replaces the whole list ([] removes every test); leave out to keep them.
    test_cases: Optional[list[TestCaseIn]] = Field(default=None, max_length=_TEST_CASES_MAX)
    # Replaces the whole list of tasks; leave out to keep them. Their number can't change once
    # students have submitted (their code is saved per task).
    questions: Optional[list[QuestionIn]] = Field(default=None, max_length=_QUESTIONS_MAX)
    test_main_file: Optional[str] = Field(default=None, max_length=200)  # "" picks it automatically
    task_password: Optional[str] = Field(default=None, max_length=_TASK_PASSWORD_MAX)  # "" removes it
    tasks_in_order: Optional[bool] = None  # can be changed at any time
    # The late rules can change at any time; work already handed in keeps the penalty it got.
    late_grace_minutes: Optional[int] = Field(default=None, ge=0, le=_LATE_GRACE_MAX)
    late_until: Optional[datetime] = None  # send null explicitly to stop accepting late work
    late_penalty_percent: Optional[float] = Field(default=None, ge=0, le=100)
    late_penalty_max_percent: Optional[float] = Field(default=None, ge=0, le=100)
    late_penalty_unit: Optional[LatePenaltyUnit] = None
    late_penalty_marks: Optional[float] = Field(default=None, ge=0, le=_LATE_MARKS_MAX)
    late_penalty_max_marks: Optional[float] = Field(default=None, ge=0, le=_LATE_MARKS_MAX)  # null: no limit


class AssignmentOut(BaseModel):
    """Instructor view of an assignment."""

    id: int
    subject_id: int
    subject_name: str
    assignment_type: str = "submission"  # submission | code_challenge
    name: str
    description: str
    available_from: UTCDateTime
    deadline: UTCDateTime
    status: str  # upcoming | open | closed
    rubric_id: Optional[int]
    rubric_name: Optional[str]
    max_points: Optional[float]
    submission_types: list[str]
    submission_count: int
    graded_count: int
    created_at: UTCDateTime
    updated_at: Optional[UTCDateTime]
    starter_code: str = ""
    starter_code_filename: str = ""
    # Template PDF cut out of student reports before the report similarity check.
    report_template_filename: str = ""
    report_template_words: int = 0
    # Languages students must use for code; empty = any supported language.
    code_languages: list[str] = []
    student_similarity_check: bool = True
    student_ai_check: bool = True
    ignore_common_code: bool = True
    marks_release_at: Optional[UTCDateTime] = None
    marks_released: bool = True  # whether students can see marks and feedback now
    # Every test case, hidden ones included: this is the instructor view only.
    test_cases: list[TestCaseOut] = []
    questions: list[QuestionOut] = []  # a code challenge's tasks; empty for other assignments
    test_main_file: str = ""
    task_password: str = ""  # the code challenge's access password, for the instructor to read back and share
    tasks_in_order: bool = False
    late_grace_minutes: int = 0
    late_until: Optional[UTCDateTime] = None
    late_penalty_percent: float = 0
    late_penalty_max_percent: float = 100
    late_penalty_unit: LatePenaltyUnit = "percent"
    late_penalty_marks: float = 0
    late_penalty_max_marks: Optional[float] = None
    late_count: int = 0  # submissions handed in late


class CriterionMarkOut(BaseModel):
    name: str
    score: float
    max_points: float


class MySubmissionOut(BaseModel):
    """What a student sees about their own submission: status, the final
    total, the per-criterion marks and the instructor's feedback for them
    -- never the internal comments or the evaluator output."""

    id: int
    submitted_at: UTCDateTime
    status: str  # submitted | graded
    has_code: bool
    has_report: bool
    has_video: bool
    final_mark: Optional[float]  # after any late penalty
    max_mark: Optional[float]
    # Handed in after the deadline and its grace period: seconds after the deadline (None: on time), the percent
    # of the mark or the marks that cost, and the mark before that penalty (shown with the final one, e.g. 34 -> 30.6).
    late_seconds: Optional[int] = None
    late_penalty_percent: float = 0
    late_penalty_marks: float = 0
    raw_mark: Optional[float] = None
    # Empty when graded with "Final mark only" (no per-criterion marks) or not graded.
    criterion_marks: list[CriterionMarkOut] = []
    feedback: Optional[str] = None
    can_edit: bool  # assignment open, not yet graded, and not a code challenge (its code cannot be replaced)
    # The student may delete the submission: the assignment is open and (unless it is a code challenge, which is
    # marked from its tests at once) it is not graded yet. A graded code challenge can still be deleted and redone.
    can_delete: bool = False
    # A code challenge is handed in one task at a time: how many tasks have been (0 for other assignments).
    questions_submitted: int = 0


class StudentAssignmentOut(BaseModel):
    id: int
    subject_id: int
    subject_name: str
    name: str
    description: str
    available_from: UTCDateTime
    deadline: UTCDateTime
    status: str  # open | closed (upcoming assignments aren't listed)
    assignment_type: str = "submission"  # submission | code_challenge (a challenge is answered in the code editor)
    submission_types: list[str]
    code_languages: list[str] = []  # empty = any supported language
    # Which self-checks the instructor allows for this assignment.
    student_similarity_check: bool = True
    student_ai_check: bool = True
    # Set only while marks are still held back: when they will be released.
    marks_release_at: Optional[UTCDateTime] = None
    # What a code challenge asks, task by task (title and question text only). No test case is
    # ever part of this: a student meets the tests only through the result of "Run"
    # (POST /assignments/{id}/run-code), where a visible test that fails shows its expected and
    # actual output and everything else is only counted. While the challenge has a password the student
    # has not entered yet, each task keeps its number and title but its question and starting code are empty.
    questions: list[QuestionOut] = []
    # A code challenge with a password: the student must enter it (POST /assignments/{id}/unlock-tasks) before
    # the questions are shown. The password itself is never sent.
    has_task_password: bool = False
    tasks_unlocked: bool = True  # False: has_task_password and this student has not entered it yet
    tasks_in_order: bool = False  # the tasks must be handed in in order
    # Late work. `status` stays "open" while late work is still taken, so `past_deadline` says the deadline has gone.
    # `accept_until` is the last moment work is taken when that is after the deadline (grace period or late date).
    past_deadline: bool = False
    accept_until: Optional[UTCDateTime] = None
    late_grace_minutes: int = 0
    late_penalty_percent: float = 0
    late_penalty_max_percent: float = 100
    late_penalty_unit: LatePenaltyUnit = "percent"
    late_penalty_marks: float = 0
    late_penalty_max_marks: Optional[float] = None
    penalty_now_percent: float = 0  # what handing in right now would cost (0 inside the grace period)
    penalty_now_marks: float = 0
    my_submission: Optional[MySubmissionOut]


class SubmissionOut(BaseModel):
    id: int
    student_id: int
    student_name: str
    student_email: str
    subject_id: int
    subject_name: str
    assignment_name: str
    assignment_id: Optional[int] = None
    code_path: Optional[str]
    report_path: Optional[str]
    video_path: Optional[str]
    submitted_at: UTCDateTime
    status: str
    # Final total of the latest grade (and the rubric's maximum); the only
    # grading information this response carries.
    final_mark: Optional[float] = None  # after any late penalty
    max_mark: Optional[float] = None
    # Handed in late: seconds after the deadline (None: on time), the percent of the mark or the marks lost for it,
    # and the mark before that.
    late_seconds: Optional[int] = None
    late_penalty_percent: float = 0
    late_penalty_marks: float = 0
    raw_mark: Optional[float] = None
    # Kinds of file uploaded: a subset of code, report, video.
    submitted_types: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class GradeIn(BaseModel):
    rubric_id: int
    criterion_scores: dict[str, float] = Field(default_factory=dict)
    # Final mark only, without per-criterion marks. Send this OR criterion_scores.
    total_score: Optional[float] = None
    comments: Optional[str] = None  # internal notes, instructors only
    feedback: Optional[str] = Field(default=None, max_length=5000)  # for the student


class GradeOut(BaseModel):
    id: int
    submission_id: int
    rubric_id: int
    criterion_scores: dict[str, float]
    total_score: float
    comments: Optional[str]
    feedback: Optional[str] = None
    graded_by: Optional[str]
    graded_at: UTCDateTime

    model_config = ConfigDict(from_attributes=True)


class AutoEvaluateIn(BaseModel):
    rubric_id: int
    # False: grade with the built-in heuristic grader instead of the rubric
    # model (local Ollama). Everything else in the pipeline runs.
    use_rubric_model: bool = True
    # False: skip AI-content detection (the report's AI-text model and the
    # code heuristic). Cross-modal consistency and everything else still run.
    use_ai_detection: bool = True


class ConsistencyComponentOut(BaseModel):
    available: bool
    words: int = 0
    chunks: int = 0
    note: Optional[str] = None  # why it's unavailable


class ReportExtractionOut(BaseModel):
    """How the report text was obtained (MarkItDown); shown to instructors."""

    status: str  # ok | empty | failed | unsupported
    backend: str
    chars: int = 0
    words: int = 0
    error: Optional[str] = None
    extracted_at: Optional[str] = None


class CrossModalConsistencyOut(BaseModel):
    """Semantic similarity (0-1) between the code documentation, report and
    video transcript. None = not evaluated (component missing / analysis
    unavailable) -- never a stand-in for 0. A review signal only."""

    code_report: Optional[float]
    code_transcript: Optional[float]
    report_transcript: Optional[float]
    overall: Optional[float]
    status: str  # consistent | review_recommended | limited_data | unavailable | disabled
    reason: str
    threshold: float
    model: str
    warning: Optional[str] = None
    components: dict[str, ConsistencyComponentOut] = {}
    report_extraction: Optional[ReportExtractionOut] = None


class AISignalOut(BaseModel):
    signal: str  # low | medium | high
    score: int  # 0-100, higher = more AI-like
    method: str  # e.g. "style-heuristic", "fast-detectgpt:Qwen2.5-0.5B"
    reasons: list[str]


class AISignalsOut(BaseModel):
    """AI-content estimates for the report and the code. Review signals
    only: they never change the suggested score. None = not assessed."""

    report: Optional[AISignalOut] = None
    code: Optional[AISignalOut] = None
    # True when the instructor switched AI-content detection off for this run.
    disabled: bool = False


class AutoEvaluationOut(BaseModel):
    id: int
    submission_id: int
    rubric_id: int
    recommended_score: float
    recommended_max: float
    review_flags: list[str]
    criterion_breakdown: list[dict]
    grader: str
    model: Optional[str] = None
    similarity_flagged: bool
    code_ai_flagged: bool
    report_ai_signal: Optional[str]
    consistency_score: Optional[int]
    cross_modal_consistency: Optional[CrossModalConsistencyOut] = None
    ai_signals: Optional[AISignalsOut] = None
    created_at: UTCDateTime

    model_config = ConfigDict(from_attributes=True)


class BatchAutoEvaluateIn(BaseModel):
    rubric_id: int
    # Resume after an interruption: leave submissions that already have an
    # evaluation against this rubric untouched.
    skip_already_evaluated: bool = False
    # See AutoEvaluateIn.use_rubric_model / use_ai_detection.
    use_rubric_model: bool = True
    use_ai_detection: bool = True


class BatchEvaluationItemOut(BaseModel):
    submission_id: int
    student_name: str
    status: str  # evaluated | skipped | failed
    recommended_score: Optional[float] = None
    recommended_max: Optional[float] = None
    grader: Optional[str] = None
    model: Optional[str] = None
    review_flags: list[str] = []
    error: Optional[str] = None
    # Review flags shown as their own table columns; None when the submission failed.
    similarity_flagged: Optional[bool] = None
    ai_flagged: Optional[bool] = None
    # Level, score and method behind ai_flagged, so the table can show which
    # detector ran. None when the submission failed or predates these details.
    ai_signals: Optional[AISignalsOut] = None
    # The code / report / video consistency behind the row, so the table can show it without opening each
    # submission. None when the submission failed or was evaluated before this was kept.
    cross_modal_consistency: Optional[CrossModalConsistencyOut] = None


class BatchAutoEvaluateOut(BaseModel):
    subject_id: int
    assignment_name: str
    rubric_id: int
    job_id: Optional[int] = None  # the BatchJob that recorded this run
    total: int
    evaluated: int
    skipped: int
    failed: int
    results: list[BatchEvaluationItemOut]


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class UpcomingAssignmentOut(BaseModel):
    """An assignment that has not opened yet, as a student sees it in "Coming soon": only when it opens and
    closes. Its description, tasks and settings stay hidden until it opens (the instructor may still be
    changing them)."""
    name: str
    subject_id: int  # which of the student's subjects it belongs to (two subjects can share a name)
    subject_name: str
    assignment_type: str
    available_from: UTCDateTime
    deadline: UTCDateTime


class SubmissionFileOut(BaseModel):
    kind: str  # code | report | video
    path: str  # relative to that part of the submission, "/"-separated
    name: str
    size: int


class BatchJobOut(BaseModel):
    """A batch auto-evaluation run and its progress so far."""

    id: int
    subject_id: int
    assignment_name: str
    rubric_id: int
    status: str  # queued | running | done | failed | interrupted | stopped
    total: int
    done: int  # finished so far, whatever the outcome
    evaluated: int
    skipped: int
    failed: int
    # One entry per submission in submission order; null while still waiting or running.
    results: list[Optional[BatchEvaluationItemOut]] = []
    error: Optional[str] = None
    created_at: UTCDateTime
    started_at: Optional[UTCDateTime] = None
    finished_at: Optional[UTCDateTime] = None


class TestResultOut(BaseModel):
    """One test's outcome. This is the instructor view: it includes hidden
    tests and the expected output."""

    test_id: int
    name: str
    visible: bool
    points: float
    match: str
    status: str  # passed | failed | error | timeout | skipped (no code was submitted for its task)
    passed: bool
    expected_output: str
    actual_output: str
    stderr: str = ""
    question: int = 1  # the task the test belongs to


class TestRunQuestionOut(BaseModel):
    """How one task of a code challenge did on a submission."""

    question: int
    title: str
    answered: bool  # false: the student wrote no code for this question, so its tests earn nothing
    file: str  # the file that was run ("" when none was)
    language: str
    passed: int  # its tests passed
    total: int  # its tests
    earned_points: float
    total_points: float


class TestRunOut(BaseModel):
    submission_id: int
    file: str  # the file that was run (one per question that was answered, comma separated)
    language: str
    passed: int  # tests passed
    total: int  # tests run
    saved: bool = False  # true when the score was saved as the submission's mark
    earned_points: float  # points of the tests that passed
    total_points: float  # points of every test run
    results: list[TestResultOut]  # every question's tests, in order
    questions: list[TestRunQuestionOut] = []  # the same, question by question
