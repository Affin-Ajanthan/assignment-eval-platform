"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiFetchBlob, SubmissionFile, submissionFileUrl } from "@/lib/api";

const KIND_LABEL: Record<SubmissionFile["kind"], string> = {
  code: "Code",
  report: "Report",
  video: "Presentation video",
};
const TEXT_EXTENSIONS = new Set([
  "py", "java", "js", "jsx", "ts", "tsx", "c", "h", "cpp", "hpp", "cc", "cs", "go", "rb", "kt", "swift", "php",
  "rs", "scala", "txt", "md", "json", "csv", "xml", "yml", "yaml", "html", "css", "sql", "sh",
]);
const MAX_PREVIEW_BYTES = 1024 * 1024;

const btn = "rounded-md bg-gray-600 px-2 py-1 text-xs font-semibold text-white hover:bg-gray-700 disabled:opacity-60";

function ext(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Lists a submission's uploaded files with View / Open / Download. The API
 * decides who may see them (the owning student, the subject's instructors). */
export default function SubmissionFiles({ submissionId }: { submissionId: number }) {
  const [files, setFiles] = useState<SubmissionFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ name: string; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<SubmissionFile[]>(`/submissions/${submissionId}/files`)
      .then((f) => !cancelled && setFiles(f))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [submissionId]);

  async function withFile(file: SubmissionFile, action: (blob: Blob) => void | Promise<void>) {
    const key = `${file.kind}/${file.path}`;
    setBusy(key);
    setError(null);
    try {
      await action(await apiFetchBlob(submissionFileUrl(submissionId, file)));
    } catch (err) {
      setError(`Could not load ${file.name}: ${err instanceof Error ? err.message : err}`);
    } finally {
      setBusy(null);
    }
  }

  function download(file: SubmissionFile) {
    withFile(file, (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    });
  }

  function view(file: SubmissionFile) {
    if (ext(file.name) === "pdf") {
      // Open in the browser's PDF viewer.
      withFile(file, (blob) => {
        const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
        window.open(url, "_blank", "noopener");
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      });
    } else {
      // Shown as plain text, never rendered as HTML.
      withFile(file, async (blob) => setPreview({ name: file.path, text: await blob.text() }));
    }
  }

  if (error && !files) return <p className="text-sm text-red-700">Could not load files: {error}</p>;
  if (!files) return <p className="text-sm text-gray-500">Loading files...</p>;
  if (files.length === 0) return <p className="text-sm text-gray-600">No files found for this submission.</p>;

  const kinds = (Object.keys(KIND_LABEL) as SubmissionFile["kind"][]).filter((k) => files.some((f) => f.kind === k));

  return (
    <div className="space-y-3" data-testid="submission-files">
      {kinds.map((kind) => (
        <div key={kind}>
          <p className="text-sm font-semibold">{KIND_LABEL[kind]}</p>
          <ul className="mt-1 space-y-1">
            {files
              .filter((f) => f.kind === kind)
              .map((f) => {
                const key = `${f.kind}/${f.path}`;
                const canView = (TEXT_EXTENSIONS.has(ext(f.name)) || ext(f.name) === "" || ext(f.name) === "pdf") &&
                  f.size <= MAX_PREVIEW_BYTES * (ext(f.name) === "pdf" ? 50 : 1);
                return (
                  <li key={key} className="flex flex-wrap items-center justify-between gap-2 rounded bg-gray-50 px-2 py-1">
                    <span className="break-all text-sm">
                      {f.path} <span className="text-xs text-gray-500">({formatSize(f.size)})</span>
                    </span>
                    <span className="flex gap-1">
                      {canView && (
                        <button type="button" className={btn} disabled={busy === key} onClick={() => view(f)}>
                          {ext(f.name) === "pdf" ? "Open" : "View"}
                        </button>
                      )}
                      <button type="button" className={btn} disabled={busy === key} onClick={() => download(f)}>
                        {busy === key ? "..." : "Download"}
                      </button>
                    </span>
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
      {error && <p className="text-sm text-red-700">{error}</p>}
      {preview && (
        <div className="rounded-md border border-gray-300">
          <div className="flex items-center justify-between bg-gray-100 px-3 py-1.5">
            <span className="break-all text-sm font-semibold">{preview.name}</span>
            <button type="button" className={btn} onClick={() => setPreview(null)}>
              Close
            </button>
          </div>
          <pre className="max-h-96 overflow-auto p-3 text-xs">{preview.text}</pre>
        </div>
      )}
    </div>
  );
}
