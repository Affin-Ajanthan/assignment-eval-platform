"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch, Assignment, Rubric } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { setFlash } from "@/lib/flash";
import AssignmentForm from "@/components/instructor/AssignmentForm";
import AssignmentPageLayout from "@/components/instructor/AssignmentPageLayout";

/** Edit an assignment: /instructor/assignments/<id>, opened by Edit on the instructor dashboard. */
export default function EditAssignmentPage() {
  const { user, ready } = useRequireRole("instructor");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !user) return;
    (async () => {
      try {
        const a = await apiFetch<Assignment>(`/assignments/${id}`);
        setRubrics(await apiFetch<Rubric[]>(`/rubrics?subject_id=${a.subject_id}`));
        setAssignment(a);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [ready, user, id]);

  if (!ready || !user) return null;

  const back = assignment ? `/instructor?subject=${assignment.subject_id}` : "/instructor";
  return (
    <AssignmentPageLayout
      user={user}
      backHref={back}
      title={assignment ? `Edit ${assignment.name}` : "Edit assignment"}
      subtitle={assignment?.subject_name}
    >
      {error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" data-testid="page-error">
          {error}
        </p>
      ) : !assignment || !rubrics ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <AssignmentForm
          subjectId={assignment.subject_id}
          kind={assignment.assignment_type ?? "submission"}
          assignment={assignment}
          rubrics={rubrics}
          onSaved={(message) => {
            setFlash(message);
            router.push(back);
          }}
          onCancel={() => router.push(back)}
        />
      )}
    </AssignmentPageLayout>
  );
}
