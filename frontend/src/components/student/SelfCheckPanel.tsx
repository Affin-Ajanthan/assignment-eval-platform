"use client";

import { MySubmission, StudentAssignment } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import Message from "@/components/Message";
import { AiResult, SimilarityResult } from "@/components/student/SelfCheckResults";
import { CHECKS } from "@/lib/selfCheckBands";
import { useHiddenResults } from "@/lib/useHiddenResults";
import { useSelfCheckStatus } from "@/lib/useSelfCheckStatus";

/** "Check my submission": similarity and AI-content self-checks while the assignment is open. */
export default function SelfCheckPanel({ assignment, submission }: { assignment: StudentAssignment; submission: MySubmission }) {
  const { status, msg, starting, start } = useSelfCheckStatus(submission.id, submission.submitted_at);
  const [hidden, toggleHidden] = useHiddenResults();

  if (!status || !status.can_run || !(status.similarity_enabled || status.ai_enabled)) return null;

  const available = CHECKS.filter((c) =>
    c.kind === "ai_content"
      ? status.ai_enabled && (submission.has_code || submission.has_report)
      : status.similarity_enabled && (c.kind === "code_similarity" ? submission.has_code : submission.has_report),
  );
  if (available.length === 0) return null;

  return (
    <div className="mt-4 rounded-md border border-blue-100 bg-blue-50/40 p-4" data-testid="self-check-panel">
      <h4 className="font-bold">Check my submission</h4>
      <p className="mt-1 text-xs text-gray-600">
        Available until the deadline ({formatDateTime(assignment.deadline)}). You can run each check{" "}
        {status.limit_per_hour} times per hour. Results show only your own work.
      </p>
      <div className="mt-3 space-y-4">
        {available.map((c) => {
          const check = status.latest[c.kind];
          const busy = check?.status === "running" || starting === c.kind;
          const left = status.remaining[c.kind];
          return (
            <div key={c.kind} className="rounded-md border border-gray-200 bg-white p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold">{c.label}</p>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">
                    {left} of {status.limit_per_hour} left this hour
                  </span>
                  <button
                    type="button"
                    onClick={() => start(c.kind)}
                    disabled={busy || left === 0}
                    className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {busy ? "Checking..." : c.button}
                  </button>
                </div>
              </div>
              {check?.status === "running" && (
                <p className="mt-2 text-xs text-gray-600">
                  {c.kind === "ai_content"
                    ? "Checking... this can take about a minute."
                    : "Comparing with the other submissions..."}
                </p>
              )}
              {check?.status === "failed" && <p className="mt-2 text-sm text-red-700">{check.error}</p>}
              {check?.status === "done" && check.result && (
                <>
                  {!hidden.includes(check.id) &&
                    (c.kind === "ai_content" ? <AiResult check={check} /> : <SimilarityResult check={check} />)}
                  <div className="mt-1 flex flex-wrap items-center gap-3">
                    <span className="text-xs text-gray-400">
                      Checked {formatDateTime(check.finished_at ?? check.created_at)}
                    </span>
                    <button
                      type="button"
                      onClick={() => toggleHidden(check.id)}
                      aria-expanded={!hidden.includes(check.id)}
                      className="text-xs font-semibold text-blue-700 hover:underline"
                    >
                      {hidden.includes(check.id) ? "Show result" : "Hide result"}
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
      <Message state={msg} />
    </div>
  );
}
