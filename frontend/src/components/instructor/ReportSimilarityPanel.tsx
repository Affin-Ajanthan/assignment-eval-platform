"use client";

import { Fragment, useEffect, useState } from "react";
import { apiFetch, ReportSimilarityPair, ReportSimilarityResult } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import DownloadExcelButton from "@/components/instructor/DownloadExcelButton";

const pct = (x: number) => `${(x * 100).toFixed(0)}%`;

/**
 * Report (PDF) similarity for one assignment, shown inside the Similarity
 * check card: identical passages (Winnowing over words) plus similar meaning
 * (all-MiniLM-L6-v2). Review signal only -- the backend stores nothing and
 * grading never sees it.
 */
export default function ReportSimilarityPanel({
  subjectId,
  assignmentName,
}: {
  subjectId: number | null;
  assignmentName: string;
}) {
  const [result, setResult] = useState<ReportSimilarityResult | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [running, setRunning] = useState(false);
  const [openPair, setOpenPair] = useState<string | null>(null);

  // A result belongs to one assignment: clear it when the selection changes.
  useEffect(() => {
    setResult(null);
    setMsg(null);
    setOpenPair(null);
  }, [subjectId, assignmentName]);

  async function run() {
    if (subjectId === null || !assignmentName) {
      setMsg({ text: "Pick a subject and an assignment first.", kind: "error" });
      return;
    }
    setMsg(null);
    setResult(null);
    setRunning(true);
    try {
      const res = await apiFetch<ReportSimilarityResult>(
        `/subjects/${subjectId}/assignments/${encodeURIComponent(assignmentName)}/check-report-similarity`,
        { method: "POST" }
      );
      setResult(res);
      const flagged = res.pairs.filter((p) => p.flag_level).length;
      setMsg({
        text: flagged
          ? `Compared ${res.compared} reports -- ${flagged} pair(s) worth a closer look.`
          : `Compared ${res.compared} reports -- no pairs flagged.`,
        kind: flagged ? "error" : "success",
      });
    } catch (err) {
      setMsg({ text: `Report similarity check failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setRunning(false);
    }
  }

  const key = (p: ReportSimilarityPair) => `${p.submission_a_id}-${p.submission_b_id}`;
  const pairs = result
    ? [...result.pairs].sort(
        (a, b) =>
          Number(!!b.flag_level) - Number(!!a.flag_level) ||
          Math.max(b.coverage_a, b.coverage_b) - Math.max(a.coverage_a, a.coverage_b) ||
          (b.semantic_similarity ?? 0) - (a.semantic_similarity ?? 0)
      )
    : [];

  return (
    <div className="mt-6 border-t border-gray-200 pt-4">
      <h3 className="font-bold">Report similarity (PDF)</h3>
      <p className="mt-1 text-sm text-gray-600">
        Compares the PDF reports of the selected assignment: identical passages and similar meaning. Page numbers,
        running headers/footers and text that appears in most reports (such as the assignment brief) are ignored.
        Upload the assignment&apos;s question paper or report template as a &ldquo;Report template (PDF)&rdquo; on
        the assignment, and its text is cut out of every report before comparing.
      </p>
      <button
        type="button"
        onClick={run}
        disabled={running}
        className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {running ? "Comparing reports..." : "Check report similarity"}
      </button>
      <Message state={msg} />
      {result && (
        <div className="mt-3">
          <DownloadExcelButton
            path="/exports/report-similarity.xlsx"
            result={result}
            filePrefix="report-similarity"
            assignmentName={result.assignment_name}
          />
        </div>
      )}

      {result && result.semantic.status !== "ok" && result.semantic.warning && (
        <div className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800">⚠ {result.semantic.warning}</div>
      )}

      {result && result.skipped.length > 0 && (
        <details className="mt-3 text-sm text-gray-700">
          <summary className="cursor-pointer">{result.skipped.length} report(s) not compared</summary>
          <ul className="mt-1 list-disc pl-5">
            {result.skipped.map((s) => (
              <li key={s.submission_id}>
                {s.student}: {s.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {result && pairs.length > 0 && (
        <>
          <dl className="mt-4 grid gap-x-4 gap-y-1 text-xs text-gray-600 sm:grid-cols-[max-content_1fr]">
            <dt className="font-semibold">Identical text</dt>
            <dd>Share of each report (A / B) found word-for-word in the other, in passages of 10+ words.</dd>
            <dt className="font-semibold">Semantic</dt>
            <dd>
              all-MiniLM-L6-v2: how close the meaning is, section by section. Reports on the same assignment naturally
              score fairly high; a pair is only flagged when it stands out from the rest of the class.
            </dd>
          </dl>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="border border-gray-200 px-3 py-1.5">Student A</th>
                  <th className="border border-gray-200 px-3 py-1.5">Student B</th>
                  <th className="border border-gray-200 px-3 py-1.5">Identical text (A / B)</th>
                  <th className="border border-gray-200 px-3 py-1.5">Semantic</th>
                  <th className="border border-gray-200 px-3 py-1.5">Flag</th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((p) => (
                  <Fragment key={key(p)}>
                    <tr
                      className={
                        p.flag_level === "high" ? "bg-red-50" : p.flag_level === "review" ? "bg-yellow-50" : undefined
                      }
                    >
                      <td className="border border-gray-200 px-3 py-1.5">{p.student_a}</td>
                      <td className="border border-gray-200 px-3 py-1.5">{p.student_b}</td>
                      <td className="border border-gray-200 px-3 py-1.5">
                        {pct(p.coverage_a)} / {pct(p.coverage_b)}
                        {p.passages.length > 0 && (
                          <button
                            type="button"
                            onClick={() => setOpenPair(openPair === key(p) ? null : key(p))}
                            className="ml-2 text-xs font-semibold text-blue-700 hover:underline"
                          >
                            {openPair === key(p) ? "Hide passages" : `Show ${p.passages.length} passage(s)`}
                          </button>
                        )}
                      </td>
                      <td className="border border-gray-200 px-3 py-1.5">
                        {p.semantic_similarity === null ? (
                          <span className="text-gray-400" title="Semantic comparison not available">
                            —
                          </span>
                        ) : (
                          pct(p.semantic_similarity)
                        )}
                      </td>
                      <td className="border border-gray-200 px-3 py-1.5">
                        {p.flag_level === "high" && <span className="font-semibold text-red-700">⚑ Review</span>}
                        {p.flag_level === "review" && (
                          <span className="font-semibold text-yellow-800">⚑ Review (meaning)</span>
                        )}
                        {p.flag_reason && <div className="text-xs text-gray-600">{p.flag_reason}</div>}
                      </td>
                    </tr>
                    {openPair === key(p) && (
                      <tr>
                        <td colSpan={5} className="border border-gray-200 bg-gray-50 px-3 py-2">
                          {p.passages.map((x, i) => (
                            <div key={i} className="mb-3 last:mb-0">
                              <div className="text-xs font-semibold text-gray-700">
                                Passage {i + 1} · {x.words} identical words
                              </div>
                              <div className="mt-1 grid gap-2 text-xs sm:grid-cols-2">
                                <blockquote className="rounded border border-gray-200 bg-white p-2">
                                  <div className="mb-1 font-semibold">{p.student_a}</div>
                                  {x.text_a}
                                </blockquote>
                                <blockquote className="rounded border border-gray-200 bg-white p-2">
                                  <div className="mb-1 font-semibold">{p.student_b}</div>
                                  {x.text_b}
                                </blockquote>
                              </div>
                            </div>
                          ))}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-gray-600">
            Exploratory: these thresholds have not been checked on real reports yet. A flag means &ldquo;compare these
            reports&rdquo;, never an automatic finding of misconduct, and report results never change marks.
          </p>
          <p className="mt-1 text-xs text-gray-500">
            {result.template_filename &&
              `Template "${result.template_filename}" cut out of reports (${Object.values(
                result.template_words_removed
              ).reduce((sum, n) => sum + n, 0)} words in total) · `}
            {result.common_fingerprints_excluded > 0 &&
              `${result.common_fingerprints_excluded} fingerprint(s) shared by most reports ignored · `}
            {result.semantic.status === "ok" && `Semantic model: ${result.semantic.model}`}
            {result.semantic.cohort_median !== null && ` · class median ${pct(result.semantic.cohort_median)}`}
            {result.semantic.review_threshold !== null &&
              ` · review threshold ${pct(result.semantic.review_threshold)}`}
          </p>
        </>
      )}
    </div>
  );
}
