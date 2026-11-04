"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, Assignment } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import PageLoading from "@/components/PageLoading";

/** What a subject box shows: how many of each kind of assignment, and how many submissions wait for a grade. */
type SubjectCounts = { assignments: number; challenges: number; toGrade: number };

/** The instructor's home: every subject they teach as a box. A box opens that subject (/instructor/subjects/<id>). */
export default function InstructorHomePage() {
  const { user, ready } = useRequireRole("instructor");
  // null until the assignments have arrived; a failure leaves the boxes without numbers.
  const [counts, setCounts] = useState<Record<number, SubjectCounts> | null>(null);

  useEffect(() => {
    if (!ready || !user) return;
    apiFetch<Assignment[]>("/assignments")
      .then((all) => {
        const next: Record<number, SubjectCounts> = {};
        for (const a of all) {
          const c = (next[a.subject_id] ??= { assignments: 0, challenges: 0, toGrade: 0 });
          if (a.assignment_type === "code_challenge") {
            c.challenges += 1; // marked by its tests: nothing to grade by hand
          } else {
            c.assignments += 1;
            c.toGrade += Math.max(0, a.submission_count - a.graded_count);
          }
        }
        setCounts(next);
      })
      .catch(() => setCounts({}));
  }, [ready, user]);

  if (!ready || !user) return <PageLoading />;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Your subjects</h1>
      <p className="mt-1 text-sm text-gray-600">
        Choose a subject to set up its assignments and rubrics, then run the automated evaluator and grade the
        submissions -- you always have the final say.
      </p>

      {user.subjects.length === 0 ? (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          You haven&apos;t been assigned to any subjects yet -- ask your admin to assign you to one.
        </p>
      ) : (
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="subject-list">
          {user.subjects.map((s) => {
            const c = counts?.[s.id] ?? { assignments: 0, challenges: 0, toGrade: 0 };
            return (
              <li key={s.id}>
                <Link
                  href={`/instructor/subjects/${s.id}`}
                  className="block h-full rounded-lg border border-gray-200 bg-white p-5 shadow-sm hover:border-blue-500 hover:bg-blue-50"
                  data-testid="subject-card"
                >
                  <span className="block text-lg font-bold">{s.name}</span>
                  <span className="block text-xs text-gray-500">{s.code}</span>
                  {counts && (
                    <span className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
                      <span className="rounded bg-gray-100 px-2 py-0.5 text-gray-700">
                        {c.assignments} assignment{c.assignments === 1 ? "" : "s"}
                      </span>
                      <span className="rounded bg-purple-50 px-2 py-0.5 text-purple-800">
                        {c.challenges} code challenge{c.challenges === 1 ? "" : "s"}
                      </span>
                      {c.toGrade > 0 && (
                        <span className="rounded bg-yellow-100 px-2 py-0.5 text-yellow-800">{c.toGrade} to grade</span>
                      )}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
