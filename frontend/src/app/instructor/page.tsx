"use client";

import { useEffect, useState } from "react";
import { groupByBatch } from "@/lib/batches";
import { readRecentSubjects } from "@/lib/recentSubjects";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import BatchList from "@/components/BatchList";
import InstructorSubjectCard, { useSubjectCounts } from "@/components/instructor/InstructorSubjectCard";
import PageLoading from "@/components/PageLoading";
import PageHeader from "@/components/PageHeader";

/** How many "Recently viewed" boxes the home page shows. */
const RECENT_SHOWN = 6;

/**
 * The instructor's home: the subjects they opened last as boxes, then the batches of the subjects they teach. A batch
 * opens the page with its subjects (/instructor/batches/<batch>); a subject opens its page (/instructor/subjects/<id>).
 */
export default function InstructorHomePage() {
  const { user, ready } = useRequireRole("instructor");
  const counts = useSubjectCounts(ready && !!user);
  const [recentIds, setRecentIds] = useState<number[]>([]);

  useEffect(() => {
    if (ready && user) setRecentIds(readRecentSubjects("instructor", user.id));
  }, [ready, user]);

  if (!ready || !user) return <PageLoading />;

  const recent = user.subjects
    .map((s) => ({ s, at: recentIds.indexOf(s.id) }))
    .filter((x) => x.at >= 0)
    .sort((a, b) => a.at - b.at)
    .slice(0, RECENT_SHOWN)
    .map((x) => x.s);

  return (
    <>
      <AccountBar user={user} width="max-w-6xl" />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <PageHeader
          title="Your subjects"
          description="Choose a batch to see its subjects, then set up a subject's assignments and rubrics, run the automated evaluator and grade the submissions -- you always have the final say."
        />

        {user.subjects.length === 0 ? (
          <p className="empty-state">
            You haven&apos;t been assigned to any subjects yet. Ask your administrator to assign you to one.
          </p>
        ) : (
          <>
            {recent.length > 0 && (
              <div data-testid="recent-subjects">
                <h2 className="text-xl font-semibold">Recently viewed</h2>
                <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="subject-list">
                  {recent.map((s) => (
                    <li key={s.id}>
                      <InstructorSubjectCard subject={s} counts={counts} />
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <h2 className={`text-xl font-semibold ${recent.length > 0 ? "mt-8" : ""}`}>Batches</h2>
            <BatchList groups={groupByBatch(user.subjects)} hrefBase="/instructor/batches" testId="batch-list" />
          </>
        )}
      </main>
    </>
  );
}
