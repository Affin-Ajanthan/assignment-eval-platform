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
import RichText from "@/components/RichText";
import CodeEditorForm, { editorLanguages } from "@/components/student/CodeEditorForm";
import TaskPasswordForm from "@/components/student/TaskPasswordForm";

/**
 * A code challenge's own page, opened with Do assignment on its card on the student portal. It first shows only
 * the title and the instructions, with a Do task button; pressing it (and entering the task password, when the
 * instructor set one) shows the tasks and their questions in the same page (not on the card). The student writes their code and hands the tasks in one at a time
 * (see CodeEditorForm). What was already handed in comes from the server, so the page can be closed and
 * reopened, and still shows the results after the deadline.
 */
export default function CodeChallengePage() {
  const { user, ready } = useRequireRole("student");
  const { id } = useParams<{ id: string }>();
  const [assignment, setAssignment] = useState<StudentAssignment | null>(null);
  const [work, setWork] = useState<CodeWork | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false); // the student pressed Do task: the tasks are shown
  const [asking, setAsking] = useState(false); // the student pressed Do task and is asked for the task password

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
  const taskCount = assignment?.questions?.length ?? 0;
  // Once an answer is handed in the student has plainly begun, so the tasks stay in view when the page is reopened.
  const showTasks = started || (work?.questions.some((q) => q.submitted) ?? false);
  // The instructor's password, until the student has entered it the server does not even send the questions.
  const passwordNeeded = assignment?.has_task_password === true && assignment?.tasks_unlocked === false;
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
            <p className="text-sm font-semibold">Instructions</p>
            <RichText text={assignment.description} className="text-sm text-gray-700" />
          </div>
        )}
        {showTasks && !passwordNeeded ? (
          <CodeEditorForm assignment={assignment} work={work} onWork={setWork} />
        ) : (
          // The tasks are not shown until the student asks for them: this page first gives only the title and
          // the instructions. With a password, pressing the button asks for it.
          <div className="mt-4" data-testid="do-task">
            {taskCount > 1 && <p className="mb-2 text-sm text-gray-700">This assignment has {taskCount} tasks.</p>}
            {assignment.tasks_in_order && taskCount > 1 && (
              <p className="mb-2 text-sm text-gray-700">The tasks are done in order: each one after the one before it.</p>
            )}
            {!asking && (
              <button
                type="button"
                onClick={() => (passwordNeeded ? setAsking(true) : setStarted(true))}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                data-testid="do-task-button"
              >
                {open ? (taskCount > 1 ? "Do tasks" : "Do task") : taskCount > 1 ? "See tasks" : "See task"}
              </button>
            )}
            {asking && passwordNeeded && (
              <TaskPasswordForm
                assignmentId={assignment.id}
                onUnlocked={async () => {
                  await load(); // the questions come with the next answer from the server
                  setStarted(true);
                }}
              />
            )}
          </div>
        )}
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
