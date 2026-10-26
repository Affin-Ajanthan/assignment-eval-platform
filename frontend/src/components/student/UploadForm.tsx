"use client";

import { FormEvent, useRef, useState } from "react";
import { apiFetch, StudentAssignment, Submission, SubmissionType } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import SubmissionFiles from "@/components/SubmissionFiles";
import { TYPE_LABEL } from "@/components/student/labels";
import { CODE_LANGUAGES, languageNames, languagesFor } from "@/lib/codeLanguages";

const fileInput = "mt-1 mb-3 block w-full text-sm";
// Every supported code extension (app/code_languages.py refuses anything else).
const CODE_EXTENSIONS = [".zip", ...new Set(CODE_LANGUAGES.flatMap((l) => l.extensions))];
const REPORT_ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const VIDEO_ACCEPT = ".mp4,.mov,.avi,.mkv,.webm,.m4v,video/*";
// Shown under each upload field. These must match the backend limits in app/main.py.
const UPLOAD_HINTS = {
  code: "A single source file in one of the languages above, or a .zip. Max 50 MB; a .zip may unpack to at most 200 MB.",
  report: "PDF or DOCX. Max 25 MB.",
  video: "MP4, MOV, AVI, MKV, WEBM or M4V. Max 1 GB.",
};

/** Only the upload fields this assignment accepts, for a new submission or an edit. */
export default function UploadForm({
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
  // The instructor may require particular languages; otherwise every supported one.
  const restricted = (assignment.code_languages ?? []).length > 0;
  const languages = languagesFor(assignment.code_languages);
  const allowedExtensions = [".zip", ...new Set(languages.flatMap((l) => l.extensions))];

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
      if (!allowedExtensions.includes(ext)) {
        setMessage({
          text: `This assignment must be written in ${languageNames(assignment.code_languages)}. "${codeFile.name}" is in another language.`,
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
            <p className="font-semibold">
              {restricted ? "Required language for this assignment" : "Accepted languages"}
            </p>
            <ul className="mt-1 grid gap-x-4 gap-y-0.5 sm:grid-cols-3">
              {languages.map((l) => (
                <li key={l.name}>
                  {l.name} <span className="text-gray-500">({l.extensions.join(", ")})</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-gray-600">
              {restricted
                ? "Your instructor requires this language. Code in any other language is refused, including inside a .zip; other files (README, data) are fine."
                : "A .zip may also contain other files (README, data), but it must include code in one of these languages. Other languages, such as TypeScript, Kotlin, Swift or Rust, are not accepted yet."}
            </p>
          </div>
          <input
            id={id("code")}
            type="file"
            ref={codeRef}
            accept={allowedExtensions.join(",")}
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
