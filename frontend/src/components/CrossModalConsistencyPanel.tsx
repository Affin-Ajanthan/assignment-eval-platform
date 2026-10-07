import { ConsistencyComponent, CrossModalConsistency } from "@/lib/api";

const LABELS: Record<ConsistencyComponent, string> = {
  code: "Code documentation",
  report: "Report",
  transcript: "Video transcript",
};

const ROWS: { label: string; key: "code_report" | "code_transcript" | "report_transcript"; parts: ConsistencyComponent[] }[] = [
  { label: "Code ↔ Report", key: "code_report", parts: ["code", "report"] },
  { label: "Code ↔ Transcript", key: "code_transcript", parts: ["code", "transcript"] },
  { label: "Report ↔ Transcript", key: "report_transcript", parts: ["report", "transcript"] },
];

const STATUS: Record<CrossModalConsistency["status"], { text: string; cls: string }> = {
  consistent: { text: "Consistent", cls: "bg-green-50 text-green-800" },
  review_recommended: { text: "Review recommended", cls: "bg-yellow-50 text-yellow-800" },
  limited_data: { text: "Limited data", cls: "bg-gray-100 text-gray-700" },
  unavailable: { text: "Unavailable", cls: "bg-gray-100 text-gray-700" },
  disabled: { text: "Disabled", cls: "bg-gray-100 text-gray-700" },
};

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

/** Why a comparison has no score: the missing component's own note, or "not evaluated". */
function missingNote(c: CrossModalConsistency, parts: ConsistencyComponent[]): string {
  const notes = parts.map((p) => c.components[p]).filter((x) => x && !x.available).map((x) => x!.note);
  if (notes.length) return notes.join("; ");
  return c.status === "limited_data" ? "Not evaluated" : "Not evaluated (analysis unavailable)";
}

export default function CrossModalConsistencyPanel({ result }: { result: CrossModalConsistency | null }) {
  return (
    <div className="mt-4 rounded-md border border-gray-200 p-4">
      <h4 className="font-bold">Cross-Modal Semantic Consistency</h4>
      <p className="mt-1 text-xs text-gray-600">
        Compares the <em>meaning</em> of the code documentation (comments and docstrings), the report and the video
        transcript with a local sentence-embedding model. Similar wording is not required for a high score.
      </p>

      {!result ? (
        <p className="mt-2 text-sm text-gray-600">Not available for this evaluation — run the auto-evaluation again.</p>
      ) : (
        <>
          {result.warning && (
            <div className="mt-2 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800">⚠ {result.warning}</div>
          )}
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="border border-gray-200 px-3 py-1.5">Comparison</th>
                  <th className="border border-gray-200 px-3 py-1.5 text-right">Similarity</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => {
                  const value = result[row.key];
                  return (
                    <tr key={row.key}>
                      <td className="border border-gray-200 px-3 py-1.5">{row.label}</td>
                      <td className="border border-gray-200 px-3 py-1.5 text-right">
                        {value === null ? (
                          <>
                            <span className="text-gray-400">—</span>
                            <div className="text-xs text-gray-500">{missingNote(result, row.parts)}</div>
                          </>
                        ) : (
                          pct(value)
                        )}
                      </td>
                    </tr>
                  );
                })}
                <tr className="font-semibold">
                  <td className="border border-gray-200 px-3 py-1.5">Overall</td>
                  <td className="border border-gray-200 px-3 py-1.5 text-right">
                    {result.overall === null ? <span className="text-gray-400">—</span> : pct(result.overall)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {result.report_extraction && (
            <p className="mt-2 text-xs text-gray-600">
              {result.report_extraction.status === "ok"
                ? `Report text was extracted automatically from the uploaded document (${result.report_extraction.words} words).`
                : `Report text could not be extracted automatically from the uploaded document (${result.report_extraction.status}${
                    result.report_extraction.error ? `: ${result.report_extraction.error}` : ""
                  }), so comparisons involving the report were not evaluated.`}
            </p>
          )}

          <p className="mt-3 text-sm">
            <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS[result.status].cls}`}>
              {STATUS[result.status].text}
            </span>{" "}
            {result.reason}
          </p>

          {(Object.keys(LABELS) as ConsistencyComponent[]).some((k) => result.components[k]?.available === false) && (
            <ul className="mt-2 ml-5 list-disc text-xs text-gray-600">
              {(Object.keys(LABELS) as ConsistencyComponent[])
                .filter((k) => result.components[k]?.available === false)
                .map((k) => (
                  <li key={k}>
                    {LABELS[k]}: {result.components[k]!.note}
                  </li>
                ))}
            </ul>
          )}

          <p className="mt-3 text-xs text-gray-500">
            <strong>—</strong> = unavailable / not evaluated · <strong>0%</strong> = evaluated, very low similarity ·
            other percentages are semantic similarity scores, not accuracy. Scores under{" "}
            {pct(result.threshold)} overall are marked for review (prototype threshold, not yet validated on real
            submissions). Semantic similarity is a review signal and does not by itself indicate misconduct; it does
            not affect marks.
          </p>
        </>
      )}
    </div>
  );
}
