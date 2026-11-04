"use client";

import { useEffect, useState } from "react";
import { apiFetch, CodeCompareFile, CodeCompareResult, CodeCompareSide } from "@/lib/api";
import Message from "@/components/Message";

// Lines of context kept around each marked stretch when only the matching parts are shown.
const CONTEXT = 2;

/** The line numbers to show: all of them, or the marked ones with CONTEXT lines around each stretch (null: a gap). */
function shownLines(file: CodeCompareFile, onlyMatches: boolean): (number | null)[] {
  const count = file.source === "" ? 0 : file.source.split("\n").length;
  if (!onlyMatches) return Array.from({ length: count }, (_, i) => i + 1);
  const keep = new Set<number>();
  for (const r of file.ranges) {
    for (let n = Math.max(1, r.start - CONTEXT); n <= Math.min(count, r.end + CONTEXT); n++) keep.add(n);
  }
  const out: (number | null)[] = [];
  let last = 0;
  for (const n of [...keep].sort((x, y) => x - y)) {
    if (n > last + 1) out.push(null);
    out.push(n);
    last = n;
  }
  if (out.length && last < count) out.push(null);
  return out;
}

function FileView({ file, onlyMatches }: { file: CodeCompareFile; onlyMatches: boolean }) {
  const lines = file.source.split("\n");
  const marked = (n: number) => file.ranges.some((r) => n >= r.start && n <= r.end);
  const markedCount = file.ranges.reduce((sum, r) => sum + r.end - r.start + 1, 0);
  const shown = shownLines(file, onlyMatches);
  return (
    <div className="mt-2">
      <p className="text-xs font-semibold text-gray-700">
        {file.name}{" "}
        <span className="font-normal text-gray-500">
          · {markedCount} of {file.line_count} line(s) marked
          {file.truncated && ` · first ${lines.length} lines shown`}
        </span>
      </p>
      {shown.length === 0 ? (
        <p className="mt-1 text-xs text-gray-500">{onlyMatches ? "No shared code in this file." : "Empty file."}</p>
      ) : (
        <pre className="mt-1 max-h-[32rem] overflow-auto rounded border border-gray-200 bg-gray-50 py-1 text-xs leading-5">
          {shown.map((n, i) =>
            n === null ? (
              <div key={`gap-${i}`} className="px-2 text-gray-400">
                ⋯
              </div>
            ) : (
              <div key={n} className={`flex ${marked(n) ? "bg-red-100" : ""}`}>
                <span className="w-10 shrink-0 select-none pr-2 text-right text-gray-600">{n}</span>
                <code className="whitespace-pre pr-2">{lines[n - 1] || " "}</code>
              </div>
            ),
          )}
        </pre>
      )}
    </div>
  );
}

function SideView({ side, label, onlyMatches }: { side: CodeCompareSide; label: string; onlyMatches: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-sm font-semibold">{label}</p>
      {side.files.length === 0 && <p className="mt-1 text-xs text-gray-500">No code files.</p>}
      {side.files.map((f) => (
        <FileView key={f.name} file={f} onlyMatches={onlyMatches} />
      ))}
    </div>
  );
}

/** Two submissions' code side by side, with the lines that carry code found in both marked. Loads when opened. */
export default function CodeCompareView({
  subjectId,
  assignmentName,
  aId,
  bId,
  labelA,
  labelB,
}: {
  subjectId: number;
  assignmentName: string;
  aId: number;
  bId: number;
  labelA: string;
  labelB: string;
}) {
  const [result, setResult] = useState<CodeCompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onlyMatches, setOnlyMatches] = useState(true);

  useEffect(() => {
    let current = true;
    setResult(null);
    setError(null);
    apiFetch<CodeCompareResult>(
      `/subjects/${subjectId}/assignments/${encodeURIComponent(assignmentName)}/code-compare?a=${aId}&b=${bId}`,
    )
      .then((r) => current && setResult(r))
      .catch((err) => current && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      current = false;
    };
  }, [subjectId, assignmentName, aId, bId]);

  if (error) return <Message state={{ text: `Could not compare the code: ${error}`, kind: "error" }} />;
  if (!result) return <p className="text-sm text-gray-500">Loading both submissions...</p>;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-gray-600">
          <span className="rounded bg-red-100 px-1">Marked lines</span> carry code found in both submissions (
          {result.shared_fingerprints} shared fingerprint(s), after normalising names and literals
          {result.common_code_removed > 0 && " and leaving out code most of the class shares"}).
        </p>
        <label className="flex items-center gap-1.5 text-xs font-semibold">
          <input type="checkbox" checked={onlyMatches} onChange={(e) => setOnlyMatches(e.target.checked)} />
          Only the matching parts
        </label>
      </div>
      <div className="mt-2 grid gap-4 lg:grid-cols-2">
        <SideView side={result.a} label={labelA} onlyMatches={onlyMatches} />
        <SideView side={result.b} label={labelB} onlyMatches={onlyMatches} />
      </div>
      <p className="mt-2 text-xs text-gray-500">
        A review aid, not proof: renamed code still matches, and so can short common patterns.
      </p>
    </div>
  );
}
