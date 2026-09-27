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
}

export interface Submission {
  id: number;
  student_id: number;
  student_name: string;
  student_email: string;
  subject_id: number;
  subject_name: string;
  assignment_name: string;
  code_path: string | null;
  report_path: string | null;
  video_path: string | null;
  submitted_at: string;
  status: "submitted" | "graded";
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
  jaccard: number;
  containment: number;
  flagged: boolean;
}

export interface SimilarityCheckResult {
  subject_id: number;
  assignment_name: string;
  compared: number;
  pairs: SimilarityPair[];
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
  created_at: string;
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
