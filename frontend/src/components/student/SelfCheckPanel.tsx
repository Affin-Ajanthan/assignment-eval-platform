"use client";

import { useState } from "react";
import { MySubmission, SelfCheckKind, StudentAssignment } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import Message from "@/components/Message";
import { AiResult, SimilarityResult } from "@/components/student/SelfCheckResults";
import { CHECKS } from "@/lib/selfCheckBands";
import { useHiddenResults } from "@/lib/useHiddenResults";
import { useSelfCheckStatus } from "@/lib/useSelfCheckStatus";

/** The checks this assignment allows for the parts the student uploaded. */
function availableChecks(assignment: StudentAssignment, submission: MySubmission): SelfCheckKind[] {
  return CHECKS.map((c) => c.kind).filter((kind) =>
    kind === "ai_content"
      ? assignment.student_ai_check && (submission.has_code || submission.has_report)
      : assignment.student_similarity_check && (kind === "code_similarity" ? submission.has_code : submission.has_report),
  );
}

/** The open panel: loads this submission's checks (and polls while one runs). */
function SelfCheckBody({
  assignment,
  submission,
  kinds,
}: {
  assignment: StudentAssignment;
  submission: MySubmission;
  kinds: SelfCheckKind[];
}) {
  const { status, msg, starting, start } = useSelfCheckStatus(submission.id, submission.submitted_at);
  const [hidden, toggleHidden] = useHiddenResults();

  if (!status) return <p className="mt-2 text-xs text-gray-500">Loading your checks...</p>;
  if (!status.can_run) return <p className="mt-2 text-xs text-gray-600">Self-checks are closed for this submission.</p>;

  // The server has the final say on which checks are switched on.
  const available = CHECKS.filter(
    (c) =>
      kinds.includes(c.kind) && (c.kind === "ai_content" ? status.ai_enabled : status.similarity_enabled),
  );
  if (available.length === 0) {
    return <p className="mt-2 text-xs text-gray-600">Your instructor has turned self-checks off for this assignment.</p>;
  }

  return (
    <>
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
    </>
  );
}

/**
 * "Check my submission": similarity and AI-content self-checks while the
 * assignment is open. Collapsed by default -- nothing is requested until the
 * student opens it, so a page with many assignments stays light.
 */
export default function SelfCheckPanel({ assignment, submission }: { assignment: StudentAssignment; submission: MySubmission }) {
  const [open, setOpen] = useState(false);
  const kinds = availableChecks(assignment, submission);
  if (kinds.length === 0) return null;

  return (
    <div className="mt-4 rounded-md border border-blue-100 bg-blue-50/40 p-4" data-testid="self-check-panel">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <span className="font-bold">Check my submission</span>
        <span className="text-xs font-semibold text-blue-700">{open ? "Close ▴" : "Open ▾"}</span>
      </button>
      {!open && (
        <p className="mt-1 text-xs text-gray-600">
          Check your work for{" "}
          {[kinds.some((k) => k !== "ai_content") && "similarity", kinds.includes("ai_content") && "AI content"]
            .filter(Boolean)
            .join(" and ")}{" "}
          before the deadline.
        </p>
      )}
      {open && <SelfCheckBody assignment={assignment} submission={submission} kinds={kinds} />}
    </div>
  );
}
