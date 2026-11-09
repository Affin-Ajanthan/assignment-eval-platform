"use client";

import { useState } from "react";
import { AISignal, AiContentCheckResult, apiFetch } from "@/lib/api";
import { methodLabel } from "@/components/AISignalsPanel";
import Message, { MessageState } from "@/components/Message";

const BADGE: Record<AISignal["signal"], { text: string; cls: string }> = {
  low: { text: "Low", cls: "bg-green-50 text-green-800" },
  medium: { text: "Medium", cls: "bg-yellow-50 text-yellow-800" },
  high: { text: "High", cls: "bg-red-50 text-red-700" },
};

/** One part (report or code) of one submission: the level, the score and, below, why. */
function Part({ signal, missing }: { signal: AISignal | null; missing: string }) {
  if (!signal) return <span className="text-gray-400">{missing}</span>;
  return (
    <div>
      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${BADGE[signal.signal].cls}`}>
        {BADGE[signal.signal].text} · {signal.score}
      </span>
      <div className="mt-1 text-xs text-gray-500">{methodLabel(signal.method)}</div>
      {signal.reasons.length > 0 && (
        <ul className="mt-1 ml-4 list-disc text-xs text-gray-700">
          {signal.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * AI-content check for one assignment: every submission's report and code, most AI-like first. A review signal only
 * (the backend stores nothing and no mark changes).
 */
export default function AiContentSection({ subjectId, assignmentName }: { subjectId: number; assignmentName: string }) {
  const [result, setResult] = useState<AiContentCheckResult | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setMsg(null);
    setResult(null);
    setRunning(true);
    try {
      const res = await apiFetch<AiContentCheckResult>(
        `/subjects/${subjectId}/assignments/${encodeURIComponent(assignmentName)}/check-ai-content`,
        { method: "POST" },
      );
      setResult(res);
      setMsg({
        text: res.flagged
          ? `Checked ${res.checked} submission(s) -- ${res.flagged} with a high AI-content signal; lecturer review recommended.`
          : `Checked ${res.checked} submission(s) -- none with a high signal.`,
        kind: res.flagged ? "warning" : "success",
      });
    } catch (err) {
      setMsg({ text: `AI-content check failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">AI Content Check</h2>
      <p className="mt-1 text-sm text-gray-600">
        Estimates whether each submission&apos;s report and code look machine-generated. These are review signals, not
        proof: they misfire on formal or non-native English writing and on tidy code, and they never change a mark.
      </p>
      <button
        type="button"
        onClick={run}
        disabled={running}
        className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {running ? "Checking..." : "Check AI content"}
      </button>
      <Message state={msg} />
      {result && result.rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left">
                <th className="border border-gray-200 px-3 py-1.5">Student</th>
                <th className="border border-gray-200 px-3 py-1.5">Report</th>
                <th className="border border-gray-200 px-3 py-1.5">Code</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.map((r) => (
                <tr
                  key={r.submission_id}
                  className={r.report?.signal === "high" || r.code?.signal === "high" ? "bg-red-50" : undefined}
                >
                  <td className="border border-gray-200 px-3 py-1.5 align-top">
                    {r.student_name} <span className="text-gray-500">(#{r.submission_id})</span>
                    <br />
                    <small className="text-gray-500">{r.student_email}</small>
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5 align-top">
                    <Part signal={r.report} missing="No readable report" />
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5 align-top">
                    <Part signal={r.code} missing="No code" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
