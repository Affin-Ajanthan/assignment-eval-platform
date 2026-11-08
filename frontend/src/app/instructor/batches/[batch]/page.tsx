"use client";

import { useParams } from "next/navigation";
import { batchFromSegment, batchTitle } from "@/lib/batches";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import InstructorSubjectCard, { useSubjectCounts } from "@/components/instructor/InstructorSubjectCard";
import PageHeader from "@/components/PageHeader";
import PageLoading from "@/components/PageLoading";

/** One batch of the instructor: /instructor/batches/<batch>, the subjects they teach in it. */
export default function InstructorBatchPage() {
  const { user, ready } = useRequireRole("instructor");
  const batch = batchFromSegment(useParams<{ batch: string }>().batch);
  const counts = useSubjectCounts(ready && !!user);

  if (!ready || !user) return <PageLoading />;

  const subjects = user.subjects.filter((s) => (s.batch ?? "").trim() === batch);

  return (
    <>
      <AccountBar user={user} width="max-w-6xl" />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <PageHeader
          back={{ href: "/instructor", label: "Home" }}
          title={batchTitle(batch)}
          description="The subjects you teach in this batch. Open one to set up its assignments and rubrics and to grade the submissions."
        />

        {subjects.length === 0 ? (
          <p className="empty-state" data-testid="batch-empty">
            You teach no subjects in this batch.
          </p>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="batch-subject-list">
            {subjects.map((s) => (
              <li key={s.id}>
                <InstructorSubjectCard subject={s} counts={counts} />
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
