"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, Assignment, Subject } from "@/lib/api";

/** What a subject box shows: how many of each kind of assignment, and how many submissions wait for a grade. */
export type SubjectCounts = { assignments: number; challenges: number; toGrade: number };

/**
 * The counts for every subject the instructor teaches (GET /assignments), or null until they have arrived. A failure
 * leaves the boxes without numbers.
 */
export function useSubjectCounts(enabled: boolean): Record<number, SubjectCounts> | null {
  const [counts, setCounts] = useState<Record<number, SubjectCounts> | null>(null);

  useEffect(() => {
    if (!enabled) return;
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
  }, [enabled]);

  return counts;
}

/** One of the instructor's subjects as a box. It opens that subject (/instructor/subjects/<id>). */
export default function InstructorSubjectCard({
  subject: s,
  counts,
}: {
  subject: Subject;
  counts: Record<number, SubjectCounts> | null;
}) {
  const c = counts?.[s.id] ?? { assignments: 0, challenges: 0, toGrade: 0 };
  return (
    <Link
      href={`/instructor/subjects/${s.id}`}
      className="block h-full rounded-lg border border-gray-200 bg-white p-5 shadow-sm hover:border-blue-500 hover:bg-blue-50"
      data-testid="subject-card"
    >
      <span className="block text-lg font-bold">{s.name}</span>
      <span className="block text-xs text-gray-500">
        {s.code}
        {s.batch ? ` · Batch ${s.batch}` : ""}
      </span>
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
  );
}
