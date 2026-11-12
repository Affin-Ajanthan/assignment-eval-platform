"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, StudentAssignment } from "@/lib/api";
import { formatDateTime, timeLeft } from "@/lib/datetime";
import Badge from "@/components/Badge";

/** How far ahead "due soon" looks, and how many boxes the home page shows. */
const DAYS_AHEAD = 7;
const SHOWN = 6;

/** Still to hand in: nothing submitted yet, or a code challenge with tasks left. */
function needsSubmitting(a: StudentAssignment): boolean {
  const sub = a.my_submission;
  if (!sub) return true;
  const tasks = a.questions?.length ?? 0;
  return a.assignment_type === "code_challenge" && tasks > 1 && sub.questions_submitted < tasks;
}

/** What is left to do, as the box says it. */
function leftText(a: StudentAssignment): string {
  const sub = a.my_submission;
  const tasks = a.questions?.length ?? 0;
  return sub && tasks > 1 ? `${sub.questions_submitted} of ${tasks} tasks submitted` : "Not submitted";
}

/**
 * The student home's "Upcoming assignments and code challenges" (under Recently viewed): the open assignments and code challenges of the student's subjects whose
 * deadline falls in the next 7 days and that are not handed in yet, soonest first, as boxes like the subject boxes. A
 * box opens its subject's page with that assignment's details already open (/student/subjects/<id>?assignment=<id>).
 */
export default function DueSoon() {
  // null until the first load; a failure just leaves the section out.
  const [assignments, setAssignments] = useState<StudentAssignment[] | null>(null);
  // The clock behind the deadlines: it moves on every 30 seconds, so a box whose deadline passes drops out by itself.
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    apiFetch<StudentAssignment[]>("/assignments")
      .then(setAssignments)
      .catch(() => setAssignments(null));
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  if (assignments === null) return null;

  const limit = now + DAYS_AHEAD * 24 * 60 * 60 * 1000;
  const due = assignments
    .filter((a) => a.status === "open" && needsSubmitting(a))
    .filter((a) => {
      const at = new Date(a.deadline).getTime();
      return at > now && at <= limit;
    })
    .sort((x, y) => new Date(x.deadline).getTime() - new Date(y.deadline).getTime());
  const shown = due.slice(0, SHOWN);

  return (
    <div className="mt-8" data-testid="due-soon">
      <h2 className="text-xl font-semibold">Upcoming assignments and code challenges</h2>
      <p className="mt-1 text-sm text-gray-600">Due in the next {DAYS_AHEAD} days and not handed in yet.</p>
      {shown.length === 0 ? (
        <p className="empty-state mt-3" data-testid="due-soon-empty">
          Nothing to hand in over the next {DAYS_AHEAD} days.
        </p>
      ) : (
        <>
          <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="due-soon-list">
            {shown.map((a) => {
              const left = timeLeft(a.deadline, now);
              return (
                <li key={a.id}>
                  <Link
                    href={`/student/subjects/${a.subject_id}?assignment=${a.id}`}
                    className="block h-full rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:border-blue-500 hover:bg-blue-50 sm:p-5"
                    data-testid="due-soon-card"
                  >
                    <span className="block break-words text-lg font-bold">{a.name}</span>
                    <span className="block break-words text-xs text-gray-500">
                      {a.subject_name} · {a.assignment_type === "code_challenge" ? "Code challenge" : "Assignment"}
                    </span>
                    <span className="mt-2 block text-sm text-gray-700">Due {formatDateTime(a.deadline)}</span>
                    <span className="mt-2 flex flex-wrap gap-2">
                      {left && (
                        <Badge tone={left.urgent ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-800"}>{left.text}</Badge>
                      )}
                      <Badge tone="border border-amber-500 bg-amber-50 text-amber-900">{leftText(a)}</Badge>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {due.length > shown.length && (
            <p className="mt-2 text-xs text-gray-600">
              Showing the {shown.length} due first of {due.length}. Open a subject to see the rest.
            </p>
          )}
        </>
      )}
    </div>
  );
}
