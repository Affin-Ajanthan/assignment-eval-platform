"use client";

import { useEffect, useState } from "react";
import { apiFetch, StudentSubject } from "@/lib/api";
import { groupByBatch } from "@/lib/batches";
import { readRecentSubjects } from "@/lib/recentSubjects";
import BatchList from "@/components/BatchList";
import DueSoon from "@/components/student/DueSoon";
import StudentSubjectCard from "@/components/student/StudentSubjectCard";

/** How many "Recently viewed" boxes the home page shows. */
const RECENT_SHOWN = 6;

/**
 * The student's subjects (GET /student/subjects): the few they opened last as boxes, then the batches. A batch opens
 * the page with all its subjects (/student/batches/<batch>); a subject opens its own page (/student/subjects/<id>):
 * its assignments if the student joined it, the page where the instructor's password is entered if not.
 */
export default function StudentSubjects({ userId }: { userId: number }) {
  // null until the first load.
  const [subjects, setSubjects] = useState<StudentSubject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recentIds, setRecentIds] = useState<number[]>([]);

  useEffect(() => {
    setRecentIds(readRecentSubjects("student", userId));
    apiFetch<StudentSubject[]>("/student/subjects")
      .then(setSubjects)
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, [userId]);

  const recent = (subjects ?? [])
    .map((s) => ({ s, at: recentIds.indexOf(s.id) }))
    .filter((x) => x.at >= 0)
    .sort((a, b) => a.at - b.at)
    .slice(0, RECENT_SHOWN)
    .map((x) => x.s);

  return (
    <section className="mt-6" data-testid="student-subjects">
      {loadError && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load the subjects: {loadError}
        </p>
      )}

      {recent.length > 0 && (
        <div data-testid="recent-subjects">
          <h2 className="text-xl font-semibold">Recently viewed</h2>
          <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="student-subject-list">
            {recent.map((s) => (
              <li key={s.id}>
                <StudentSubjectCard subject={s} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Under the recently viewed subjects: what is due soon and not handed in. */}
      <DueSoon />

      <h2 className="mt-8 text-xl font-semibold">Batches</h2>
      <p className="mt-1 text-sm text-gray-600">
        Choose a batch to see all its subjects. Open one you have joined to see its assignments. For any other, open it
        and enter the password your instructor gave you.
      </p>
      {subjects !== null && subjects.length === 0 && !loadError && (
        <p className="empty-state mt-2">There are no subjects yet.</p>
      )}
      {subjects !== null && subjects.length > 0 && (
        <BatchList groups={groupByBatch(subjects)} hrefBase="/student/batches" testId="batch-list" />
      )}
    </section>
  );
}
