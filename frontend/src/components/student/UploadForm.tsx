"use client";

import { FormEvent, useRef, useState } from "react";
import { apiUpload, StudentAssignment, Submission, SubmissionType, UploadCancelled } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import SubmissionFiles from "@/components/SubmissionFiles";
import { TYPE_LABEL } from "@/components/student/labels";
import { CODE_LANGUAGES, languageNames, languagesFor } from "@/lib/codeLanguages";

// The browser's own file button is reset by the base styles, so it is given the look of an input here.
const fileInput =
  "mt-1 mb-3 block w-full cursor-pointer rounded-md border border-gray-300 bg-white text-sm text-gray-700 file:mr-3 file:cursor-pointer file:border-0 file:border-r file:border-solid file:border-gray-300 file:bg-gray-100 file:px-4 file:py-2.5 file:text-sm file:font-semibold file:text-blue-700 hover:border-gray-400 hover:file:bg-gray-200";
// Every supported code extension (app/code_languages.py refuses anything else).
const CODE_EXTENSIONS = [".zip", ...new Set(CODE_LANGUAGES.flatMap((l) => l.extensions))];
const REPORT_ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const VIDEO_ACCEPT = ".mp4,.mov,.avi,.mkv,.webm,.m4v,video/*";
// Shown under each upload field. These must match the backend limits in app/main.py.
const UPLOAD_HINTS = {
  code: "A single source file or a .zip. Max 50 MB; a .zip may unpack to at most 200 MB.",
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
  // While uploading: the share sent so far (0..1), and how to stop it.
  const [progress, setProgress] = useState<number | null>(null);
  const upload = useRef<AbortController | null>(null);
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
          text: `"${codeFile.name}" can't be checked: ${ext || "files without an extension"} is not a supported language. Upload a .zip or one file in one of: ${languageNames(assignment.code_languages)}.`,
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
    setProgress(0);
    upload.current = new AbortController();
    try {
      if (mode === "submit") {
        formData.append("subject_id", String(assignment.subject_id));
        formData.append("assignment_id", String(assignment.id));
        const submission = await apiUpload<Submission>("/submissions", "POST", formData, setProgress, upload.current.signal);
        await onDone(`Submitted! Your submission id is ${submission.id}.`);
      } else {
        const path = `/submissions/${assignment.my_submission!.id}`;
        await apiUpload(path, "PUT", formData, setProgress, upload.current.signal);
        await onDone("Submission updated.");
      }
    } catch (err) {
      setMessage(
        err instanceof UploadCancelled
          ? { text: "Upload cancelled. Nothing was changed: choose your files again when you are ready.", kind: "info" }
          : { text: `Submission failed: ${err instanceof Error ? err.message : err}`, kind: "error" },
      );
    } finally {
      setSubmitting(false);
      setProgress(null);
      upload.current = null;
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
          {/* Only when the instructor requires a language. Otherwise a file in the wrong language gets an error naming the accepted ones. */}
          {restricted && (
            <div id={id("code-help")} className="mt-1 rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-700">
              <p className="font-semibold">Required language for this assignment</p>
              <ul className="mt-1 grid gap-x-4 gap-y-0.5 sm:grid-cols-3">
                {languages.map((l) => (
                  <li key={l.name}>
                    {l.name} <span className="text-gray-500">({l.extensions.join(", ")})</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-gray-600">
                Your instructor requires this language. Code in any other language is refused, including inside a .zip;
                other files (README, data) are fine.
              </p>
            </div>
          )}
          <input
            id={id("code")}
            type="file"
            ref={codeRef}
            accept={allowedExtensions.join(",")}
            aria-describedby={restricted ? id("code-help") : undefined}
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
          className="btn-primary rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-60"
        >
          {submitting ? "Submitting..." : mode === "submit" ? "Submit assignment" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={() => (submitting ? upload.current?.abort() : onCancel())}
          // Once every byte is sent the server is saving: stopping then could not undo it.
          disabled={progress !== null && progress >= 1}
          className="btn-secondary rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-60"
        >
          {submitting ? "Cancel upload" : "Cancel"}
        </button>
      </div>
      {progress !== null && (
        <div className="mt-3" data-testid="upload-progress">
          <div className="flex justify-between text-xs text-gray-600">
            <span>{progress < 1 ? "Uploading your files..." : "Upload complete: checking your files..."}</span>
            <span>{Math.round(progress * 100)}%</span>
          </div>
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
            className="mt-1 h-2 overflow-hidden rounded bg-gray-200"
          >
            <div className="h-full bg-blue-600 transition-[width]" style={{ width: `${progress * 100}%` }} />
          </div>
        </div>
      )}
      <Message state={message} />
    </form>
  );
}
