"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, Assignment, AssignmentKind, subjectLabel } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import AssignmentsSection, { KIND_LIST_LABEL } from "@/components/instructor/AssignmentsSection";
import PageHeader from "@/components/PageHeader";
import PageLoading from "@/components/PageLoading";

/**
 * The existing assignments of one kind in a subject: /instructor/subjects/<id>/assignments?kind=submission|code_challenge,
 * opened from the Assignments tab of the subject page. "+ New" at the top right creates another of that kind; a box
 * opens its details to edit.
 */
export default function SubjectAssignmentsPage() {
  const { user, ready } = useRequireRole("instructor");
  const router = useRouter();
  const routeSubject = Number(useParams<{ subjectId: string }>().subjectId);
  const subjectId: number | null = user?.subjects.some((s) => s.id === routeSubject) ? routeSubject : null;

  // Which kind: ?kind= in the address (read once the page is in the browser).
  const [kind, setKind] = useState<AssignmentKind | null>(null);
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("kind");
    setKind(wanted === "code_challenge" ? "code_challenge" : "submission");
  }, []);

  useEffect(() => {
    if (ready && user && subjectId === null) router.replace("/instructor");
  }, [ready, user, subjectId, router]);

  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    if (subjectId === null) return;
    try {
      setAssignments(await apiFetch<Assignment[]>(`/assignments?subject_id=${subjectId}`));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, [subjectId]);
  useEffect(() => {
    reload();
  }, [reload]);

  if (!ready || !user || kind === null) return <PageLoading />;
  const subject = user.subjects.find((s) => s.id === subjectId);

  return (
    <>
      <AccountBar user={user} width="max-w-6xl" />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <PageHeader
          back={{ href: `/instructor/subjects/${subjectId}?tab=assignments`, label: "Back to the subject" }}
          title={KIND_LIST_LABEL[kind].title}
          description={subject ? subjectLabel(subject) : undefined}
        >
          {subjectId !== null && (
            <Link
              href={`/instructor/assignments/new?subject=${subjectId}&kind=${kind}`}
              className="btn-primary rounded-md px-4 py-2 text-sm font-semibold"
              data-testid="new-assignment"
            >
              + New
            </Link>
          )}
        </PageHeader>

        {loadError && (
          <p role="alert" className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            Could not load the assignments: {loadError}
          </p>
        )}
        {subjectId !== null && (
          <AssignmentsSection subjectId={subjectId} kind={kind} assignments={assignments} onChanged={reload} />
        )}
      </main>
    </>
  );
}
