"use client";

import { useEffect, useState } from "react";
import { AISignal, apiFetch, Assignment, BatchEvaluationItem, BatchEvaluationResult, BatchJob, Rubric } from "@/lib/api";
import Badge from "@/components/Badge";
import { methodLabel } from "@/components/AISignalsPanel";
import { formatMark } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";
import DownloadExcelButton from "@/components/instructor/DownloadExcelButton";
import RubricModelToggle, {
  AiDetectionToggle,
  useAiDetectionSetting,
  useRubricModelSetting,
} from "@/components/instructor/RubricModelToggle";

const STATUS_STYLE: Record<string, string> = {
  evaluated: "bg-green-50 text-green-800",
  skipped: "bg-gray-100 text-gray-700",
  failed: "bg-red-50 text-red-700",
};

/** "⚑ Flagged" for a review flag, "No flag" when clear, "—" when unknown (failed run). */
function FlagBadge({ flagged }: { flagged: boolean | null }) {
  if (flagged === null) return <span className="text-gray-400">—</span>;
  return flagged ? (
    <span className="rounded bg-yellow-50 px-2 py-0.5 text-xs font-semibold text-yellow-800">⚑ Flagged</span>
  ) : (
    <span className="rounded bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-800">No flag</span>
  );
}

/**
 * "Report: High 73 · Fast-DetectGPT (Qwen2.5-1.5B)". A report scored by the
 * style heuristic is marked, since that only happens when the model is off
 * or failed to load.
 */
function AISignalLine({ label, signal, report }: { label: string; signal: AISignal | null; report?: boolean }) {
  if (!signal) return null;
  const heuristic = !signal.method.startsWith("fast-detectgpt:");
  return (
    <div className="mt-1 text-xs text-gray-600">
      {label}: <span className="capitalize">{signal.signal}</span> {signal.score} · {methodLabel(signal.method)}
      {report && heuristic && <span className="text-red-700"> (model not used)</span>}
    </div>
  );
}

/** How often a running job's progress is fetched. */
const POLL_MS = 3000;

const isActive = (job: BatchJob | null) => job !== null && (job.status === "queued" || job.status === "running");

/** The finished part of a job in the shape the Excel export expects. */
function jobResult(job: BatchJob): BatchEvaluationResult {
  return {
    subject_id: job.subject_id,
    assignment_name: job.assignment_name,
    rubric_id: job.rubric_id,
    total: job.total,
    evaluated: job.evaluated,
    skipped: job.skipped,
    failed: job.failed,
    results: job.results.filter((r): r is BatchEvaluationItem => r !== null),
  };
}

/**
 * "Evaluate a whole assignment": runs the automated evaluation for every
 * submission of one assignment against one rubric. The server runs it as a
 * background job (it can take many minutes with a local LLM); this card
 * starts the job, then polls its progress and fills in the results as each
 * submission finishes.
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
  const [useRubricModel, setUseRubricModel] = useRubricModelSetting();
  const [useAiDetection, setUseAiDetection] = useAiDetectionSetting();
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<BatchJob | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const running = starting || isActive(job);

  // Keep the selected assignment valid as the list changes.
  useEffect(() => {
    if (assignmentNames.length && !assignmentNames.includes(assignment)) setAssignment(assignmentNames[0]);
    if (!assignmentNames.length) setAssignment("");
  }, [assignmentNames, assignment]);

  // Default to the assignment's own rubric, else the first rubric.
  useEffect(() => {
    const own = assignments.find((a) => a.name === assignment)?.rubric_id ?? null;
    setRubricId(own !== null && rubrics.some((r) => r.id === own) ? own : (rubrics[0]?.id ?? null));
    // Keep a job of this same assignment (e.g. the list reloaded mid-run); clear any other.
    setJob((j) => (j && j.assignment_name === assignment ? j : null));
    setMsg(null);
  }, [assignment, assignments, rubrics]);

  // While the job runs, fetch its progress every few seconds; stop once it has finished.
  useEffect(() => {
    if (!job || !isActive(job)) return;
    const timer = setTimeout(async () => {
      try {
        setJob(await apiFetch<BatchJob>(`/auto-evaluate/jobs/${job.id}`));
      } catch (err) {
        setMsg({ text: `Could not fetch progress (retrying): ${err instanceof Error ? err.message : err}`, kind: "error" });
        setJob((j) => (j ? { ...j } : j)); // a new object, so this effect runs again and retries
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job]);

  // Summary once the job has finished.
  useEffect(() => {
    if (job?.status === "done") {
      setMsg({
        text: `Done: ${job.evaluated} evaluated, ${job.skipped} skipped, ${job.failed} failed (of ${job.total}).`,
        kind: job.failed > 0 ? "error" : "success",
      });
    } else if (job?.status === "failed") {
      setMsg({
        text: `Batch evaluation stopped: ${job.error ?? "unknown error"}. Results already produced are saved -- tick "skip already evaluated" and run again to continue.`,
        kind: "error",
      });
    }
  }, [job?.status, job?.evaluated, job?.skipped, job?.failed, job?.total, job?.error]);

  const count = assignments.find((a) => a.name === assignment)?.submission_count;
  const finished = job ? job.results.filter((r): r is BatchEvaluationItem => r !== null) : [];
  const result = job?.status === "done" ? jobResult(job) : null;
  const percent = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;

  async function run() {
    if (!assignment || rubricId === null) return;
    setMsg(null);
    setJob(null);
    setStarting(true);
    try {
      setJob(
        await apiFetch<BatchJob>(
          `/subjects/${subjectId}/assignments/${encodeURIComponent(assignment)}/auto-evaluate/jobs`,
          { method: "POST", json: { rubric_id: rubricId, skip_already_evaluated: skipDone, use_rubric_model: useRubricModel, use_ai_detection: useAiDetection } }
        )
      );
    } catch (err) {
      setMsg({ text: `Could not start the evaluation: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Evaluate a whole assignment</h2>
      <p className="mt-1 text-sm text-gray-600">
        Runs the automated evaluation for every submission of one assignment (one after another, or several at a time
        when the server is set up for it). Run the similarity
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

      <RubricModelToggle on={useRubricModel} onChange={setUseRubricModel} disabled={running} />
      <AiDetectionToggle on={useAiDetection} onChange={setUseAiDetection} disabled={running} />

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
        {starting ? "Starting…" : running ? "Evaluating…" : `Evaluate all${count !== undefined ? ` ${count} submission(s)` : ""}`}
      </button>

      {job && isActive(job) && (
        <div className="mt-3 rounded-md border border-blue-100 bg-blue-50 px-3 py-2" data-testid="batch-progress">
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span className="font-semibold text-blue-900">
              {job.status === "queued" ? "Starting…" : `${job.done} / ${job.total} done`}
            </span>
            <span className="text-xs text-blue-900">
              {job.evaluated} evaluated · {job.skipped} skipped · {job.failed} failed
            </span>
          </div>
          <div
            className="mt-2 h-2 w-full overflow-hidden rounded bg-blue-100"
            role="progressbar"
            aria-label="Evaluation progress"
            aria-valuemin={0}
            aria-valuemax={job.total}
            aria-valuenow={job.done}
          >
            <div className="h-full bg-blue-600 transition-all" style={{ width: `${percent}%` }} />
          </div>
          <p className="mt-2 text-xs text-blue-900">
            Grading runs on the server and continues even if you close this page. Results appear below as each
            submission finishes.
          </p>
        </div>
      )}
      <Message state={msg} />
      {result && (
        <div className="mt-3">
          <DownloadExcelButton
            path="/exports/batch-evaluation.xlsx"
            result={result}
            filePrefix="evaluation"
            assignmentName={result.assignment_name}
          />
        </div>
      )}

      {finished.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left">
                <th className="border border-gray-200 px-3 py-1.5">Student</th>
                <th className="border border-gray-200 px-3 py-1.5">Status</th>
                <th className="border border-gray-200 px-3 py-1.5">Marks</th>
                <th className="border border-gray-200 px-3 py-1.5">Similarity flag</th>
                <th className="border border-gray-200 px-3 py-1.5">AI detection flag</th>
                <th className="border border-gray-200 px-3 py-1.5">Grader</th>
                <th className="border border-gray-200 px-3 py-1.5">Notes</th>
              </tr>
            </thead>
            <tbody>
              {finished.map((r) => (
                <tr key={r.submission_id}>
                  <td className="border border-gray-200 px-3 py-1.5">
                    {r.student_name} (#{r.submission_id})
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    <Badge tone={STATUS_STYLE[r.status] ?? ""}>{r.status}</Badge>
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    {r.recommended_score === null ? "—" : formatMark(r.recommended_score, r.recommended_max)}
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    <FlagBadge flagged={r.similarity_flagged} />
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    <FlagBadge flagged={r.ai_flagged} />
                    <AISignalLine label="Report" signal={r.ai_signals?.report ?? null} report />
                    <AISignalLine label="Code" signal={r.ai_signals?.code ?? null} />
                  </td>
                  <td className="border border-gray-200 px-3 py-1.5">
                    {r.grader ? (r.model ? `${r.grader}, ${r.model}` : r.grader) : "—"}
                  </td>
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
