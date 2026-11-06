"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, Rubric, subjectLabel } from "@/lib/api";
import { setFlash } from "@/lib/flash";
import { useRequireRole } from "@/lib/useRequireRole";
import AssignmentPageLayout from "@/components/instructor/AssignmentPageLayout";
import RubricEditor from "@/components/instructor/RubricEditor";
import PageLoading from "@/components/PageLoading";

/** Edit one rubric: /instructor/subjects/<id>/rubrics/<rubric id>, opened by clicking its box on the Rubrics tab. */
export default function EditRubricPage() {
  const { user, ready } = useRequireRole("instructor");
  const router = useRouter();
  const params = useParams<{ subjectId: string; rubricId: string }>();
  const subjectId = Number(params.subjectId);
  const rubricId = Number(params.rubricId);
  const subject = user?.subjects.find((s) => s.id === subjectId);
  const back = `/instructor/subjects/${subjectId}?tab=rubrics`;

  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const all = await apiFetch<Rubric[]>(`/rubrics?subject_id=${subjectId}`);
      const found = all.find((r) => r.id === rubricId);
      if (found) {
        setRubric(found);
        setError(null);
      } else {
        setError("This rubric was not found in this subject.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [subjectId, rubricId]);

  useEffect(() => {
    if (ready && user && !subject) router.replace("/instructor");
  }, [ready, user, subject, router]);
  useEffect(() => {
    if (ready && user && subject) load();
  }, [ready, user, subject, load]);

  if (!ready || !user || !subject) return <PageLoading />;

  return (
    <AssignmentPageLayout
      user={user}
      backHref={back}
      backLabel="Back to the rubrics"
      title={rubric ? `Edit ${rubric.name}` : "Edit rubric"}
      subtitle={subjectLabel(subject)}
    >
      {error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" data-testid="page-error">
          {error}
        </p>
      ) : !rubric ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <RubricEditor
          rubric={rubric}
          onChanged={load}
          onDeleted={(message) => {
            setFlash(message);
            router.push(back);
          }}
        />
      )}
    </AssignmentPageLayout>
  );
}
