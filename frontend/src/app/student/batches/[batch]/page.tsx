"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch, StudentSubject } from "@/lib/api";
import { batchFromSegment, batchTitle } from "@/lib/batches";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import PageHeader from "@/components/PageHeader";
import PageLoading from "@/components/PageLoading";
import StudentSubjectCard from "@/components/student/StudentSubjectCard";

/** One batch of the student: /student/batches/<batch>, every subject in it (joined ones open, the others are locked). */
export default function StudentBatchPage() {
  const { user, ready } = useRequireRole("student");
  const batch = batchFromSegment(useParams<{ batch: string }>().batch);

  // null until the first load.
  const [subjects, setSubjects] = useState<StudentSubject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !user) return;
    apiFetch<StudentSubject[]>("/student/subjects")
      .then((all) => setSubjects(all.filter((s) => (s.batch ?? "").trim() === batch)))
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, [ready, user, batch]);

  if (!ready || !user) return <PageLoading />;

  return (
    <>
      <AccountBar user={user} width="max-w-4xl" />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <PageHeader
          back={{ href: "/student", label: "Home" }}
          title={batchTitle(batch)}
          description="All the subjects in this batch. Open one you have joined to see its assignments; for any other, enter the password your instructor gave you."
        />

        {loadError && (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            Could not load the subjects: {loadError}
          </p>
        )}
        {subjects !== null && subjects.length === 0 && !loadError && (
          <p className="empty-state" data-testid="batch-empty">
            There are no subjects in this batch.
          </p>
        )}
        {subjects !== null && subjects.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2" data-testid="batch-subject-list">
            {subjects.map((s) => (
              <li key={s.id}>
                <StudentSubjectCard subject={s} />
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
