"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ReactNode, useCallback, useEffect, useState } from "react";
import { apiFetch, CodeWork, StudentAssignment } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { formatDateTime } from "@/lib/datetime";
import { languageNames } from "@/lib/codeLanguages";
import AccountBar from "@/components/AccountBar";
import Badge from "@/components/Badge";
import CodeEditorForm, { editorLanguages } from "@/components/student/CodeEditorForm";

/**
 * A code challenge's own page, opened with Do assignment on its card on the student portal. The questions
 * are shown here and not on the card. The student writes their code and hands the tasks in one at a time
 * (see CodeEditorForm). What was already handed in comes from the server, so the page can be closed and
 * reopened, and still shows the results after the deadline.
 */
export default function CodeChallengePage() {
  const { user, ready } = useRequireRole("student");
  const { id } = useParams<{ id: string }>();
  const [assignment, setAssignment] = useState<StudentAssignment | null>(null);
  const [work, setWork] = useState<CodeWork | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const a = await apiFetch<StudentAssignment>(`/assignments/${id}`);
      if (a.assignment_type !== "code_challenge") {
        setError("This assignment is not a code challenge: open it from your list of assignments.");
        return;
      }
      setWork(await apiFetch<CodeWork>(`/assignments/${id}/my-code`));
      setAssignment(a);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      // A route the server does not have is answered with exactly "Not Found": it is running older code.
      setError(
        reason === "Not Found"
          ? "Could not load the tasks: the server does not have this page yet. It is running an older version of the code, so restart the backend."
          : reason,
      );
    }
  }, [id]);

  useEffect(() => {
    if (!ready || !user) return;
    load();
  }, [ready, user, load]);

  if (!ready || !user) return null;

  const open = assignment?.status === "open";
  let body: ReactNode;
  if (error) {
    body = (
      <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" data-testid="page-error">
        {error}
      </p>
    );
  } else if (!assignment || !work) {
    body = <p className="mt-4 text-sm text-gray-500">Loading...</p>;
  } else if (editorLanguages(assignment).length === 0) {
    body = (
      <p className="mt-4 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800" data-testid="no-editor">
        This challenge cannot be written in the code editor, because it cannot run its language here. Submit it from your
        list of assignments instead.
      </p>
    );
  } else {
    body = (
      <>
        <h1 className="mt-4 text-2xl font-bold">{assignment.name}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
          <span>{assignment.subject_name}</span>
          {assignment.code_languages?.length > 0 && <span>Language: {languageNames(assignment.code_languages)}</span>}
          <span>Deadline: {formatDateTime(assignment.deadline)}</span>
          <Badge tone={open ? "bg-green-50 text-green-800" : "bg-gray-100 text-gray-700"}>{open ? "Open" : "Closed"}</Badge>
        </div>
        {assignment.description && (
          <div className="mt-3">
            <p className="text-sm font-semibold">Description</p>
            <p className="whitespace-pre-wrap text-sm text-gray-700">{assignment.description}</p>
          </div>
        )}
        <CodeEditorForm assignment={assignment} work={work} onWork={setWork} />
      </>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <AccountBar user={user} />
      <Link href="/student" className="text-sm font-semibold text-blue-700 hover:underline">
        ← Back to my assignments
      </Link>
      {body}
    </div>
  );
}
