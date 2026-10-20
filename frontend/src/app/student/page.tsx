"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, StudentAssignment, Submission, SubmissionType } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { formatDateTime, formatMark } from "@/lib/datetime";
import AccountBar from "@/components/AccountBar";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import SubmissionFiles from "@/components/SubmissionFiles";

const fileInput = "mt-1 mb-3 block w-full text-sm";
// Languages the code checks read. Must match _ANALYZED_EXTENSIONS in the backend
// (app/main.py), which refuses any other code file at upload.
const CODE_LANGUAGES: { name: string; extensions: string[] }[] = [
  { name: "Python", extensions: [".py", ".ipynb"] },
  { name: "Java", extensions: [".java"] },
  { name: "JavaScript", extensions: [".js"] },
  { name: "C", extensions: [".c", ".h"] },
  { name: "C++", extensions: [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"] },
  { name: "C#", extensions: [".cs"] },
  { name: "Go", extensions: [".go"] },
  { name: "Ruby", extensions: [".rb"] },
  { name: "PHP", extensions: [".php"] },
];
const CODE_EXTENSIONS = [".zip", ...CODE_LANGUAGES.flatMap((l) => l.extensions)];
const CODE_ACCEPT = CODE_EXTENSIONS.join(",");
const REPORT_ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const VIDEO_ACCEPT = ".mp4,.mov,.avi,.mkv,.webm,.m4v,video/*";
// Shown under each upload field. These must match the backend limits in app/main.py.
const UPLOAD_HINTS = {
  code: "A single source file in one of the languages above, or a .zip. Max 50 MB; a .zip may unpack to at most 200 MB.",
  report: "PDF or DOCX. Max 25 MB.",
  video: "MP4, MOV, AVI, MKV, WEBM or M4V. Max 1 GB.",
};

const TYPE_LABEL: Record<SubmissionType, string> = { code: "Code", report: "Report", video: "Presentation video" };

/** Only the upload fields this assignment accepts, for a new submission or an edit. */
function UploadForm({
  assignment,
  mode,
  onDone,
  onCancel,
}: {
  assignment: StudentAssignment;
  mode: "submit" | "edit";
  onDone: (text: string) => Promise<void>;
  onCancel: () => void;
}) {
  const codeRef = useRef<HTMLInputElement>(null);
  const reportRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState<MessageState>(null);
  const [submitting, setSubmitting] = useState(false);
  const id = (field: string) => `${field}-${assignment.id}`;
  const accepts = (kind: SubmissionType) => assignment.submission_types.includes(kind);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    const formData = new FormData();
    const codeFile = codeRef.current?.files?.[0];
    if (codeFile) {
      const ext = codeFile.name.includes(".") ? codeFile.name.slice(codeFile.name.lastIndexOf(".")).toLowerCase() : "";
      if (!CODE_EXTENSIONS.includes(ext)) {
        setMessage({
          text: `"${codeFile.name}" can't be checked: ${ext || "files without an extension"} is not a supported language. Upload a .zip or one file in a language listed under the Code field.`,
          kind: "error",
        });
        return;
      }
      formData.append("code", codeFile);
    }
    if (reportRef.current?.files?.[0]) formData.append("report", reportRef.current.files[0]);
    if (videoRef.current?.files?.[0]) formData.append("video", videoRef.current.files[0]);
    if (![...formData.keys()].length) {
      setMessage({ text: mode === "submit" ? "Choose at least one file to submit." : "Choose a file to replace.", kind: "error" });
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "submit") {
        formData.append("subject_id", String(assignment.subject_id));
        formData.append("assignment_id", String(assignment.id));
        const submission = await apiFetch<Submission>("/submissions", { method: "POST", body: formData });
        await onDone(`Submitted! Your submission id is ${submission.id}.`);
      } else {
        await apiFetch(`/submissions/${assignment.my_submission!.id}`, { method: "PUT", body: formData });
        await onDone("Submission updated.");
      }
    } catch (err) {
      setMessage({ text: `Submission failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 rounded-md border border-gray-200 p-4">
      <p className="mb-3 text-sm text-gray-600">
        Accepted for this assignment: {assignment.submission_types.map((t) => TYPE_LABEL[t]).join(", ")}.
      </p>
      {mode === "edit" && assignment.my_submission && (
        <div className="mb-4">
          <p className="mb-2 text-sm font-semibold">Currently submitted files</p>
          <SubmissionFiles submissionId={assignment.my_submission.id} />
          <p className="mt-3 text-sm text-gray-600">Choose only the files you want to replace; the others are kept.</p>
        </div>
      )}
      {accepts("code") && (
        <>
          <label className="block text-sm font-semibold" htmlFor={id("code")}>
            Code (zip or single file)
          </label>
          <div id={id("code-help")} className="mt-1 rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-700">
            <p className="font-semibold">Accepted languages</p>
            <ul className="mt-1 grid gap-x-4 gap-y-0.5 sm:grid-cols-3">
              {CODE_LANGUAGES.map((l) => (
                <li key={l.name}>
                  {l.name} <span className="text-gray-500">({l.extensions.join(", ")})</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-gray-600">
              A .zip may also contain other files (README, data), but it must include code in one of these
              languages. Other languages, such as TypeScript, Kotlin, Swift or Rust, are not accepted yet.
            </p>
          </div>
          <input
            id={id("code")}
            type="file"
            ref={codeRef}
            accept={CODE_ACCEPT}
            aria-describedby={id("code-help")}
            className={fileInput}
          />
          <p className="mb-3 text-xs text-gray-500">{UPLOAD_HINTS.code}</p>
        </>
      )}

      {accepts("report") && (
        <>
          <label className="block text-sm font-semibold" htmlFor={id("report")}>
            Report (PDF or DOCX)
          </label>
          <input id={id("report")} type="file" ref={reportRef} accept={REPORT_ACCEPT} className={fileInput} />
          <p className="mb-3 text-xs text-gray-500">{UPLOAD_HINTS.report}</p>
        </>
      )}

      {accepts("video") && (
        <>
          <label className="block text-sm font-semibold" htmlFor={id("video")}>
            Presentation video
          </label>
          <input id={id("video")} type="file" ref={videoRef} accept={VIDEO_ACCEPT} className={fileInput} />
          <p className="mb-3 text-xs text-gray-500">{UPLOAD_HINTS.video}</p>
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {submitting ? "Submitting..." : mode === "submit" ? "Submit assignment" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
        >
          Cancel
        </button>
      </div>
      <Message state={message} />
    </form>
  );
}

function AssignmentCard({
  a,
  openForm,
  setOpenForm,
  onChanged,
  askDelete,
  notice,
}: {
  a: StudentAssignment;
  openForm: { id: number; mode: "submit" | "edit" } | null;
  setOpenForm: (v: { id: number; mode: "submit" | "edit" } | null) => void;
  onChanged: (assignmentId: number, text: string) => Promise<void>;
  askDelete: (a: StudentAssignment) => void;
  notice: MessageState;
}) {
  const sub = a.my_submission;
  const submissionStatus = !sub ? "Not submitted" : sub.status === "graded" ? "Graded" : "Submitted";
  const files = sub
    ? [sub.has_code && "code", sub.has_report && "report", sub.has_video && "video"].filter(Boolean).join(", ")
    : "";
  const formMode = openForm?.id === a.id ? openForm.mode : null;

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm" data-testid="student-assignment">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-bold">{a.name}</h3>
          <p className="text-xs text-gray-500">{a.subject_name}</p>
          <p className="text-xs text-gray-500">Accepts: {a.submission_types.map((t) => TYPE_LABEL[t]).join(", ")}</p>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold ${
            a.status === "open" ? "bg-green-50 text-green-800" : "bg-gray-100 text-gray-700"
          }`}
        >
          {a.status === "open" ? "Open" : "Closed"}
        </span>
      </div>

      {a.description && (
        <div className="mt-3">
          <p className="text-sm font-semibold">Description</p>
          <p className="whitespace-pre-wrap text-sm text-gray-700">{a.description}</p>
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
          {sub && ` (${formatDateTime(sub.submitted_at)}${files ? ` — ${files}` : ""})`}
        </dd>
        {sub && (
          <>
            <dt className="font-semibold">Marks</dt>
            <dd data-testid="marks">{formatMark(sub.final_mark, sub.max_mark)}</dd>
          </>
        )}
      </dl>

      {a.status === "open" && !formMode && (
        <div className="mt-4 flex flex-wrap gap-2">
          {!sub && (
            <button
              type="button"
              onClick={() => setOpenForm({ id: a.id, mode: "submit" })}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Submit assignment
            </button>
          )}
          {sub?.can_edit && (
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

      {formMode && (
        <UploadForm
          assignment={a}
          mode={formMode}
          onCancel={() => setOpenForm(null)}
          onDone={async (text) => {
            setOpenForm(null);
            await onChanged(a.id, text);
          }}
        />
      )}
      {notice && <Message state={notice} />}
    </li>
  );
}

export default function StudentPage() {
  const { user, ready } = useRequireRole("student");

  const [assignments, setAssignments] = useState<StudentAssignment[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [openForm, setOpenForm] = useState<{ id: number; mode: "submit" | "edit" } | null>(null);
  const [notice, setNotice] = useState<{ assignmentId: number; state: MessageState } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const load = useCallback(async () => {
    const [a, s] = await Promise.all([
      apiFetch<StudentAssignment[]>("/assignments"),
      apiFetch<Submission[]>("/submissions"),
    ]);
    setAssignments(a);
    setSubmissions(s);
  }, []);

  useEffect(() => {
    if (!ready || !user) return;
    load();
  }, [ready, user, load]);

  async function changed(assignmentId: number, text: string) {
    setNotice({ assignmentId, state: { text, kind: "success" } });
    await load();
  }

  function askDelete(a: StudentAssignment) {
    setConfirm({
      title: "Delete your submission?",
      message: `Are you sure you want to delete your submission for "${a.name}"? Your uploaded files will be removed. You can submit again before the deadline (${formatDateTime(a.deadline)}).`,
      onConfirm: async () => {
        setConfirmBusy(true);
        try {
          await apiFetch(`/submissions/${a.my_submission!.id}`, { method: "DELETE" });
          await changed(a.id, "Submission deleted.");
        } catch (err) {
          setNotice({ assignmentId: a.id, state: { text: `Could not delete: ${err instanceof Error ? err.message : err}`, kind: "error" } });
        } finally {
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  if (!ready || !user) return null;

  const open = assignments.filter((a) => a.status === "open");
  const past = assignments.filter((a) => a.status === "closed");
  const card = (a: StudentAssignment) => (
    <AssignmentCard
      key={a.id}
      a={a}
      openForm={openForm}
      setOpenForm={setOpenForm}
      onChanged={changed}
      askDelete={askDelete}
      notice={notice?.assignmentId === a.id ? notice.state : null}
    />
  );

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Student portal</h1>
      <p className="mt-1 text-sm text-gray-600">
        Open an assignment, upload your code, report and presentation video, and submit before the deadline. You can
        edit or delete your submission until the deadline or until it has been graded.
      </p>

      {user.subjects.length === 0 && (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">No subjects assigned yet -- ask your admin</p>
      )}

      <section className="mt-6">
        <h2 className="text-lg font-bold">Available assignments</h2>
        {open.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">There are no assignments open for submission right now.</p>
        ) : (
          <ul className="mt-3 space-y-4">{open.map(card)}</ul>
        )}
      </section>

      {past.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-bold">Past assignments</h2>
          <ul className="mt-3 space-y-4">{past.map(card)}</ul>
        </section>
      )}

      <section className="mt-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold">My submissions</h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left">
                <th className="border border-gray-200 px-3 py-1.5">Subject</th>
                <th className="border border-gray-200 px-3 py-1.5">Assignment</th>
                <th className="border border-gray-200 px-3 py-1.5">Submitted</th>
                <th className="border border-gray-200 px-3 py-1.5">Status</th>
                <th className="border border-gray-200 px-3 py-1.5">Marks</th>
              </tr>
            </thead>
            <tbody>
              {submissions.map((s) => (
                <tr key={s.id}>
                  <td className="border border-gray-200 px-3 py-1.5">{s.subject_name}</td>
                  <td className="border border-gray-200 px-3 py-1.5">{s.assignment_name}</td>
                  <td className="border border-gray-200 px-3 py-1.5">{formatDateTime(s.submitted_at)}</td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        s.status === "graded" ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"
                      }`}
                    >
                      {s.status === "graded" ? "Graded" : "Submitted"}
                    </span>
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">{formatMark(s.final_mark, s.max_mark)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </div>
  );
}
