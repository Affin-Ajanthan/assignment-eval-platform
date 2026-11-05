"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, StudentSubject } from "@/lib/api";

/**
 * Every subject there is (GET /student/subjects), as boxes. Each opens its own page (/student/subjects/<id>): for a
 * subject the student joined that is its assignments, for any other it is the page where the instructor's password is
 * entered.
 */
export default function StudentSubjects() {
  // null until the first load.
  const [subjects, setSubjects] = useState<StudentSubject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<StudentSubject[]>("/student/subjects")
      .then(setSubjects)
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <section className="mt-6" data-testid="student-subjects">
      <h2 className="text-xl font-semibold">Subjects</h2>
      <p className="mt-1 text-sm text-gray-600">
        Every subject is listed. Open one you have joined to see its assignments. For any other, open it and enter the
        password your instructor gave you.
      </p>
      {loadError && (
        <p role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load the subjects: {loadError}
        </p>
      )}
      {subjects !== null && subjects.length === 0 && !loadError && (
        <p className="empty-state mt-2">There are no subjects yet.</p>
      )}
      {subjects !== null && subjects.length > 0 && (
        <ul className="mt-4 grid gap-4 sm:grid-cols-2" data-testid="student-subject-list">
          {subjects.map((s) => (
            <li key={s.id}>
              <Link
                href={`/student/subjects/${s.id}`}
                className={`block h-full rounded-lg border p-5 shadow-sm hover:border-blue-500 hover:bg-blue-50 ${
                  s.joined ? "border-gray-200 bg-white" : "border-gray-200 bg-gray-50"
                }`}
                data-testid={s.joined ? "subject-card" : "locked-subject"}
              >
                <span className="block text-lg font-bold">{s.name}</span>
                <span className="block text-xs text-gray-500">
                  {s.code}
                  {s.batch ? ` · Batch ${s.batch}` : ""}
                </span>
                {s.teachers.length > 0 && (
                  <span className="mt-1 block text-xs text-gray-500">{s.teachers.map((t) => t.name).join(", ")}</span>
                )}
                {s.joined ? (
                  <span className="mt-2 inline-block rounded bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-800">
                    Joined · open
                  </span>
                ) : (
                  <span className="mt-2 inline-block rounded bg-gray-200 px-2 py-0.5 text-xs font-semibold text-gray-700">
                    {s.registration_open ? "Not joined · enter the password" : "Not joined · registration not open yet"}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
