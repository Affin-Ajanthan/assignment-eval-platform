"use client";

import { useEffect, useState } from "react";
import { apiFetch, Assignment, BatchEvaluationResult, Rubric } from "@/lib/api";
import { formatMark } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";

const STATUS_STYLE: Record<string, string> = {
  evaluated: "bg-green-50 text-green-800",
  skipped: "bg-gray-100 text-gray-700",
  failed: "bg-red-50 text-red-700",
};

/**
 * "Evaluate a whole assignment": runs the automated evaluation for every
 * submission of one assignment against one rubric. The backend call is
 * synchronous (submissions run one after another), so it can take minutes
 * with a local LLM -- the card says so and locks its controls meanwhile.
 */
export default function BatchEvaluateSection({
  subjectId,
  assignmentNames,
  assignments,
  rubrics,
}: {
  subjectId: number;
  assignmentNames: string[];
  assignments: Assignment[];
  rubrics: Rubric[];
}) {
  const [assignment, setAssignment] = useState("");
  const [rubricId, setRubricId] = useState<number | null>(null);
  const [skipDone, setSkipDone] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BatchEvaluationResult | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);

  // Keep the selected assignment valid as the list changes.
  useEffect(() => {
    if (assignmentNames.length && !assignmentNames.includes(assignment)) setAssignment(assignmentNames[0]);
    if (!assignmentNames.length) setAssignment("");
  }, [assignmentNames, assignment]);

  // Default to the assignment's own rubric, else the first rubric.
  useEffect(() => {
    const own = assignments.find((a) => a.name === assignment)?.rubric_id ?? null;
    setRubricId(own !== null && rubrics.some((r) => r.id === own) ? own : (rubrics[0]?.id ?? null));
    setResult(null);
    setMsg(null);
  }, [assignment, assignments, rubrics]);

  const count = assignments.find((a) => a.name === assignment)?.submission_count;

  async function run() {
    if (!assignment || rubricId === null) return;
    setMsg(null);
    setResult(null);
    setRunning(true);
    try {
      const res = await apiFetch<BatchEvaluationResult>(
        `/subjects/${subjectId}/assignments/${encodeURIComponent(assignment)}/auto-evaluate`,
        { method: "POST", json: { rubric_id: rubricId, skip_already_evaluated: skipDone } }
      );
      setResult(res);
      setMsg({
        text: `Done: ${res.evaluated} evaluated, ${res.skipped} skipped, ${res.failed} failed (of ${res.total}).`,
        kind: res.failed > 0 ? "error" : "success",
      });
    } catch (err) {
      setMsg({
        text: `Batch evaluation failed: ${err instanceof Error ? err.message : err}. Results already produced are saved -- tick "skip already evaluated" and run again to continue.`,
        kind: "error",
      });
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Evaluate a whole assignment</h2>
      <p className="mt-1 text-sm text-gray-600">
        Runs the automated evaluation for every submission of one assignment, one after another. Run the similarity
        check first so its flags are included. Automated results are a second opinion; your manual grade always counts.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-sm font-semibold" htmlFor="batch-assignment">
            Assignment
          </label>
          <select
            id="batch-assignment"
            value={assignment}
            disabled={running}
            onChange={(e) => setAssignment(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {assignmentNames.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-semibold" htmlFor="batch-rubric">
            Rubric
          </label>
          <select
            id="batch-rubric"
            value={rubricId ?? ""}
            disabled={running}
            onChange={(e) => setRubricId(e.target.value ? Number(e.target.value) : null)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {rubrics.length === 0 && <option value="">No rubrics yet</option>}
            {rubrics.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={skipDone} disabled={running} onChange={(e) => setSkipDone(e.target.checked)} />
        Skip submissions already evaluated with this rubric (use to resume)
      </label>

      <button
        type="button"
        onClick={run}
        disabled={running || !assignment || rubricId === null}
        className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {running ? "Evaluating…" : `Evaluate all${count !== undefined ? ` ${count} submission(s)` : ""}`}
      </button>

      {running && (
        <div className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          ⏳ This can take several minutes (roughly 10–20 seconds per submission with the local model). Keep this page
          open until it finishes.
        </div>
      )}
      <Message state={msg} />

      {result && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left">
                <th className="border border-gray-200 px-3 py-1.5">Student</th>
                <th className="border border-gray-200 px-3 py-1.5">Status</th>
                <th className="border border-gray-200 px-3 py-1.5">Recommended</th>
                <th className="border border-gray-200 px-3 py-1.5">Grader</th>
                <th className="border border-gray-200 px-3 py-1.5">Notes</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((r) => (
                <tr key={r.submission_id}>
                  <td className="border border-gray-200 px-3 py-1.5">
                    {r.student_name} (#{r.submission_id})
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[r.status] ?? ""}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    {r.recommended_score === null ? "—" : formatMark(r.recommended_score, r.recommended_max)}
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">{r.grader ?? "—"}</td>
                  <td className="border border-gray-200 px-3 py-1.5 text-xs">
                    {r.error && <div className="text-red-700">{r.error}</div>}
                    {r.review_flags.map((f) => (
                      <div key={f} className="text-yellow-800">
                        ⚑ {f}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-gray-500">
            Open a submission in the table below and use &ldquo;Auto-evaluate&rdquo; to see the full per-criterion
            breakdown, then grade manually.
          </p>
        </div>
      )}
    </section>
  );
}
