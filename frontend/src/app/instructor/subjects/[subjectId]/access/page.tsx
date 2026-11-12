"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { subjectLabel } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import SubjectAccessPanel from "@/components/instructor/SubjectAccessPanel";
import PageHeader from "@/components/PageHeader";
import PageLoading from "@/components/PageLoading";

/**
 * The student access of one subject: /instructor/subjects/<id>/access, opened by the Student access button on the
 * subject page. The password students join with, whether registration is open and until when.
 */
export default function SubjectAccessPage() {
  const { user, ready } = useRequireRole("instructor");
  const router = useRouter();
  const routeSubject = Number(useParams<{ subjectId: string }>().subjectId);
  const subject = user?.subjects.find((s) => s.id === routeSubject);

  useEffect(() => {
    if (ready && user && !subject) router.replace("/instructor");
  }, [ready, user, subject, router]);

  if (!ready || !user || !subject) return <PageLoading />;

  return (
    <>
      <AccountBar user={user} width="max-w-4xl" />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <PageHeader
          back={{ href: `/instructor/subjects/${subject.id}`, label: "Back to the subject" }}
          title="Student access"
          description={subjectLabel(subject)}
        />
        <SubjectAccessPanel subjectId={subject.id} />
      </main>
    </>
  );
}
