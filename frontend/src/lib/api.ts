import type { CodeLanguageId } from "@/lib/codeLanguages";

// Shared API client: talks to the FastAPI backend and manages the
// logged-in session (token + user, kept in localStorage so a refresh
// doesn't sign you out).

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type Role = "admin" | "instructor" | "student";

export interface Subject {
  id: number;
  name: string;
  code: string;
  created_at: string;
}

export interface UserInfo {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  subjects: Subject[];
  /** Admin student list only: number of submissions. */
  submission_count?: number;
}

export interface LoginResult {
  token: string;
  user: UserInfo;
}

export interface Criterion {
  /** Stable within its rubric; absent only on criteria being created. */
  id?: number;
  name: string;
  description: string;
  max_points: number;
}

export interface Rubric {
  id: number;
  name: string;
  subject_id: number;
  subject_name: string;
  criteria: Criterion[];
  max_total: number;
  created_at: string;
  /** Grades recorded with this rubric; when > 0 its criteria are locked. */
  graded_count: number;
  locked: boolean;
  assignment_names: string[];
}

export type AssignmentStatus = "upcoming" | "open" | "closed";

/** File kinds an assignment accepts. */
export type SubmissionType = "code" | "report" | "video";

/** Instructor view of an assignment. Times are ISO strings with a UTC offset. */
export interface Assignment {
  id: number;
  subject_id: number;
  subject_name: string;
  name: string;
  description: string;
  available_from: string;
  deadline: string;
  status: AssignmentStatus;
  rubric_id: number | null;
  rubric_name: string | null;
  max_points: number | null;
  submission_types: SubmissionType[];
  submission_count: number;
  graded_count: number;
  created_at: string;
  updated_at: string | null;
  /** Instructor starter code ("" = none); excluded from the token similarity check. */
  starter_code: string;
  starter_code_filename: string;
  /** Template PDF cut out of student reports before the report similarity check. */
  report_template_filename: string;
  report_template_words: number;
  /** Languages students must write their code in; empty = any supported language. */
  code_languages: CodeLanguageId[];
  /** Student self-checks before the deadline (on by default). */
  student_similarity_check: boolean;
  student_ai_check: boolean;
  /** Code similarity (instructor check and self-check) ignores code most of the class shares. */
  ignore_common_code: boolean;
  /** Students see no marks or feedback before this time; null = as soon as each is saved. */
  marks_release_at: string | null;
  /** Whether students can see marks and feedback now. */
  marks_released: boolean;
  /** Test cases for submitted code (instructor view: hidden ones included). */
  test_cases: TestCase[];
  /** The file the tests run (a name or path in the submission); "" = picked automatically. */
  test_main_file: string;
  /** "submission": students upload files; "code_challenge": code only, run against test cases. Fixed at creation. */
  assignment_type: AssignmentKind;
}

export type AssignmentKind = "submission" | "code_challenge";

/** exact: the whole output (ignoring trailing spaces); contains: the expected text appears in it. */
export type TestMatch = "exact" | "contains";

/** One test for submitted code: `input` goes to standard input, the output is compared with `expected_output`. */
export interface TestCase {
  id: number;
  name: string;
  input: string;
  expected_output: string;
  match: TestMatch;
  /** Shown to students; hidden tests are only used for marking. */
  visible: boolean;
  points: number;
}

/** A student's own submission: status, marks and feedback (once released). */
export interface MySubmission {
  id: number;
  submitted_at: string;
  status: "submitted" | "graded";
  has_code: boolean;
  has_report: boolean;
  has_video: boolean;
  final_mark: number | null;
  max_mark: number | null;
  /** Per-criterion marks; empty when graded with "Final mark only" or not graded. */
  criterion_marks: { name: string; score: number; max_points: number }[];
  /** The instructor's feedback for the student (never the internal comments). */
  feedback: string | null;
  /** Open and not graded yet; never true for a code challenge, which is final once submitted. */
  can_edit: boolean;
}

/** Student view of an assignment (never includes rubric details). */
export interface StudentAssignment {
  id: number;
  subject_id: number;
  subject_name: string;
  name: string;
  description: string;
  available_from: string;
  deadline: string;
  status: "open" | "closed";
  submission_types: SubmissionType[];
  /** Languages the code must be written in; empty = any supported language. */
  code_languages: CodeLanguageId[];
  /** Which self-checks the instructor allows for this assignment. */
  student_similarity_check: boolean;
  student_ai_check: boolean;
  /** Set only while marks are held back: when they will be released. */
  marks_release_at: string | null;
  /** A code challenge is answered in the code editor instead of by uploading files. */
  assignment_type: AssignmentKind;
  my_submission: MySubmission | null;
}

/** A VISIBLE test that did not pass, from POST /assignments/{id}/run-code: what was expected and what was printed. */
export interface CodeRunFailure {
  /** Its place among the visible tests, from 1. */
  sample: number;
  name: string;
  status: "failed" | "error" | "timeout";
  expected_output: string;
  actual_output: string;
  /** The crash message, or the time-limit note. */
  error: string;
}

/**
 * What a student sees after pressing Run: the code was run against every test
 * case, hidden ones included, but a hidden test is only ever counted.
 */
export interface CodeRun {
  language: string;
  /** Every test case passed, hidden ones included. */
  all_passed: boolean;
  passed: number;
  total: number;
  /** Hidden test cases that did not pass; nothing more is said about them. */
  hidden_failed: number;
  remaining_runs: number;
  /** The visible tests that did not pass, with expected vs actual output. */
  failures: CodeRunFailure[];
}

/**
 * What a student gets after pressing Submit on a code challenge (POST /assignments/{id}/submit-code):
 * the code is saved, run against every test case and marked at once, and it cannot be changed afterwards.
 */
export interface CodeSubmit {
  submission_id: number;
  /** The tests ran and the mark is saved. False: the code is submitted but will be marked later. */
  marked: boolean;
  /** The same report Run gives; null when the tests could not be run just now. */
  run: CodeRun | null;
  /** The mark: points of the tests passed out of all the points. Null before the marks release date, or when not marked. */
  earned: number | null;
  total: number | null;
}

/** One test's outcome from POST /submissions/{id}/run-tests (instructor view). */
export interface TestResult {
  test_id: number;
  name: string;
  visible: boolean;
  points: number;
  match: TestMatch;
  status: "passed" | "failed" | "error" | "timeout";
  passed: boolean;
  expected_output: string;
  actual_output: string;
  stderr: string;
}

export interface TestRun {
  submission_id: number;
  /** The file that was run, relative to the submission's code folder. */
  file: string;
  language: string;
  passed: number;
  total: number;
  /** True when the score was saved as the submission's mark (mark-from-tests). */
  saved: boolean;
  earned_points: number;
  total_points: number;
  results: TestResult[];
}

export interface Submission {
  id: number;
  student_id: number;
  student_name: string;
  student_email: string;
  subject_id: number;
  subject_name: string;
  assignment_name: string;
  assignment_id: number | null;
  code_path: string | null;
  report_path: string | null;
  video_path: string | null;
  submitted_at: string;
  status: "submitted" | "graded";
  final_mark: number | null;
  max_mark: number | null;
  /** Kinds of file uploaded, in this order: code, report, video. */
  submitted_types: ("code" | "report" | "video")[];
}

export interface Grade {
  id: number;
  submission_id: number;
  rubric_id: number;
  criterion_scores: Record<string, number>;
  total_score: number;
  comments: string | null; // internal, instructors only
  feedback: string | null; // for the student
  graded_by: string | null;
  graded_at: string;
}

export interface SimilarityPair {
  submission_a_id: number;
  submission_b_id: number;
  student_a: string;
  student_b: string;
  shared_fingerprints: number;
  jaccard: number;
  containment: number;
  /** UniXcoder cosine similarity (0-1); null when semantic analysis didn't run for this pair. */
  semantic_similarity: number | null;
  token_flagged: boolean;
  /** Final flag: token overlap OR a semantic review signal. */
  flagged: boolean;
  flag_level: "high" | "review" | null;
  flag_reason: string | null;
}

export interface SemanticSummary {
  status: "ok" | "unavailable" | "disabled";
  model: string;
  warning: string | null;
  submissions_encoded: number;
  cache_hits: number;
  skipped_too_small: number[];
  pairs_compared: number;
  cohort_median: number | null;
  review_threshold: number | null;
}

export interface ReportPassage {
  words: number;
  text_a: string;
  text_b: string;
}

export interface ReportSimilarityPair {
  submission_a_id: number;
  submission_b_id: number;
  student_a: string;
  student_b: string;
  words_a: number;
  words_b: number;
  shared_fingerprints: number;
  jaccard: number;
  containment: number;
  /** Share of each report's words inside an identical passage. */
  coverage_a: number;
  coverage_b: number;
  /** all-MiniLM-L6-v2 best-match similarity (0-1); null when it didn't run. */
  semantic_similarity: number | null;
  flag_level: "high" | "review" | null;
  flag_reason: string | null;
  passages: ReportPassage[];
}

export interface ReportSimilarityResult {
  subject_id: number;
  assignment_name: string;
  compared: number;
  skipped: { submission_id: number; student: string; reason: string }[];
  common_fingerprints_excluded: number;
  /** The assignment's template PDF, cut out of every report before comparing. */
  template_filename: string | null;
  template_words_removed: Record<string, number>;
  pairs: ReportSimilarityPair[];
  semantic: {
    status: "ok" | "unavailable" | "disabled";
    model: string;
    warning: string | null;
    pairs_compared: number;
    cohort_median: number | null;
    review_threshold: number | null;
  };
  exploratory: boolean;
}

export interface BatchEvaluationItem {
  submission_id: number;
  student_name: string;
  status: "evaluated" | "skipped" | "failed";
  recommended_score: number | null;
  recommended_max: number | null;
  grader: string | null;
  /** Ollama model that produced the marks; null for the heuristic grader. */
  model: string | null;
  review_flags: string[];
  error: string | null;
  /** Similarity flag (overlap with another submission); null when the submission failed. */
  similarity_flagged: boolean | null;
  /** AI-content review flag (code or report); never changes marks. Null when the submission failed. */
  ai_flagged: boolean | null;
  /** Level, score and method behind ai_flagged; null when failed or stored before these details. */
  ai_signals?: { report: AISignal | null; code: AISignal | null } | null;
}

export interface BatchEvaluationResult {
  subject_id: number;
  assignment_name: string;
  rubric_id: number;
  total: number;
  evaluated: number;
  skipped: number;
  failed: number;
  results: BatchEvaluationItem[];
}

/** A batch auto-evaluation running on the server (POST .../auto-evaluate/jobs). */
export interface BatchJob {
  id: number;
  subject_id: number;
  assignment_name: string;
  rubric_id: number;
  /** "interrupted": the server stopped mid-run; it can be resumed. */
  status: "queued" | "running" | "done" | "failed" | "interrupted";
  total: number;
  /** Finished so far, whatever the outcome. */
  done: number;
  evaluated: number;
  skipped: number;
  failed: number;
  /** One per submission in submission order; null while still waiting or running. */
  results: (BatchEvaluationItem | null)[];
  /** Why the whole job failed (one submission failing does not fail the job). */
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SimilarityCheckResult {
  subject_id: number;
  assignment_name: string;
  compared: number;
  pairs: SimilarityPair[];
  semantic: SemanticSummary;
  starter_code_excluded?: boolean;
  /** Distinct code patterns ignored because most of the class shares them (0 = option off). */
  common_code_removed?: number;
}

export interface AutoEvaluation {
  id: number;
  submission_id: number;
  rubric_id: number;
  recommended_score: number;
  recommended_max: number;
  review_flags: string[];
  criterion_breakdown: { name: string; score: number; max_points: number; justification: string }[];
  grader: string;
  /** Ollama model that produced the marks; null for the heuristic grader or older results. */
  model?: string | null;
  similarity_flagged: boolean;
  code_ai_flagged: boolean;
  report_ai_signal: string | null;
  consistency_score: number | null;
  /** Null on evaluations stored before this feature existed. */
  cross_modal_consistency: CrossModalConsistency | null;
  /** Null on evaluations stored before AI-signal details were kept. */
  /** `disabled`: the instructor switched AI-content detection off for this run. */
  ai_signals?: { report: AISignal | null; code: AISignal | null; disabled?: boolean } | null;
  created_at: string;
}

/** An AI-content estimate: a review signal only, never a score change. */
export interface AISignal {
  signal: "low" | "medium" | "high";
  score: number;
  method: string;
  reasons: string[];
}

export type ConsistencyComponent = "code" | "report" | "transcript";

export interface CrossModalConsistency {
  /** Semantic similarity 0-1; null = not evaluated (never a stand-in for 0). */
  code_report: number | null;
  code_transcript: number | null;
  report_transcript: number | null;
  overall: number | null;
  status: "consistent" | "review_recommended" | "limited_data" | "unavailable" | "disabled";
  reason: string;
  threshold: number;
  model: string;
  warning: string | null;
  components: Partial<
    Record<
      ConsistencyComponent,
      {
        available: boolean;
        words: number;
        chunks: number;
        note: string | null;
        /** "code_text": the code had no documentation, so its own text was compared. */
        source?: "documentation" | "code_text" | null;
      }
    >
  >;
  /** How the report text was obtained; null when no report was submitted. */
  report_extraction?: ReportExtraction | null;
}

export interface ReportExtraction {
  status: "ok" | "empty" | "failed" | "unsupported";
  backend: string;
  chars: number;
  words: number;
  error: string | null;
  extracted_at: string | null;
}

const SESSION_KEYS = { token: "token", user: "user" } as const;

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(SESSION_KEYS.token);
  } catch {
    return null;
  }
}

export function getUser(): UserInfo | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(SESSION_KEYS.user);
    return raw ? (JSON.parse(raw) as UserInfo) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: UserInfo): void {
  try {
    localStorage.setItem(SESSION_KEYS.token, token);
    localStorage.setItem(SESSION_KEYS.user, JSON.stringify(user));
  } catch {
    /* ignore -- storage unavailable */
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(SESSION_KEYS.token);
    localStorage.removeItem(SESSION_KEYS.user);
  } catch {
    /* ignore */
  }
}

export function destinationForRole(role: Role): string {
  if (role === "admin") return "/admin";
  if (role === "instructor") return "/instructor";
  return "/student";
}

interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  body?: BodyInit;
}

/** Fetch wrapper that attaches the bearer token and sends the reader
 * back to the login page if the session has expired. Pass
 * `json: {...}` instead of `body` for a JSON request. */
export async function apiFetch<T = unknown>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const init: RequestInit = { ...options, headers };
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.json);
  }
  delete (init as { json?: unknown }).json;

  const res = await fetch(`${API_BASE}${path}`, init);

  // A 401 from /auth/login just means "wrong email or password" --
  // that's a normal login failure, not an expired session, so it
  // falls through to the generic error handling below instead of
  // redirecting (which would wipe out the error message before the
  // reader ever saw it).
  if (res.status === 401 && path !== "/auth/login") {
    clearSession();
    // apiFetch is a plain utility function, not a component or hook, so
    // useRouter() isn't available here -- a hard navigation is the
    // correct way to force a full session reset from this context.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Session expired -- please log in again");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore parse errors, fall back to statusText */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

/** A file that belongs to a submission (see GET /submissions/{id}/files). */
export interface SubmissionFile {
  kind: "code" | "report" | "video";
  path: string;
  name: string;
  size: number;
}

/** Download a protected file as a Blob (a plain link can't send the bearer token).
 * With `json`, the body is POSTed (used for the Excel exports). */
export async function apiFetchBlob(path: string, json?: unknown): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const init: RequestInit = { headers };
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.method = "POST";
    init.body = JSON.stringify(json);
  }
  const res = await fetch(`${API_BASE}${path}`, init);
  if (res.status === 401) {
    clearSession();
    // Same as apiFetch: a plain utility can't use useRouter().
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Session expired -- please log in again");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.blob();
}

export function submissionFileUrl(submissionId: number, file: SubmissionFile): string {
  const encoded = file.path.split("/").map(encodeURIComponent).join("/");
  return `/submissions/${submissionId}/files/${file.kind}/${encoded}`;
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    /* ignore -- we're clearing the local session regardless */
  } finally {
    clearSession();
  }
}

// ---- Student self-checks -----------------------------------------------------

export type SelfCheckKind = "code_similarity" | "report_similarity" | "ai_content";
export type SelfCheckBand = "low" | "moderate" | "high";

/** What a student sees: bands, counts and passages of their OWN work only. */
export interface SelfCheckResult {
  band?: SelfCheckBand;
  compared?: number;
  similar_submissions?: number;
  /** Too few submissions to say what is normal for the class: fixed limits were used. Absent on older results. */
  small_class?: boolean;
  highlights?: { file: string; start_line: number; end_line: number; text: string; truncated: boolean }[];
  passages?: string[];
  note?: string;
  /** AI-content check: one band per part, null when the part wasn't assessed. */
  report?: SelfCheckBand | null;
  code?: SelfCheckBand | null;
}

export interface SelfCheck {
  id: number;
  kind: SelfCheckKind;
  status: "running" | "done" | "failed";
  created_at: string;
  finished_at: string | null;
  error: string | null;
  result: SelfCheckResult | null;
}

export interface SelfCheckStatus {
  submission_id: number;
  can_run: boolean;
  similarity_enabled: boolean;
  ai_enabled: boolean;
  limit_per_hour: number;
  remaining: Record<SelfCheckKind, number>;
  latest: Record<SelfCheckKind, SelfCheck | null>;
}

/** Instructor view: how often each student ran each self-check. */
export interface SelfCheckHistoryRow {
  submission_id: number;
  student_name: string;
  student_email: string;
  code_similarity_checks: number;
  report_similarity_checks: number;
  ai_checks: number;
  last_check_at: string | null;
  latest_kind: SelfCheckKind | null;
  latest_status: SelfCheck["status"] | null;
}
