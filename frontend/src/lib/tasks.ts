import type { CodeQuestion } from "@/lib/api";

// A code challenge is made of tasks, each with its own question and test cases. The pages say "task";
// the API and the database call it a question (CodeQuestion), so no stored data had to change.

// The server titles a task "Task 2" when the instructor gave it no title of its own (older ones were
// titled "Question 2"): that is not a title anyone wrote.
const GENERATED_TITLE = /^(Task|Question) \d+$/;

/** The title the instructor gave a task, or "" when it has none of its own. */
export function ownTitle(title: string): string {
  const trimmed = title.trim();
  return GENERATED_TITLE.test(trimmed) ? "" : trimmed;
}

/** A task's time limit in words: "10 minutes", "1 minute 30 seconds", "45 seconds". */
export function timeLimitText(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  const parts = [];
  if (m > 0) parts.push(`${m} minute${m === 1 ? "" : "s"}`);
  if (s > 0) parts.push(`${s} second${s === 1 ? "" : "s"}`);
  return parts.join(" ");
}

/** The tasks of a challenge that have a time limit. */
export function timedTasks(questions: Pick<CodeQuestion, "id" | "title" | "time_limit_seconds">[] | undefined) {
  return (questions ?? []).filter((q) => (q.time_limit_seconds ?? 0) > 0);
}

/** "Task 2: Triple it", or just "Task 2" for a task without a title of its own. */
export function taskName(q: Pick<CodeQuestion, "id" | "title">): string {
  const title = ownTitle(q.title);
  return title ? `Task ${q.id}: ${title}` : `Task ${q.id}`;
}
