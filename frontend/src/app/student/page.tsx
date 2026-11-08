"use client";

import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import StudentSubjects from "@/components/student/StudentSubjects";
import SubmissionHistory from "@/components/student/SubmissionHistory";
import PageLoading from "@/components/PageLoading";
import PageHeader from "@/components/PageHeader";

/**
 * The student's home: the subjects opened last as boxes, then the batches (each opens a page with all its subjects).
 * A subject the student joined opens its own page with its assignments (/student/subjects/<id>); the others stay
 * locked until the student joins them with the instructor's password.
 */
export default function StudentPage() {
  const { user, ready } = useRequireRole("student");

  if (!ready || !user) return <PageLoading />;

  return (
    <>
      <AccountBar user={user} width="max-w-4xl" />
      <main className="mx-auto max-w-4xl px-4 py-8">

      <PageHeader
        title="Student portal"
        description="Open a subject to see its assignments and submit your work before the deadline. You can edit or delete a submission until the deadline or until it is graded."
      />

      <StudentSubjects userId={user.id} />

      {/* Loads when opened, so it is current whenever it is looked at. */}
      <SubmissionHistory version={0} />
      </main>
    </>
  );
}
