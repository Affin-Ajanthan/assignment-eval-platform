"use client";

import { useState } from "react";
import { apiFetchBlob } from "@/lib/api";

/** "Download Excel" for a result already on screen: the result is sent to
 * an /exports/*.xlsx endpoint, which returns the same data as a workbook. */
export default function DownloadExcelButton({
  path,
  result,
  filePrefix,
  assignmentName,
}: {
  path: string;
  result: unknown;
  filePrefix: string;
  assignmentName: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const blob = await apiFetchBlob(path, result);
      const slug = assignmentName.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "assignment";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${filePrefix}_${slug}_${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col">
      <button
        type="button"
        onClick={download}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-md border border-green-700 px-3 py-1.5 text-sm font-semibold text-green-800 hover:bg-green-50 disabled:opacity-60"
      >
        <span aria-hidden="true">⬇</span>
        {busy ? "Preparing Excel..." : "Download Excel"}
      </button>
      {error && <span className="mt-1 text-xs text-red-700">Download failed: {error}</span>}
    </span>
  );
}
