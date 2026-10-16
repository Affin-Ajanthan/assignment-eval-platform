"use client";

import { ChangeEvent, useRef, useState } from "react";
import { apiFetch, Assignment } from "@/lib/api";

/**
 * Template PDF for one assignment (question paper / report template). Its
 * text is cut out of every student report before the report similarity
 * check, so questions pasted into reports don't make them look copied.
 */
export default function ReportTemplateControl({
  assignment,
  onChanged,
}: {
  assignment: Assignment;
  onChanged: () => Promise<void>;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const has = Boolean(assignment.report_template_filename);

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";  // allow choosing the same file again later
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      await apiFetch(`/assignments/${assignment.id}/report-template`, { method: "POST", body });
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/assignments/${assignment.id}/report-template`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <span>
        {has
          ? `${assignment.report_template_filename} (${assignment.report_template_words} words, cut out of student reports before the report similarity check)`
          : "None"}
      </span>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="hidden" onChange={upload} />
        <button
          type="button"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
          className="rounded-md border border-blue-600 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-60"
        >
          {busy ? "Working..." : has ? "Replace PDF" : "Upload PDF"}
        </button>
        {has && (
          <button
            type="button"
            disabled={busy}
            onClick={remove}
            className="rounded-md border border-red-600 px-2.5 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-60"
          >
            Remove
          </button>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-red-700">Template not saved: {error}</p>}
    </div>
  );
}
