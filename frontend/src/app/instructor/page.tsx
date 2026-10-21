"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiFetch,
  Assignment,
  AutoEvaluation,
  Rubric,
  SimilarityCheckResult,
  Submission,
  SubmissionFile,
} from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import CrossModalConsistencyPanel from "@/components/CrossModalConsistencyPanel";
import SubmissionFiles from "@/components/SubmissionFiles";
import AISignalsPanel from "@/components/AISignalsPanel";
import AssignmentsSection from "@/components/instructor/AssignmentsSection";
import BatchEvaluateSection from "@/components/instructor/BatchEvaluateSection";
import DownloadExcelButton from "@/components/instructor/DownloadExcelButton";
import ReportSimilarityPanel from "@/components/instructor/ReportSimilarityPanel";
import RubricModelToggle, {
  AiDetectionToggle,
  useAiDetectionSetting,
  useRubricModelSetting,
} from "@/components/instructor/RubricModelToggle";
import RubricsSection from "@/components/instructor/RubricsSection";
import { formatDateTime, formatMark } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";

/** Inline error for one criterion's mark, or null when it is fine. An empty box
 * is not an error (it is saved as 0). */
function scoreError(value: string | undefined, maxPoints: number): string | null {
  if (value === undefined || value.trim() === "") return null;
  const score = Number(value);
  if (!Number.isFinite(score)) return "Enter a number.";
  if (score < 0) return "Can't be below 0.";
  if (score > maxPoints) return `Max is ${maxPoints}.`;
  return null;
}

export default function InstructorPage() {
  const { user, ready } = useRequireRole("instructor");

  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);

  const [assignments, setAssignments] = useState<Assignment[]>([]);

  // Similarity check
  const [similarityAssignment, setSimilarityAssignment] = useState("");
  const [similarityResult, setSimilarityResult] = useState<SimilarityCheckResult | null>(null);
  const [similarityMsg, setSimilarityMsg] = useState<MessageState>(null);
  const [similarityRunning, setSimilarityRunning] = useState(false);

  // Auto-evaluation panel
  const [autoevalSubmissionId, setAutoevalSubmissionId] = useState<number | null>(null);
  const [autoevalRubricId, setAutoevalRubricId] = useState<number | null>(null);
  const [autoevalResult, setAutoevalResult] = useState<AutoEvaluation | null>(null);
  const [autoevalMsg, setAutoevalMsg] = useState<MessageState>(null);
  const [autoevalRunning, setAutoevalRunning] = useState(false);
  // The panel renders at the bottom of the page: bring it into view on every
  // "Auto-evaluate" click (a counter, so clicking the same student again works too).
  const autoevalPanelRef = useRef<HTMLElement>(null);
  const [autoevalScrollRequest, setAutoevalScrollRequest] = useState(0);
  useEffect(() => {
    if (autoevalScrollRequest > 0) autoevalPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [autoevalScrollRequest]);
  const [useRubricModel, setUseRubricModel] = useRubricModelSetting();
  const [useAiDetection, setUseAiDetection] = useAiDetectionSetting();

  // Grading panel
  const [gradingSubmissionId, setGradingSubmissionId] = useState<number | null>(null);
  // Which submission's uploaded files are expanded in the submissions table.
  const [filesOpenFor, setFilesOpenFor] = useState<{ id: number; kind: SubmissionFile["kind"] } | null>(null);
  // Which assignment's submissions the table shows: "all", "a:<assignment id>",
  // or "n:<name>" for submissions whose assignment was deleted (kept as records).
  const [submissionFilter, setSubmissionFilter] = useState("all");
  const [gradingRubricId, setGradingRubricId] = useState<number | null>(null);
  const [criterionScores, setCriterionScores] = useState<Record<string, string>>({});
  // "final": one overall mark (e.g. 70 / 100) instead of a mark per criterion.
  const [gradingMode, setGradingMode] = useState<"criteria" | "final">("criteria");
  const [finalMark, setFinalMark] = useState("");
  const [gradingComments, setGradingComments] = useState("");
  const [gradingMsg, setGradingMsg] = useState<MessageState>(null);
  // Same as the auto-evaluation panel: scroll the grading panel into view when it is opened.
  const gradingPanelRef = useRef<HTMLElement>(null);
  const [gradingScrollRequest, setGradingScrollRequest] = useState(0);
  useEffect(() => {
    if (gradingScrollRequest > 0) gradingPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [gradingScrollRequest]);

  const loadRubrics = useCallback(async (forSubject: number) => {
    setRubrics(await apiFetch<Rubric[]>(`/rubrics?subject_id=${forSubject}`));
  }, []);

  const loadAssignments = useCallback(async (forSubject: number) => {
    setAssignments(await apiFetch<Assignment[]>(`/assignments?subject_id=${forSubject}`));
  }, []);

  const reloadCourseSetup = useCallback(async () => {
    if (subjectId === null) return;
    await Promise.all([loadAssignments(subjectId), loadRubrics(subjectId)]);
  }, [subjectId, loadAssignments, loadRubrics]);

  const loadSubmissions = useCallback(async (forSubject: number) => {
    setSubmissions(await apiFetch<Submission[]>(`/submissions?subject_id=${forSubject}`));
  }, []);

  useEffect(() => {
    if (!ready || !user) return;
    if (user.subjects.length && subjectId === null) setSubjectId(user.subjects[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, user]);

  useEffect(() => {
    if (subjectId === null) return;
    setGradingSubmissionId(null);
    setAutoevalSubmissionId(null);
    loadRubrics(subjectId);
    loadAssignments(subjectId);
    loadSubmissions(subjectId);
  }, [subjectId, loadRubrics, loadAssignments, loadSubmissions]);

  const submissionOptions = useMemo(() => {
    const options = assignments.map((a) => ({ key: `a:${a.id}`, label: a.name, assignment: a as Assignment | null }));
    const orphanNames = Array.from(
      new Set(submissions.filter((sub) => sub.assignment_id === null).map((sub) => sub.assignment_name))
    );
    return [
      ...options,
      ...orphanNames.map((name) => ({ key: `n:${name}`, label: `${name} (deleted)`, assignment: null })),
    ];
  }, [assignments, submissions]);

  // Back to "All assignments" when the subject changes or the chosen one disappears.
  useEffect(() => {
    if (submissionFilter !== "all" && !submissionOptions.some((o) => o.key === submissionFilter)) {
      setSubmissionFilter("all");
    }
  }, [submissionOptions, submissionFilter]);
  useEffect(() => {
    setSubmissionFilter("all");
  }, [subjectId]);

  const selectedOption = submissionOptions.find((o) => o.key === submissionFilter) ?? null;
  const shownSubmissions = useMemo(() => {
    if (submissionFilter === "all") return submissions;
    if (submissionFilter.startsWith("a:")) {
      const id = Number(submissionFilter.slice(2));
      return submissions.filter((sub) => sub.assignment_id === id);
    }
    const name = submissionFilter.slice(2);
    return submissions.filter((sub) => sub.assignment_id === null && sub.assignment_name === name);
  }, [submissions, submissionFilter]);

  const assignmentNames = useMemo(
    () => Array.from(new Set(submissions.map((s) => s.assignment_name))),
    [submissions]
  );
  useEffect(() => {
    if (assignmentNames.length && !assignmentNames.includes(similarityAssignment)) {
      setSimilarityAssignment(assignmentNames[0]);
    }
    if (!assignmentNames.length) setSimilarityAssignment("");
  }, [assignmentNames, similarityAssignment]);

  function studentLabel(submissionId: number): string {
    const s = submissions.find((s) => s.id === submissionId);
    return s ? `${s.student_name} (#${submissionId})` : `#${submissionId}`;
  }

  // ---- Similarity check ----

  async function handleRunSimilarity() {
    setSimilarityMsg(null);
    setSimilarityResult(null);
    if (subjectId === null) {
      setSimilarityMsg({ text: "Pick a subject first.", kind: "error" });
      return;
    }
    if (!similarityAssignment) {
      setSimilarityMsg({ text: "No assignments with submissions yet.", kind: "error" });
      return;
    }
    setSimilarityRunning(true);
    try {
      const result = await apiFetch<SimilarityCheckResult>(
        `/subjects/${subjectId}/assignments/${encodeURIComponent(similarityAssignment)}/check-similarity`,
        { method: "POST" }
      );
      setSimilarityResult(result);
      const flaggedCount = result.pairs.filter((p) => p.flagged).length;
      setSimilarityMsg({
        text: flaggedCount
          ? `Compared ${result.compared} submissions -- potential similarity detected in ${flaggedCount} pair(s); lecturer review recommended.`
          : `Compared ${result.compared} submissions -- no pairs flagged.`,
        kind: flaggedCount ? "error" : "success",
      });
    } catch (err) {
      setSimilarityMsg({ text: `Similarity check failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSimilarityRunning(false);
    }
  }

  // ---- Auto-evaluation ----

  function openAutoevalPanel(submissionId: number) {
    setAutoevalSubmissionId(submissionId);
    setAutoevalResult(null);
    setAutoevalMsg(null);
    setAutoevalRubricId(rubrics[0]?.id ?? null);
    setAutoevalScrollRequest((n) => n + 1);
  }

  async function handleRunAutoeval() {
    if (autoevalSubmissionId === null || autoevalRubricId === null) return;
    setAutoevalMsg(null);
    setAutoevalRunning(true);
    try {
      const result = await apiFetch<AutoEvaluation>(`/submissions/${autoevalSubmissionId}/auto-evaluate`, {
        method: "POST",
        json: { rubric_id: autoevalRubricId, use_rubric_model: useRubricModel, use_ai_detection: useAiDetection },
      });
      setAutoevalResult(result);
      setAutoevalMsg({ text: "Auto-evaluation complete.", kind: "success" });
    } catch (err) {
      setAutoevalMsg({ text: `Auto-evaluation failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setAutoevalRunning(false);
    }
  }

  function useAutoevalScoresForGrading() {
    if (!autoevalResult || autoevalSubmissionId === null) return;
    const prefill: Record<string, string> = {};
    for (const c of autoevalResult.criterion_breakdown) prefill[c.name] = String(c.score);
    setAutoevalSubmissionId(null);
    openGradingPanel(autoevalSubmissionId, autoevalResult.rubric_id, prefill);
  }

  // ---- Manual grading ----

  function openGradingPanel(submissionId: number, rubricId: number | null = null, prefill: Record<string, string> = {}) {
    setGradingSubmissionId(submissionId);
    setGradingMsg(null);
    setGradingComments("");
    const submission = submissions.find((s) => s.id === submissionId);
    const assignmentRubric = assignments.find((a) => a.id === submission?.assignment_id)?.rubric_id ?? null;
    setGradingRubricId(rubricId ?? assignmentRubric ?? rubrics[0]?.id ?? null);
    setCriterionScores(prefill);
    setGradingMode("criteria");
    setFinalMark("");
    setGradingScrollRequest((n) => n + 1);
  }

  const gradingRubric = rubrics.find((r) => r.id === gradingRubricId) || null;
  const scoreErrors: Record<string, string> = {};
  for (const c of gradingRubric?.criteria ?? []) {
    const error = scoreError(criterionScores[c.name], c.max_points);
    if (error) scoreErrors[c.name] = error;
  }
  const finalMarkError = scoreError(finalMark, gradingRubric?.max_total ?? 0);
  const cannotSave =
    gradingMode === "final" ? finalMark.trim() === "" || finalMarkError !== null : Object.keys(scoreErrors).length > 0;

  async function handleSaveGrade() {
    if (gradingSubmissionId === null || gradingRubricId === null || cannotSave) return;
    setGradingMsg(null);
    let marks: { criterion_scores: Record<string, number> } | { total_score: number };
    if (gradingMode === "final") {
      marks = { total_score: Number(finalMark) };
    } else {
      const scores: Record<string, number> = {};
      for (const c of gradingRubric?.criteria ?? []) {
        scores[c.name] = parseFloat(criterionScores[c.name] || "0");
      }
      marks = { criterion_scores: scores };
    }
    try {
      await apiFetch(`/submissions/${gradingSubmissionId}/grade`, {
        method: "POST",
        json: { rubric_id: gradingRubricId, ...marks, comments: gradingComments },
      });
      setGradingMsg({ text: "Grade saved.", kind: "success" });
      if (subjectId !== null) await loadSubmissions(subjectId);
    } catch (err) {
      setGradingMsg({ text: `Failed to save grade: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }

  if (!ready || !user) return null;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Instructor dashboard</h1>
      <p className="mt-1 text-sm text-gray-600">
        Set up assignments and rubrics, run the automated evaluator, then grade manually or accept its scores as a
        starting point -- you always have the final say.
      </p>

      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <label className="block text-sm font-semibold" htmlFor="subject-selector">
          Subject
        </label>
        {user.subjects.length === 0 ? (
          <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            You haven&apos;t been assigned to any subjects yet -- ask your admin to assign you to one.
          </p>
        ) : (
          <select
            id="subject-selector"
            value={subjectId ?? ""}
            onChange={(e) => setSubjectId(parseInt(e.target.value, 10))}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {user.subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.code})
              </option>
            ))}
          </select>
        )}
      </section>

      {user.subjects.length > 0 && (
        <>
          {subjectId !== null && (
            <>
              <AssignmentsSection
                subjectId={subjectId}
                assignments={assignments}
                rubrics={rubrics}
                onChanged={reloadCourseSetup}
              />
              <RubricsSection subjectId={subjectId} rubrics={rubrics} onChanged={reloadCourseSetup} />
            </>
          )}

          {/* Similarity check */}
          <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold">Similarity Code Check</h2>
            <p className="mt-1 text-sm text-gray-600">
              Compares every code submission for one assignment pairwise and flags likely copies. The PDF reports
              can be compared below.
            </p>
            <label className="mt-3 block text-sm font-semibold" htmlFor="similarity-assignment">
              Assignment
            </label>
            <select
              id="similarity-assignment"
              value={similarityAssignment}
              onChange={(e) => setSimilarityAssignment(e.target.value)}
              disabled={similarityRunning}
              className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              {assignmentNames.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleRunSimilarity}
              disabled={similarityRunning}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {similarityRunning ? "Comparing code..." : "Check similarity"}
            </button>
            <Message state={similarityMsg} />
            {similarityResult && (
              <div className="mt-3">
                <DownloadExcelButton
                  path="/exports/code-similarity.xlsx"
                  result={similarityResult}
                  filePrefix="code-similarity"
                  assignmentName={similarityResult.assignment_name}
                />
              </div>
            )}

            {similarityResult && similarityResult.semantic.status !== "ok" && similarityResult.semantic.warning && (
              <div className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
                ⚠ {similarityResult.semantic.warning}
              </div>
            )}

            {similarityResult && similarityResult.pairs.length > 0 && (
              <>
                <dl className="mt-4 grid gap-x-4 gap-y-1 text-xs text-gray-600 sm:grid-cols-[max-content_1fr]">
                  <dt className="font-semibold">Shared fingerprints</dt>
                  <dd>Identical code fragments found in both (after normalizing names and literals).</dd>
                  <dt className="font-semibold">Jaccard</dt>
                  <dd>Share of all fingerprints that the two submissions have in common.</dd>
                  <dt className="font-semibold">Containment</dt>
                  <dd>Share of the smaller submission&apos;s fingerprints found in the other.</dd>
                  <dt className="font-semibold">Semantic</dt>
                  <dd>
                    UniXcoder similarity. A high value indicates that the submissions may implement similar logic even
                    though limited identical code fragments were detected. Students solving the same task naturally
                    score fairly high, so this is evidence for review, not proof.
                  </dd>
                </dl>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 text-left">
                        <th rowSpan={2} className="border border-gray-200 px-3 py-1.5">Student A</th>
                        <th rowSpan={2} className="border border-gray-200 px-3 py-1.5">Student B</th>
                        <th colSpan={3} className="border border-gray-200 px-3 py-1.5 text-center">
                          Token / fingerprint
                        </th>
                        <th rowSpan={2} className="border border-gray-200 px-3 py-1.5">Semantic</th>
                        <th rowSpan={2} className="border border-gray-200 px-3 py-1.5">Final flag</th>
                      </tr>
                      <tr className="bg-gray-50 text-left">
                        <th className="border border-gray-200 px-3 py-1.5">Shared</th>
                        <th className="border border-gray-200 px-3 py-1.5">Jaccard</th>
                        <th className="border border-gray-200 px-3 py-1.5">Containment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {similarityResult.pairs.map((p) => (
                        <tr
                          key={`${p.submission_a_id}-${p.submission_b_id}`}
                          className={
                            p.flag_level === "high" ? "bg-red-50" : p.flag_level === "review" ? "bg-yellow-50" : undefined
                          }
                        >
                          <td className="border border-gray-200 px-3 py-1.5">{studentLabel(p.submission_a_id)}</td>
                          <td className="border border-gray-200 px-3 py-1.5">{studentLabel(p.submission_b_id)}</td>
                          <td className="border border-gray-200 px-3 py-1.5">{p.shared_fingerprints}</td>
                          <td className="border border-gray-200 px-3 py-1.5">{(p.jaccard * 100).toFixed(0)}%</td>
                          <td className="border border-gray-200 px-3 py-1.5">{(p.containment * 100).toFixed(0)}%</td>
                          <td className="border border-gray-200 px-3 py-1.5">
                            {p.semantic_similarity === null ? (
                              <span className="text-gray-400" title="Semantic analysis not available for this pair">
                                —
                              </span>
                            ) : (
                              `${(p.semantic_similarity * 100).toFixed(0)}%`
                            )}
                          </td>
                          <td className="border border-gray-200 px-3 py-1.5">
                            {p.flag_level === "high" && <span className="font-semibold text-red-700">⚑ Review</span>}
                            {p.flag_level === "review" && (
                              <span className="font-semibold text-yellow-800">⚑ Review (semantic)</span>
                            )}
                            {p.flag_reason && <div className="text-xs text-gray-600">{p.flag_reason}</div>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {similarityResult.pairs.some((p) => p.flagged) && (
                  <p className="mt-2 text-xs text-gray-600">
                    Flagged pairs show potential similarity — lecturer review recommended. No flag is an automatic
                    finding of misconduct.
                  </p>
                )}
                {similarityResult.semantic.status === "ok" && (
                  <p className="mt-1 text-xs text-gray-500">
                    Semantic model: {similarityResult.semantic.model} · {similarityResult.semantic.submissions_encoded}{" "}
                    encoded, {similarityResult.semantic.cache_hits} reused from cache
                    {similarityResult.semantic.cohort_median !== null &&
                      ` · cohort median ${(similarityResult.semantic.cohort_median * 100).toFixed(0)}%`}
                    {similarityResult.semantic.review_threshold !== null &&
                      ` · semantic review threshold ${(similarityResult.semantic.review_threshold * 100).toFixed(0)}%`}
                    {similarityResult.semantic.skipped_too_small.length > 0 &&
                      ` · ${similarityResult.semantic.skipped_too_small.length} submission(s) too small to compare semantically`}
                  </p>
                )}
              </>
            )}

            <ReportSimilarityPanel subjectId={subjectId} assignmentNames={assignmentNames} />
          </section>

          {/* Evaluate a whole assignment */}
          {subjectId !== null && (
            <BatchEvaluateSection
              subjectId={subjectId}
              assignmentNames={assignmentNames}
              assignments={assignments}
              rubrics={rubrics}
            />
          )}

          {/* Submissions */}
          <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold">Submissions for this subject</h2>
            <label className="mt-3 block text-sm font-semibold" htmlFor="submissions-assignment">
              Assignment
            </label>
            <select
              id="submissions-assignment"
              value={submissionFilter}
              onChange={(e) => {
                setSubmissionFilter(e.target.value);
                setFilesOpenFor(null);
              }}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="all">All assignments ({submissions.length} submissions)</option>
              {submissionOptions.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>

            {selectedOption?.assignment && (
              <div className="mt-3 rounded-md border border-blue-100 bg-blue-50 px-4 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{selectedOption.assignment.name}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-semibold ${
                      selectedOption.assignment.status === "open"
                        ? "bg-green-100 text-green-800"
                        : selectedOption.assignment.status === "upcoming"
                          ? "bg-yellow-100 text-yellow-800"
                          : "bg-gray-200 text-gray-700"
                    }`}
                  >
                    {selectedOption.assignment.status === "open"
                      ? "Open"
                      : selectedOption.assignment.status === "upcoming"
                        ? "Upcoming"
                        : "Closed"}
                  </span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-gray-800">
                  {selectedOption.assignment.description || (
                    <span className="text-gray-500">No description was given for this assignment.</span>
                  )}
                </p>
                <dl className="mt-2 grid gap-x-4 gap-y-0.5 text-xs text-gray-700 sm:grid-cols-[max-content_1fr]">
                  <dt className="font-semibold">Open</dt>
                  <dd>
                    {formatDateTime(selectedOption.assignment.available_from)} to{" "}
                    {formatDateTime(selectedOption.assignment.deadline)}
                  </dd>
                  <dt className="font-semibold">Rubric</dt>
                  <dd>
                    {selectedOption.assignment.rubric_name
                      ? `${selectedOption.assignment.rubric_name} (${selectedOption.assignment.max_points} pts)`
                      : "None selected"}
                  </dd>
                  <dt className="font-semibold">Accepts</dt>
                  <dd className="capitalize">{selectedOption.assignment.submission_types.join(", ")}</dd>
                  <dt className="font-semibold">Submissions</dt>
                  <dd>
                    {shownSubmissions.length} ({shownSubmissions.filter((sub) => sub.status === "graded").length} graded)
                  </dd>
                </dl>
              </div>
            )}
            {selectedOption && !selectedOption.assignment && (
              <p className="mt-3 rounded-md bg-gray-50 px-4 py-3 text-sm text-gray-600">
                This assignment was deleted; its {shownSubmissions.length} submission(s) are kept as records.
              </p>
            )}

            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="border border-gray-200 px-3 py-1.5">Student</th>
                  <th className="border border-gray-200 px-3 py-1.5">Assignment</th>
                  <th className="border border-gray-200 px-3 py-1.5">Files submitted</th>
                  <th className="border border-gray-200 px-3 py-1.5">Submitted</th>
                  <th className="border border-gray-200 px-3 py-1.5">Status</th>
                  <th className="border border-gray-200 px-3 py-1.5">Mark</th>
                  <th className="border border-gray-200 px-3 py-1.5">Actions</th>
                </tr>
              </thead>
              <tbody>
                {shownSubmissions.length === 0 && (
                  <tr>
                    <td colSpan={7} className="border border-gray-200 px-3 py-3 text-center text-gray-500">
                      {submissionFilter === "all" ? "No submissions yet." : "No submissions for this assignment yet."}
                    </td>
                  </tr>
                )}
                {shownSubmissions.map((s) => (
                  <Fragment key={s.id}>
                  <tr>
                    <td className="border border-gray-200 px-3 py-1.5">
                      {s.student_name}
                      <br />
                      <small className="text-gray-500">{s.student_email}</small>
                    </td>
                    <td className="border border-gray-200 px-3 py-1.5">{s.assignment_name}</td>
                    <td className="border border-gray-200 px-3 py-1.5">
                      {s.submitted_types.length === 0 ? (
                        <span className="text-gray-400">none</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {s.submitted_types.map((kind) => {
                            const open = filesOpenFor?.id === s.id && filesOpenFor.kind === kind;
                            return (
                              <button
                                key={kind}
                                type="button"
                                aria-expanded={open}
                                title={open ? `Hide ${kind} files` : `Open ${kind} files`}
                                onClick={() => setFilesOpenFor(open ? null : { id: s.id, kind })}
                                className={`rounded px-2 py-0.5 text-xs font-semibold capitalize underline-offset-2 hover:underline ${
                                  open ? "bg-blue-600 text-white" : "bg-blue-50 text-blue-800 hover:bg-blue-100"
                                }`}
                              >
                                {kind}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </td>
                    <td className="border border-gray-200 px-3 py-1.5">{formatDateTime(s.submitted_at)}</td>
                    <td className="border border-gray-200 px-3 py-1.5">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          s.status === "graded" ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"
                        }`}
                      >
                        {s.status}
                      </span>
                    </td>
                    <td className="border border-gray-200 px-3 py-1.5">{formatMark(s.final_mark, s.max_mark)}</td>
                    <td className="border border-gray-200 px-3 py-1.5">
                      <div className="flex gap-1 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => openGradingPanel(s.id)}
                          className="rounded-md bg-blue-600 px-2 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                        >
                          {s.status === "graded" ? "Re-grade" : "Grade"}
                        </button>
                        <button
                          type="button"
                          onClick={() => openAutoevalPanel(s.id)}
                          className="rounded-md bg-gray-600 px-2 py-1 text-xs font-semibold text-white hover:bg-gray-700"
                        >
                          Auto-evaluate
                        </button>
                      </div>
                    </td>
                  </tr>
                  {filesOpenFor?.id === s.id && (
                    <tr>
                      <td colSpan={7} className="border border-gray-200 bg-white px-3 py-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <p className="text-sm font-semibold">
                            <span className="capitalize">{filesOpenFor.kind}</span> submitted by {s.student_name}
                          </p>
                          <button
                            type="button"
                            onClick={() => setFilesOpenFor(null)}
                            className="rounded-md bg-gray-600 px-2 py-1 text-xs font-semibold text-white hover:bg-gray-700"
                          >
                            Close
                          </button>
                        </div>
                        <SubmissionFiles key={filesOpenFor.kind} submissionId={s.id} kind={filesOpenFor.kind} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>

          {/* Auto-evaluation panel */}
          {autoevalSubmissionId !== null && (
            <section
              ref={autoevalPanelRef}
              className="mt-6 scroll-mt-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
            >
              <h2 className="text-lg font-bold">
                Auto-evaluation {studentLabel(autoevalSubmissionId)}
              </h2>
              <p className="mt-1 text-sm text-gray-600">
                Runs the automated evaluator (static analysis, AI-content heuristics, cross-modal consistency,
                rubric grading) against this submission.
              </p>
              <label className="mt-3 block text-sm font-semibold" htmlFor="autoeval-rubric">
                Rubric
              </label>
              <select
                id="autoeval-rubric"
                value={autoevalRubricId ?? ""}
                onChange={(e) => setAutoevalRubricId(parseInt(e.target.value, 10))}
                className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {rubrics.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <RubricModelToggle on={useRubricModel} onChange={setUseRubricModel} disabled={autoevalRunning} />
              <AiDetectionToggle on={useAiDetection} onChange={setUseAiDetection} disabled={autoevalRunning} />
              <div className="mt-3 space-x-2">
                <button
                  type="button"
                  disabled={autoevalRunning}
                  onClick={handleRunAutoeval}
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {autoevalRunning ? "Running..." : "Run auto-evaluation"}
                </button>
                <button
                  type="button"
                  onClick={() => setAutoevalSubmissionId(null)}
                  className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
                >
                  Cancel
                </button>
              </div>
              <Message state={autoevalMsg} />

              {autoevalResult && (
                <div className="mt-4">
                  <h3 className="font-bold">
                    Recommended score: {autoevalResult.recommended_score} / {autoevalResult.recommended_max} (
                    {autoevalResult.model ? `${autoevalResult.grader}, model ${autoevalResult.model}` : autoevalResult.grader} grader)
                  </h3>
                  <div className="mt-2">
                    <strong className="text-sm">Review flags:</strong>
                    <ul className="ml-5 list-disc text-sm">
                      {autoevalResult.review_flags.length ? (
                        autoevalResult.review_flags.map((f, i) => <li key={i}>{f}</li>)
                      ) : (
                        <li>Nothing flagged for review.</li>
                      )}
                    </ul>
                  </div>
                  <CrossModalConsistencyPanel result={autoevalResult.cross_modal_consistency} />
                  <AISignalsPanel result={autoevalResult} />
                  <table className="mt-3 w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 text-left">
                        <th className="border border-gray-200 px-3 py-1.5">Criterion</th>
                        <th className="border border-gray-200 px-3 py-1.5">Score</th>
                        <th className="border border-gray-200 px-3 py-1.5">Justification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {autoevalResult.criterion_breakdown.map((c, i) => (
                        <tr key={i}>
                          <td className="border border-gray-200 px-3 py-1.5">{c.name}</td>
                          <td className="border border-gray-200 px-3 py-1.5">
                            {c.score} / {c.max_points}
                          </td>
                          <td className="border border-gray-200 px-3 py-1.5">{c.justification}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <button
                    type="button"
                    onClick={useAutoevalScoresForGrading}
                    className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                  >
                    Use these scores as starting point for manual grading
                  </button>
                </div>
              )}
            </section>
          )}

          {/* Grading panel */}
          {gradingSubmissionId !== null && (
            <section
              ref={gradingPanelRef}
              className="mt-6 scroll-mt-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
            >
              <h2 className="text-lg font-bold">Grade submission {studentLabel(gradingSubmissionId)}</h2>
              <label className="mt-3 block text-sm font-semibold" htmlFor="grading-rubric">
                Rubric
              </label>
              <select
                id="grading-rubric"
                value={gradingRubricId ?? ""}
                onChange={(e) => setGradingRubricId(parseInt(e.target.value, 10))}
                className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {rubrics.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} ({r.max_total} pts)
                  </option>
                ))}
              </select>

              <fieldset className="mb-3 rounded-md border border-blue-100 bg-blue-50 px-3 py-2">
                <legend className="sr-only">How to grade</legend>
                <div className="flex flex-wrap gap-4 text-sm">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="grading-mode"
                      checked={gradingMode === "criteria"}
                      onChange={() => setGradingMode("criteria")}
                    />
                    Mark each criterion
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="grading-mode"
                      checked={gradingMode === "final"}
                      onChange={() => setGradingMode("final")}
                    />
                    Final mark only
                  </label>
                </div>
                {gradingMode === "final" && (
                  <div className="mt-2">
                    <div className="flex items-center gap-2">
                      <label className="text-sm font-semibold" htmlFor="final-mark">
                        Final mark
                      </label>
                      <input
                        id="final-mark"
                        type="text"
                        inputMode="decimal"
                        autoComplete="off"
                        value={finalMark}
                        placeholder="70"
                        aria-invalid={Boolean(finalMarkError)}
                        aria-describedby={finalMarkError ? "final-mark-error" : undefined}
                        onChange={(e) => setFinalMark(e.target.value)}
                        className={`w-24 rounded-md border px-2 py-1.5 text-sm ${
                          finalMarkError ? "border-red-500 bg-red-50" : "border-gray-300"
                        }`}
                      />
                      <span className="text-sm">/ {gradingRubric?.max_total ?? 0}</span>
                    </div>
                    {finalMarkError && (
                      <p id="final-mark-error" className="mt-1 text-xs text-red-700">
                        {finalMarkError}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-gray-600">
                      No per-criterion marks are saved. Students see only this final mark.
                    </p>
                  </div>
                )}
              </fieldset>

              {gradingMode === "criteria" && (
                <>
                  <div className="space-y-2">
                    {gradingRubric?.criteria.map((c) => {
                      const error = scoreErrors[c.name];
                      const inputId = `score-${c.name}`;
                      return (
                        <div key={c.name} className="flex items-start gap-3">
                          <label className="flex-1 pt-1.5 text-sm" htmlFor={inputId}>
                            {c.name}{" "}
                            <small className="text-gray-500">
                              ({c.description || "no description"}, max {c.max_points})
                            </small>
                          </label>
                          <div className="w-28 shrink-0">
                            <input
                              id={inputId}
                              // Text, not type="number": a number box reports "abc" as empty,
                              // which would hide the error and save 0.
                              type="text"
                              inputMode="decimal"
                              autoComplete="off"
                              value={criterionScores[c.name] ?? ""}
                              aria-invalid={Boolean(error)}
                              aria-describedby={error ? `${inputId}-error` : undefined}
                              onChange={(e) => setCriterionScores((prev) => ({ ...prev, [c.name]: e.target.value }))}
                              className={`w-full rounded-md border px-2 py-1.5 text-sm ${
                                error ? "border-red-500 bg-red-50" : "border-gray-300"
                              }`}
                            />
                            {error && (
                              <p id={`${inputId}-error`} className="mt-1 text-xs text-red-700">
                                {error}
                              </p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <p className="mt-3 text-sm font-semibold">
                    Final mark:{" "}
                    {(gradingRubric?.criteria ?? []).reduce((sum, c) => sum + (parseFloat(criterionScores[c.name]) || 0), 0)} /{" "}
                    {gradingRubric?.max_total ?? 0}
                    <span className="ml-2 text-xs font-normal text-gray-500">
                      Students see only this final mark, not the per-criterion scores or comments.
                    </span>
                  </p>
                </>
              )}

              <label className="mt-3 block text-sm font-semibold" htmlFor="grading-comments">
                Comments (internal)
              </label>
              <textarea
                id="grading-comments"
                value={gradingComments}
                onChange={(e) => setGradingComments(e.target.value)}
                placeholder="Grading notes (visible to instructors only)"
                className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                rows={3}
              />

              <div className="space-x-2">
                <button
                  type="button"
                  onClick={handleSaveGrade}
                  disabled={cannotSave}
                  title={
                    cannotSave
                      ? gradingMode === "final" && finalMark.trim() === ""
                        ? "Enter the final mark first"
                        : "Fix the marks shown in red first"
                      : undefined
                  }
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Save grade
                </button>
                <button
                  type="button"
                  onClick={() => setGradingSubmissionId(null)}
                  className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
                >
                  Cancel
                </button>
              </div>
              <Message state={gradingMsg} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
