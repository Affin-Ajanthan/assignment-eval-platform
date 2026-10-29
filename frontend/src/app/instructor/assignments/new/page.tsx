"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, AssignmentKind, Rubric } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { setFlash } from "@/lib/flash";
import AssignmentForm, { KIND_OPTIONS } from "@/components/instructor/AssignmentForm";
import AssignmentPageLayout from "@/components/instructor/AssignmentPageLayout";

/**
 * Add the details of a new assignment: /instructor/assignments/new?subject=<id>&kind=submission|code_challenge,
 * which the dashboard opens when the instructor chooses the kind of assignment.
 */
export default function NewAssignmentPage() {
  const { user, ready } = useRequireRole("instructor");
  const router = useRouter();
  const [target, setTarget] = useState<{ subjectId: number; kind: AssignmentKind } | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !user) return;
    const query = new URLSearchParams(window.location.search);
    const subjectId = Number(query.get("subject"));
    const kind = KIND_OPTIONS.find((o) => o.value === query.get("kind"))?.value;
    if (!kind || !user.subjects.some((s) => s.id === subjectId)) {
      setError("Choose the subject and the kind of assignment on the instructor dashboard first.");
      return;
    }
    setTarget({ subjectId, kind });
    apiFetch<Rubric[]>(`/rubrics?subject_id=${subjectId}`)
      .then(setRubrics)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [ready, user]);

  if (!ready || !user) return null;

  const back = target ? `/instructor?subject=${target.subjectId}` : "/instructor";
  const kindTitle = KIND_OPTIONS.find((o) => o.value === target?.kind)?.title;
  const subject = user.subjects.find((s) => s.id === target?.subjectId);
  return (
    <AssignmentPageLayout
      user={user}
      backHref={back}
      title={kindTitle ? `New ${kindTitle.toLowerCase()}` : "New assignment"}
      subtitle={subject ? `${subject.name} (${subject.code})` : undefined}
    >
      {error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" data-testid="page-error">
          {error}
        </p>
      ) : !target || !rubrics ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <AssignmentForm
          subjectId={target.subjectId}
          kind={target.kind}
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
