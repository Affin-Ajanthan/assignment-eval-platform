"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { subjectLabel } from "@/lib/api";
import { setFlash } from "@/lib/flash";
import { useRequireRole } from "@/lib/useRequireRole";
import AssignmentPageLayout from "@/components/instructor/AssignmentPageLayout";
import RubricCreateForm from "@/components/instructor/RubricCreateForm";
import PageLoading from "@/components/PageLoading";

/** Add a rubric: /instructor/subjects/<id>/rubrics/new, opened by + New on the Rubrics tab. */
export default function NewRubricPage() {
  const { user, ready } = useRequireRole("instructor");
  const router = useRouter();
  const routeSubject = Number(useParams<{ subjectId: string }>().subjectId);
  const subject = user?.subjects.find((s) => s.id === routeSubject);
  const back = `/instructor/subjects/${routeSubject}?tab=rubrics`;

  useEffect(() => {
    if (ready && user && !subject) router.replace("/instructor");
  }, [ready, user, subject, router]);

  if (!ready || !user || !subject) return <PageLoading />;

  return (
    <AssignmentPageLayout
      user={user}
      backHref={back}
      backLabel="Back to the rubrics"
      title="New rubric"
      subtitle={subjectLabel(subject)}
    >
      <RubricCreateForm
        subjects={user.subjects}
        subjectId={subject.id}
        onSaved={(message, savedSubjectId) => {
          setFlash(message);
          // Back to the rubrics of the subject it was saved for, which may not be the one the form was opened from.
          router.push(`/instructor/subjects/${savedSubjectId}?tab=rubrics`);
        }}
        onCancel={() => router.push(back)}
      />
    </AssignmentPageLayout>
  );
}
