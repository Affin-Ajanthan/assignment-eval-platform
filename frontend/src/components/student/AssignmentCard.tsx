"use client";

import Link from "next/link";
import { StudentAssignment } from "@/lib/api";
import { taskName, timedTasks, timeLimitText } from "@/lib/tasks";
import { formatDateTime, formatMark, timeLeft } from "@/lib/datetime";
import { lateText, markWithPenalty, penaltyText } from "@/lib/late";
import Badge from "@/components/Badge";
import RichText from "@/components/RichText";
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
  // The late rule as the student is told it: the penalty per day late in the unit the instructor chose, and its limit.
  const inMarks = a.late_penalty_unit === "marks";
  const perDay = (inMarks ? a.late_penalty_marks : a.late_penalty_percent) ?? 0;
  const capText = inMarks
    ? a.late_penalty_max_marks != null
      ? penaltyText(0, a.late_penalty_max_marks)
      : ""
    : (a.late_penalty_max_percent ?? 100) < 100
      ? penaltyText(a.late_penalty_max_percent, 0)
      : "";
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
  // "Due in 3 days" on an open assignment; red under 24 hours.
  const due = a.status === "open" ? timeLeft(a.deadline) : null;
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
        className="btn-primary rounded-md px-4 py-2 text-sm font-semibold"
        data-testid="open-code-page"
      >
        {!sub ? "Do assignment" : moreToHandIn ? "Continue assignment" : "See your code and result"}
      </Link>
    ) : null;

  return (
    <li className="card" data-testid="student-assignment">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold">{a.name}</h3>
          <p className="text-xs text-gray-500">{a.subject_name}</p>
          <p className="text-xs text-gray-500">Accepts: {a.submission_types.map((t) => TYPE_LABEL[t]).join(", ")}</p>
          {a.submission_types.includes("code") && a.code_languages?.length > 0 && (
            <p className="text-xs text-gray-500">Language: {languageNames(a.code_languages)}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {due && (
            <Badge tone={due.urgent ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-800"}>
              <span data-testid="due-badge" title={`Deadline: ${formatDateTime(a.deadline)}`}>
                {due.text}
              </span>
            </Badge>
          )}
          <Badge tone={a.status === "open" ? "bg-green-50 text-green-800" : "bg-gray-100 text-gray-700"}>
            {a.status === "open" ? "Open" : "Closed"}
          </Badge>
        </div>
      </div>

      {/* A code challenge is done on its own page: its description and its questions are shown there, after the
          student presses Do assignment, and not on the card. */}
      {a.description && !useEditor && (
        <div className="mt-3">
          <p className="text-sm font-semibold">Description</p>
          <RichText text={a.description} className="text-sm text-gray-700" />
        </div>
      )}

      {useEditor && a.status === "open" && (
        <div className="mt-3" data-testid="questions-hidden-note">
          {manyTasks && <p className="text-sm font-semibold">{taskCount} tasks</p>}
          {a.has_task_password && !a.tasks_unlocked && (
            <p className="text-xs text-gray-500" data-testid="password-note">
              You need the password from your instructor to start the tasks.
            </p>
          )}
          {timedTasks(a.questions).length > 0 && (
            <p className="text-xs font-semibold text-blue-800" data-testid="time-limit-note">
              ⏱ Timed:{" "}
              {timedTasks(a.questions)
                .map((q) => `${manyTasks ? `${taskName(q)}: ` : ""}${timeLimitText(q.time_limit_seconds ?? 0)}`)
                .join(" · ")}
              . The clock starts when you open the task.
            </p>
          )}
          {manyTasks && a.tasks_in_order && (
            <p className="text-xs text-gray-500" data-testid="order-note">
              The tasks are done in order: you can start a task only after handing in the one before it.
            </p>
          )}
          <p className="text-xs text-gray-500">
            {manyTasks
              ? "The questions are shown when you press Do assignment and then Do task, and you hand the tasks in one at a time. Each task is marked as soon as you submit it and cannot be changed afterwards; the mark adds up the test cases you pass in every task."
              : "The question is shown when you press Do assignment and then Do task. Your code is marked as soon as you submit it, and cannot be changed afterwards."}
          </p>
        </div>
      )}

      {a.status === "open" && a.past_deadline && (
        <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800" data-testid="late-notice">
          The deadline has passed.{" "}
          {(a.penalty_now_percent ?? 0) > 0 || (a.penalty_now_marks ?? 0) > 0
            ? `Work handed in now is marked Late and loses ${penaltyText(a.penalty_now_percent, a.penalty_now_marks)}${
                inMarks ? "" : " of its mark"
              }${
                perDay > 0 ? ` (${penaltyText(a.late_penalty_percent, a.late_penalty_marks)} for every day or part of a day late` : ""
              }${perDay > 0 && capText ? `, at most ${capText}` : ""}${perDay > 0 ? ")" : ""}.`
            : "Work handed in now still counts as on time (grace period)."}
          {a.accept_until && ` Work is accepted until ${formatDateTime(a.accept_until)}.`}
        </p>
      )}
      {sub?.late_seconds != null && (
        <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800" data-testid="submitted-late">
          You handed this in late: {lateText(sub.late_seconds)} after the deadline
          {(sub.late_penalty_percent ?? 0) > 0 || (sub.late_penalty_marks ?? 0) > 0
            ? `, so ${penaltyText(sub.late_penalty_percent, sub.late_penalty_marks)} is taken off the mark`
            : ""}.
        </p>
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
                : markWithPenalty(sub.raw_mark, sub.final_mark, sub.max_mark, sub.late_penalty_percent, sub.late_penalty_marks)}
            </dd>
          </>
        )}
      </dl>

      {sub && sub.final_mark !== null && (sub.criterion_marks.length > 0 || sub.feedback) && (
        <div className="mt-4 rounded-md border border-gray-200 border-l-4 border-l-green-700 bg-gray-50 p-4" data-testid="my-feedback">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="text-base font-semibold">Your marks and feedback</h4>
            <span className="text-xl font-semibold text-brand-700">
              {markWithPenalty(sub.raw_mark, sub.final_mark, sub.max_mark, sub.late_penalty_percent, sub.late_penalty_marks)}
            </span>
          </div>
          {sub.criterion_marks.length > 0 && (
            <table className="mt-2 w-full text-sm">
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
              <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">{sub.feedback}</p>
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
              className="btn-primary rounded-md px-4 py-2 text-sm font-semibold"
            >
              Submit assignment
            </button>
          )}
          {a.status === "open" && sub?.can_edit && (
            <button
              type="button"
              onClick={() => setOpenForm({ id: a.id, mode: "edit" })}
              className="btn-secondary rounded-md px-4 py-2 text-sm font-semibold"
            >
              Edit submission
            </button>
          )}
          {a.status === "open" && sub?.can_delete && (
            <button
              type="button"
              onClick={() => askDelete(a)}
              className="btn-danger rounded-md px-4 py-2 text-sm font-semibold"
            >
              Delete submission
            </button>
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
