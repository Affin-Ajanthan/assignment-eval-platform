"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { StudentAssignment, SubmissionType } from "@/lib/api";
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

// The short names in the phone summary ("Presentation video" is too long for one row of three).
const SHORT_LABEL: Record<SubmissionType, string> = { code: "Code", report: "Report", video: "Video" };

/**
 * One assignment: details, marks and feedback, submit/edit/delete, and the self-checks.
 *
 * On a phone (below the md breakpoint) the card starts compact: the status, the deadline, which parts are handed in,
 * the mark and the main action. "View details" opens the rest. This is done with CSS only, so from md up the card is
 * always shown in full and the details button doesn't exist.
 */
export default function AssignmentCard({
  a,
  openForm,
  setOpenForm,
  onChanged,
  askDelete,
  notice,
  hiddenOnPhone = false,
}: {
  a: StudentAssignment;
  openForm: OpenForm;
  setOpenForm: (v: OpenForm) => void;
  onChanged: (assignmentId: number, text: string) => Promise<void>;
  askDelete: (a: StudentAssignment) => void;
  notice: MessageState;
  /** The phone-only filter tabs on the page leave this card out. */
  hiddenOnPhone?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const cardRef = useRef<HTMLLIElement>(null);
  // Parts of the card that a phone shows only after "View details".
  const details = expanded ? "" : "max-md:hidden";
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
      : // Closed, and the instructor holds the marks back until a date. The server reports every submission as
        // "submitted" until then (whether it is graded stays hidden), so this says what the student can know.
        a.marks_release_at && a.status === "closed"
        ? "Awaiting marks"
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
        className="btn-primary min-h-11 rounded-md px-4 py-2 text-sm font-semibold md:min-h-0"
        data-testid="open-code-page"
      >
        {!sub ? "Do assignment" : moreToHandIn ? "Continue assignment" : "See your code and result"}
      </Link>
    ) : null;

  // The student's own state, shown apart from the assignment's: from the same fields as before, nothing recomputed.
  const late = sub?.late_seconds != null;
  const statusTone = !sub
    ? a.status === "open"
      ? "border border-amber-500 bg-amber-50 text-amber-900"
      : "border border-gray-300 bg-gray-100 text-gray-700"
    : sub.status === "graded" && !a.marks_release_at
      ? "border border-green-700 bg-green-50 text-green-800"
      : "border border-blue-200 bg-blue-50 text-blue-800";
  const markShown = sub
    ? a.marks_release_at
      ? null
      : markWithPenalty(sub.raw_mark, sub.final_mark, sub.max_mark, sub.late_penalty_percent, sub.late_penalty_marks)
    : null;
  const graded = !!sub && sub.final_mark !== null && !a.marks_release_at;
  const marksText = a.marks_release_at ? `Marks will be released on ${formatDateTime(a.marks_release_at)}` : markShown;
  const hasFeedback = !!sub && sub.final_mark !== null && (sub.criterion_marks.length > 0 || !!sub.feedback);
  // The main thing to do next stays on the compact card; editing and deleting are in the details.
  const hasMainAction = !!codeLink || (a.status === "open" && !sub && !useEditor);
  const handedIn: Record<SubmissionType, boolean> = {
    code: !!sub?.has_code,
    report: !!sub?.has_report,
    video: !!sub?.has_video,
  };
  const dueTone = due?.urgent
    ? "bg-red-50 text-red-700"
    : due?.soon
      ? "border border-amber-500 bg-amber-50 text-amber-900"
      : "bg-blue-50 text-blue-800";

  function toggleDetails() {
    // Closing a long card moves what is below it up: keep the card itself on the screen.
    if (expanded) cardRef.current?.scrollIntoView({ block: "nearest" });
    setExpanded(!expanded);
  }

  return (
    <li
      ref={cardRef}
      className={`card assignment-card ${hiddenOnPhone ? "max-md:hidden" : ""}`}
      data-testid="student-assignment"
    >
      {/* Identity: title, subject, and the two kinds of status side by side but never mixed up. */}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold">{a.name}</h3>
          <p className="text-sm text-gray-600">
            {a.subject_name}
            {isChallenge && <span className="text-gray-500"> · Code challenge</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* On a phone one status is enough: the section heading above the card already says open or past. */}
          <span className="inline-flex max-md:hidden">
            <span className="sr-only">Assignment:</span>
            <Badge tone={a.status === "open" ? "bg-green-50 text-green-800" : "bg-gray-100 text-gray-700"}>
              {a.status === "open" ? "Open" : "Closed"}
            </Badge>
          </span>
          <span className="sr-only">Your submission:</span>
          <Badge tone={statusTone}>
            <span data-testid="submission-status-badge">{submissionStatus}</span>
          </Badge>
          {late && (
            <Badge tone="border border-red-700 bg-red-50 text-red-800">
              <span data-testid="late-badge">Late</span>
            </Badge>
          )}
        </div>
      </div>

      {/* The phone summary: what a student needs at a glance. From md up the same facts are in the panel below. */}
      <div className="mt-3 space-y-2 text-sm md:hidden" data-testid="card-summary">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold text-gray-900">
            {a.status === "closed" ? "Closed" : a.past_deadline ? "Was due" : "Due"} {formatDateTime(a.deadline)}
          </span>
          {due && <Badge tone={dueTone}>{due.text}</Badge>}
        </p>
        {!useEditor && (
          <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="What this assignment asks for">
            {a.submission_types.map((t) => (
              <li key={t} className={handedIn[t] ? "font-semibold text-green-800" : "text-gray-600"}>
                <span aria-hidden="true">{handedIn[t] ? "✓" : "○"}</span> {SHORT_LABEL[t]}
                <span className="sr-only">{handedIn[t] ? " (handed in)" : " (not handed in)"}</span>
              </li>
            ))}
          </ul>
        )}
        {sub && <p className={graded ? "text-base font-semibold text-brand-700" : "text-gray-700"}>{marksText}</p>}
      </div>

      <div className={`mt-4 grid gap-5 md:grid-cols-[minmax(0,1fr)_18rem] ${details}`}>
        {/* Information: what the assignment asks and what it accepts. */}
        <div className="min-w-0">
          {/* A code challenge is done on its own page: its description and its questions are shown there, after the
              student presses Do assignment, and not on the card. */}
          {a.description && !useEditor && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700">Description</h4>
              <RichText text={a.description} className="mt-1 text-sm text-gray-800" />
            </div>
          )}

          {useEditor && a.status === "open" && (
            <div data-testid="questions-hidden-note">
              {manyTasks && <p className="text-sm font-semibold">{taskCount} tasks</p>}
              {a.has_task_password && !a.tasks_unlocked && (
                <p className="text-xs text-gray-600" data-testid="password-note">
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
                <p className="text-xs text-gray-600" data-testid="order-note">
                  The tasks are done in order: you can start a task only after handing in the one before it.
                </p>
              )}
              <p className="text-xs text-gray-600">
                {manyTasks
                  ? "The questions are shown when you press Do assignment and then Do task, and you hand the tasks in one at a time. Each task is marked as soon as you submit it and cannot be changed afterwards; the mark adds up the test cases you pass in every task."
                  : "The question is shown when you press Do assignment and then Do task. Your code is marked as soon as you submit it, and cannot be changed afterwards."}
              </p>
            </div>
          )}

          <div
            className={`${a.description || (useEditor && a.status === "open") ? "mt-4" : ""} ${
              a.submission_types.includes("code") && a.code_languages?.length > 0 ? "" : "max-md:hidden"
            }`}
          >
            {/* On a phone the ✓ / ○ row in the summary already says this. */}
            <div className="max-md:hidden">
              <h4 className="text-sm font-semibold text-gray-700">Accepted formats</h4>
              <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label="Accepted formats">
                {a.submission_types.map((t) => (
                  <li key={t} className="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs font-semibold text-gray-700">
                    {TYPE_LABEL[t]}
                  </li>
                ))}
              </ul>
            </div>
            {a.submission_types.includes("code") && a.code_languages?.length > 0 && (
              <p className="mt-1.5 text-xs text-gray-600">Language: {languageNames(a.code_languages)}</p>
            )}
          </div>
        </div>

        {/* Dates and the submission, together at the side where the eye looks for them. */}
        <aside className="self-start rounded-lg border border-[var(--color-surface-border)] bg-gray-50 p-4 text-sm" aria-label="Dates and your submission">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-600">Key dates</h4>
            <dl className="mt-2 space-y-2">
              <div className="max-md:hidden">
                <dt className="text-xs text-gray-600">Submission deadline</dt>
                <dd className="flex flex-wrap items-center gap-2">
                  <span className={`font-semibold ${a.status === "open" ? "text-gray-900" : "text-gray-700"}`}>
                    {formatDateTime(a.deadline)}
                  </span>
                  {due && (
                    <Badge tone={due.urgent ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-800"}>
                      <span data-testid="due-badge" title={`Deadline: ${formatDateTime(a.deadline)}`}>
                        {due.text}
                      </span>
                    </Badge>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-600">Available from</dt>
                <dd>{formatDateTime(a.available_from)}</dd>
              </div>
            </dl>
          </div>

          <div className={`mt-3 border-t border-gray-200 pt-3 ${sub ? "" : "max-md:hidden"}`}>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-600">Your submission</h4>
            <dl className="mt-2 space-y-2">
              {/* The status itself is the badge at the top; here are its details. */}
              {!sub && (
                <div>
                  <dt className="sr-only">Status</dt>
                  <dd className="text-gray-700">Nothing handed in yet.</dd>
                </div>
              )}
              {sub && manyTasks && (
                <div>
                  <dt className="text-xs text-gray-600">Tasks</dt>
                  <dd className="font-semibold">{submissionStatus}</dd>
                </div>
              )}
              {sub && !manyTasks && (
                <div>
                  <dt className="text-xs text-gray-600">Handed in</dt>
                  <dd>{formatDateTime(sub.submitted_at)}</dd>
                  {files && (
                    <dd className="mt-1 flex flex-wrap gap-1 max-md:hidden" aria-label="Files you handed in">
                      {files.split(", ").map((f) => (
                        <span key={f} className="rounded bg-white px-1.5 py-0.5 text-xs capitalize text-gray-700 ring-1 ring-gray-200">
                          {f}
                        </span>
                      ))}
                    </dd>
                  )}
                </div>
              )}
              {sub && (
                <div className="max-md:hidden">
                  <dt className="text-xs text-gray-600">Marks</dt>
                  <dd data-testid="marks" className={graded ? "text-base font-semibold text-brand-700" : "text-gray-700"}>
                    {marksText}
                  </dd>
                </div>
              )}
            </dl>
          </div>
        </aside>
      </div>

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


      {sub && hasFeedback && (
        <div
          className={`mt-4 rounded-md border border-gray-200 border-l-4 border-l-green-700 bg-gray-50 p-4 ${details}`}
          data-testid="my-feedback"
        >
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
        <div
          className={`mt-5 flex flex-wrap gap-2 border-t border-gray-200 pt-4 max-md:flex-col max-md:empty:hidden ${
            hasMainAction ? "" : details
          }`}
        >
          {codeLink}
          {a.status === "open" && !sub && !useEditor && (
            <button
              type="button"
              onClick={() => setOpenForm({ id: a.id, mode: "submit" })}
              className="btn-primary min-h-11 rounded-md px-4 py-2 text-sm font-semibold md:min-h-0"
            >
              Submit assignment
            </button>
          )}
          {a.status === "open" && sub?.can_edit && (
            <button
              type="button"
              onClick={() => setOpenForm({ id: a.id, mode: "edit" })}
              className={`btn-secondary min-h-11 rounded-md px-4 py-2 text-sm font-semibold md:min-h-0 ${details}`}
            >
              Edit submission
            </button>
          )}
          {a.status === "open" && sub?.can_delete && (
            <button
              type="button"
              onClick={() => askDelete(a)}
              // On a phone it sits right under Edit: a quiet link, so it isn't tapped by a slip of the thumb.
              className={`btn-danger min-h-11 rounded-md px-4 py-2 text-sm font-semibold md:min-h-0 max-md:border-transparent max-md:bg-transparent max-md:text-red-700 ${details}`}
            >
              Delete submission
            </button>
          )}
        </div>
      )}
      {a.status === "closed" && !sub && (
        <p className="mt-4 border-t border-gray-200 pt-3 text-sm text-gray-600">
          The deadline has passed, and nothing was handed in for this assignment.
        </p>
      )}

      {a.status === "open" && sub && sub.status !== "graded" && !formMode && (
        <div className={details}>
          <SelfCheckPanel assignment={a} submission={sub} />
        </div>
      )}

      <button
        type="button"
        onClick={toggleDetails}
        aria-expanded={expanded}
        className="mt-3 flex min-h-11 w-full items-center justify-between border-t border-gray-200 pt-3 text-left text-sm font-semibold text-blue-700 md:hidden"
        data-testid="card-details-toggle"
      >
        {expanded ? "Hide details" : hasFeedback ? "View feedback and details" : "View details"}
        <span aria-hidden="true">{expanded ? "▴" : "▾"}</span>
      </button>

      {formMode && <UploadForm assignment={a} mode={formMode} onCancel={closeForm} onDone={finishForm} />}
      {notice && <Message state={notice} />}
    </li>
  );
}
