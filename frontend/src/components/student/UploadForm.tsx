"use client";

import { ChangeEvent, FormEvent, ReactNode, useRef, useState } from "react";
import { apiUpload, StudentAssignment, Submission, SubmissionType, UploadCancelled } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import SubmissionFiles from "@/components/SubmissionFiles";
import { TYPE_LABEL } from "@/components/student/labels";
import { CODE_LANGUAGES, languageNames, languagesFor } from "@/lib/codeLanguages";

// The file chooser: a dashed box with a clear button, so each upload is easy to see.
const fileInput =
  "block w-full cursor-pointer rounded-md border border-dashed border-gray-300 bg-gray-50 p-3 text-sm " +
  "file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-gray-300 file:bg-white file:px-3 " +
  "file:py-1.5 file:text-sm file:font-semibold hover:file:bg-gray-100";
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
const KINDS: SubmissionType[] = ["code", "report", "video"];

/** One upload in its own box: a number and title, whether a file is chosen, then the chooser and its hints. */
function UploadBox({
  number,
  title,
  htmlFor,
  chosen,
  children,
}: {
  number: number;
  title: string;
  htmlFor: string;
  chosen: string | null;
  children: ReactNode;
}) {
  return (
    <section className="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm" data-testid="upload-box">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm font-semibold" htmlFor={htmlFor}>
          <span
            aria-hidden="true"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs text-blue-800"
          >
            {number}
          </span>
          {title}
        </label>
        {chosen ? (
          <span className="max-w-full truncate rounded bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-800">
            ✓ {chosen}
          </span>
        ) : (
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-600">No file chosen</span>
        )}
      </div>
      {children}
    </section>
  );
}

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
  // The name of the file chosen in each box (null: none), for the badge on the box.
  const [chosen, setChosen] = useState<Record<SubmissionType, string | null>>({ code: null, report: null, video: null });
  const pick = (kind: SubmissionType) => (e: ChangeEvent<HTMLInputElement>) =>
    setChosen((c) => ({ ...c, [kind]: e.target.files?.[0]?.name ?? null }));
  // While uploading: the share sent so far (0..1), and how to stop it.
  const [progress, setProgress] = useState<number | null>(null);
  const upload = useRef<AbortController | null>(null);
  const id = (field: string) => `${field}-${assignment.id}`;
  const accepts = (kind: SubmissionType) => assignment.submission_types.includes(kind);
  // The boxes are numbered in order, counting only the ones this assignment accepts.
  const numberOf = (kind: SubmissionType) => KINDS.filter(accepts).indexOf(kind) + 1;
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
      <p className="text-sm text-gray-600">
        Accepted for this assignment: {assignment.submission_types.map((t) => TYPE_LABEL[t]).join(", ")}.
      </p>
      {mode === "edit" && assignment.my_submission && (
        <div className="mt-3">
          <p className="mb-2 text-sm font-semibold">Currently submitted files</p>
          <SubmissionFiles submissionId={assignment.my_submission.id} />
          <p className="mt-3 text-sm text-gray-600">Choose only the files you want to replace; the others are kept.</p>
        </div>
      )}
      {accepts("code") && (
        <UploadBox number={numberOf("code")} title="Code (zip or single file)" htmlFor={id("code")} chosen={chosen.code}>
          <div id={id("code-help")} className="mb-3 rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-700">
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
            onChange={pick("code")}
            className={fileInput}
          />
          <p className="mt-2 text-xs text-gray-500">{UPLOAD_HINTS.code}</p>
        </UploadBox>
      )}

      {accepts("report") && (
        <UploadBox number={numberOf("report")} title="Report (PDF or DOCX)" htmlFor={id("report")} chosen={chosen.report}>
          <input
            id={id("report")}
            type="file"
            ref={reportRef}
            accept={REPORT_ACCEPT}
            onChange={pick("report")}
            className={fileInput}
          />
          <p className="mt-2 text-xs text-gray-500">{UPLOAD_HINTS.report}</p>
        </UploadBox>
      )}

      {accepts("video") && (
        <UploadBox number={numberOf("video")} title="Presentation video" htmlFor={id("video")} chosen={chosen.video}>
          <input
            id={id("video")}
            type="file"
            ref={videoRef}
            accept={VIDEO_ACCEPT}
            onChange={pick("video")}
            className={fileInput}
          />
          <p className="mt-2 text-xs text-gray-500">{UPLOAD_HINTS.video}</p>
        </UploadBox>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
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
