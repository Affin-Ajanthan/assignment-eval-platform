"use client";

import Link from "next/link";
import { StudentAssignment } from "@/lib/api";
import { formatDateTime, formatMark } from "@/lib/datetime";
import Badge from "@/components/Badge";
import Message, { MessageState } from "@/components/Message";
import SelfCheckPanel from "@/components/student/SelfCheckPanel";
import UploadForm from "@/components/student/UploadForm";
import { editorLanguages } from "@/components/student/CodeEditorForm";
import { OpenForm, TYPE_LABEL } from "@/components/student/labels";
import { languageNames } from "@/lib/codeLanguages";

/** One assignment: details, marks and feedback, submit/edit/delete, and the self-checks. */
export default function AssignmentCard({
  a,
  openForm,
  setOpenForm,
  onChanged,
  askDelete,
  notice,
}: {
  a: StudentAssignment;
  openForm: OpenForm;
  setOpenForm: (v: OpenForm) => void;
  onChanged: (assignmentId: number, text: string) => Promise<void>;
  askDelete: (a: StudentAssignment) => void;
  notice: MessageState;
}) {
  const sub = a.my_submission;
  // A code challenge is answered by typing code on the challenge's own page (checking it with Run, then handing
  // in one task at a time), not by uploading a file. Only when the server can run its language: otherwise
  // the usual upload form is used.
  const isChallenge = a.assignment_type === "code_challenge";
  const useEditor = isChallenge && editorLanguages(a).length > 0;
  const taskCount = a.questions?.length ?? 0;
  const manyTasks = isChallenge && taskCount > 1;
  const submissionStatus = !sub
    ? "Not submitted"
    : manyTasks
      ? `${sub.questions_submitted} of ${taskCount} tasks submitted`
      : sub.status === "graded"
        ? "Graded"
        : "Submitted";
  const files = sub
    ? [sub.has_code && "code", sub.has_report && "report", sub.has_video && "video"].filter(Boolean).join(", ")
    : "";
  const formMode = openForm?.id === a.id ? openForm.mode : null;
  const closeForm = () => setOpenForm(null);
  const finishForm = async (text: string) => {
    setOpenForm(null);
    await onChanged(a.id, text);
  };
  // The way into the challenge's page: while it is open, to do the assignment or to carry on with the tasks
  // still to hand in; and afterwards, to see the code and the result.
  const moreToHandIn = a.status === "open" && !!sub && sub.questions_submitted < Math.max(1, taskCount);
  const codeLink =
    useEditor && (a.status === "open" || sub) ? (
      <Link
        href={`/student/code/${a.id}`}
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
        data-testid="open-code-page"
      >
        {!sub ? "Do assignment" : moreToHandIn ? "Continue assignment" : "See your code and result"}
      </Link>
    ) : null;

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm" data-testid="student-assignment">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-bold">{a.name}</h3>
          <p className="text-xs text-gray-500">{a.subject_name}</p>
          <p className="text-xs text-gray-500">Accepts: {a.submission_types.map((t) => TYPE_LABEL[t]).join(", ")}</p>
          {a.submission_types.includes("code") && a.code_languages?.length > 0 && (
            <p className="text-xs text-gray-500">Language: {languageNames(a.code_languages)}</p>
          )}
        </div>
        <Badge tone={a.status === "open" ? "bg-green-50 text-green-800" : "bg-gray-100 text-gray-700"}>
          {a.status === "open" ? "Open" : "Closed"}
        </Badge>
      </div>

      {/* A code challenge is done on its own page: its description and its questions are shown there, after the
          student presses Do assignment, and not on the card. */}
      {a.description && !useEditor && (
        <div className="mt-3">
          <p className="text-sm font-semibold">Description</p>
          <p className="whitespace-pre-wrap text-sm text-gray-700">{a.description}</p>
        </div>
      )}

      {useEditor && a.status === "open" && (
        <div className="mt-3" data-testid="questions-hidden-note">
          {manyTasks && <p className="text-sm font-semibold">{taskCount} tasks</p>}
          <p className="text-xs text-gray-500">
            {manyTasks
              ? "The questions are shown when you press Do assignment, and you hand the tasks in one at a time. Each task is marked as soon as you submit it and cannot be changed afterwards; the mark adds up the test cases you pass in every task."
              : "The question is shown when you press Do assignment. Your code is marked as soon as you submit it, and cannot be changed afterwards."}
          </p>
        </div>
      )}

      <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
        <dt className="font-semibold">Available from</dt>
        <dd>{formatDateTime(a.available_from)}</dd>
        <dt className="font-semibold">Submission deadline</dt>
        <dd>{formatDateTime(a.deadline)}</dd>
        <dt className="font-semibold">Status</dt>
        <dd>
          {submissionStatus}
          {sub && !manyTasks && ` (${formatDateTime(sub.submitted_at)}${files ? ` — ${files}` : ""})`}
        </dd>
        {sub && (
          <>
            <dt className="font-semibold">Marks</dt>
            <dd data-testid="marks">
              {a.marks_release_at
                ? `Marks will be released on ${formatDateTime(a.marks_release_at)}`
                : formatMark(sub.final_mark, sub.max_mark)}
            </dd>
          </>
        )}
      </dl>

      {sub && sub.final_mark !== null && (sub.criterion_marks.length > 0 || sub.feedback) && (
        <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3" data-testid="my-feedback">
          {sub.criterion_marks.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500">
                  <th className="pb-1 font-semibold">Criterion</th>
                  <th className="pb-1 text-right font-semibold">Marks</th>
                </tr>
              </thead>
              <tbody>
                {sub.criterion_marks.map((c) => (
                  <tr key={c.name} className="border-t border-gray-200">
                    <td className="py-1 pr-3">{c.name}</td>
                    <td className="whitespace-nowrap py-1 text-right">{formatMark(c.score, c.max_points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {sub.feedback && (
            <div className={sub.criterion_marks.length > 0 ? "mt-3" : ""}>
              <p className="text-sm font-semibold">Feedback from your instructor</p>
              <p className="whitespace-pre-wrap text-sm text-gray-700">{sub.feedback}</p>
            </div>
          )}
        </div>
      )}

      {/* A challenge is marked when it is submitted; if that could not happen then, the student can ask again on
          the challenge's page. Not while marks are held back: the student cannot tell marked from unmarked until
          the release date. */}
      {isChallenge && sub && sub.final_mark === null && !a.marks_release_at && (
        <p className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-900" data-testid="not-marked-note">
          Your code is submitted, but it has no mark yet. Open the assignment and press Get my marks.
        </p>
      )}

      {(a.status === "open" || codeLink) && !formMode && (
        <div className="mt-4 flex flex-wrap gap-2">
          {codeLink}
          {a.status === "open" && !sub && !useEditor && (
            <button
              type="button"
              onClick={() => setOpenForm({ id: a.id, mode: "submit" })}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Submit assignment
            </button>
          )}
          {a.status === "open" && sub?.can_edit && (
            <>
              <button
                type="button"
                onClick={() => setOpenForm({ id: a.id, mode: "edit" })}
                className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
              >
                Edit submission
              </button>
              <button
                type="button"
                onClick={() => askDelete(a)}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
              >
                Delete submission
              </button>
            </>
          )}
        </div>
      )}
      {a.status === "closed" && !sub && <p className="mt-3 text-sm text-gray-600">The deadline has passed.</p>}

      {a.status === "open" && sub && sub.status !== "graded" && !formMode && (
        <SelfCheckPanel assignment={a} submission={sub} />
      )}

      {formMode && <UploadForm assignment={a} mode={formMode} onCancel={closeForm} onDone={finishForm} />}
      {notice && <Message state={notice} />}
    </li>
  );
}
