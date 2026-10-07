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
  submission_count: number;
  graded_count: number;
  created_at: string;
  updated_at: string | null;
}

/** A student's own submission: status and final total only. */
export interface MySubmission {
  id: number;
  submitted_at: string;
  status: "submitted" | "graded";
  has_code: boolean;
  has_report: boolean;
  has_video: boolean;
  final_mark: number | null;
  max_mark: number | null;
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
  my_submission: MySubmission | null;
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
}

export interface Grade {
  id: number;
  submission_id: number;
  rubric_id: number;
  criterion_scores: Record<string, number>;
  total_score: number;
  comments: string | null;
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

export interface SimilarityCheckResult {
  subject_id: number;
  assignment_name: string;
  compared: number;
  pairs: SimilarityPair[];
  semantic: SemanticSummary;
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
  similarity_flagged: boolean;
  code_ai_flagged: boolean;
  report_ai_signal: string | null;
  consistency_score: number | null;
  /** Null on evaluations stored before this feature existed. */
  cross_modal_consistency: CrossModalConsistency | null;
  created_at: string;
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
    Record<ConsistencyComponent, { available: boolean; words: number; chunks: number; note: string | null }>
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

export async function logout(): Promise<void> {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    /* ignore -- we're clearing the local session regardless */
  } finally {
    clearSession();
  }
}
