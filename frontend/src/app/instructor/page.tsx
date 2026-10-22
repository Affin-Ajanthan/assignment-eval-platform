"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiFetch,
  Assignment,
  AutoEvaluation,
  Rubric,
  SimilarityCheckResult,
  Grade,
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
import SelfCheckHistoryPanel from "@/components/instructor/SelfCheckHistoryPanel";
import RubricModelToggle, {
  AiDetectionToggle,
  useAiDetectionSetting,
  useRubricModelSetting,
} from "@/components/instructor/RubricModelToggle";
import RubricsSection from "@/components/instructor/RubricsSection";
import { formatDateTime, formatMark } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";

/** Inline error for one criterion's mark, or null when it is fine. An empty box
 * is not an error (it is saved as 0). */
function scoreError(value: string | undefined, maxPoints: number): string | null {
  if (value === undefined || value.trim() === "") return null;
  const score = Number(value);
  if (!Number.isFinite(score)) return "Enter a number.";
  if (score < 0) return "Can't be below 0.";
  if (score > maxPoints) return `Max is ${maxPoints}.`;
  if (roundMark(score) !== score) return "Use at most 2 decimal places.";
  return null;
}

/** What the grading form holds, as a string to compare with the last loaded or
 * saved state. The mode alone does not count: switching "Final mark only" on
 * and off without typing anything is not an unsaved change. */
function gradingSnapshot(
  mode: "criteria" | "final",
  scores: Record<string, string>,
  finalMark: string,
  comments: string,
): string {
  const marks =
    mode === "final"
      ? finalMark.trim()
      : Object.entries(scores)
          .map(([name, value]) => [name, value.trim()])
          .filter(([, value]) => value !== "")
          .sort(([a], [b]) => a.localeCompare(b));
  const hasMarks = marks.length > 0;
  return JSON.stringify(hasMarks ? [mode, marks, comments.trim()] : [null, null, comments.trim()]);
}

const STATUS_FILTERS: { label: string; status: Submission["status"] | null }[] = [
  { label: "All", status: null },
  { label: "Submitted", status: "submitted" },
  { label: "Graded", status: "graded" },
];

/** A mark rounded to the 2 decimal places the API accepts. */
function roundMark(score: number): number {
  return Math.round(score * 100) / 100;
}

/** The rubric for grading or auto-evaluating one submission. When the assignment
 * has a rubric it is fixed (the API refuses any other); otherwise any rubric of
 * the subject can be picked. */
function RubricField({
  id,
  rubrics,
  value,
  locked,
  onChange,
}: {
  id: string;
  rubrics: Rubric[];
  value: number | null;
  locked: boolean;
  onChange: (rubricId: number) => void;
}) {
  const current = rubrics.find((r) => r.id === value);
  return (
    <div className="mt-3 mb-3">
      <label className="block text-sm font-semibold" htmlFor={id}>
        Rubric
      </label>
      {locked ? (
        <p id={id} className="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
          {current ? `${current.name} (${current.max_total} pts)` : "Rubric not found"}
          <span className="ml-2 text-xs text-gray-500">Set by the assignment</span>
        </p>
      ) : (
        <select
          id={id}
          value={value ?? ""}
          onChange={(e) => onChange(parseInt(e.target.value, 10))}
          className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        >
          {rubrics.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} ({r.max_total} pts)
            </option>
          ))}
        </select>
      )}
    </div>
  );
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
  const [statusFilter, setStatusFilter] = useState<Submission["status"] | null>(null); // null: all
  const [gradingRubricId, setGradingRubricId] = useState<number | null>(null);
  const [criterionScores, setCriterionScores] = useState<Record<string, string>>({});
  // "final": one overall mark (e.g. 70 / 100) instead of a mark per criterion.
  const [gradingMode, setGradingMode] = useState<"criteria" | "final">("criteria");
  const [finalMark, setFinalMark] = useState("");
  // Set once Save is pressed with empty criterion boxes, so those boxes are highlighted.
  const [showEmptyMarks, setShowEmptyMarks] = useState(false);
  const [gradingConfirm, setGradingConfirm] = useState<ConfirmRequest | null>(null);
  // The form as last opened, loaded or saved; anything else is an unsaved change.
  const [gradingBaseline, setGradingBaseline] = useState("");
  // Re-grade: the saved grade is loaded into the form. gradeLoadFor ignores a
  // reply that arrives after another submission's panel was opened.
  const [loadingSavedGrade, setLoadingSavedGrade] = useState(false);
  const [savedGradeNote, setSavedGradeNote] = useState<string | null>(null);
  const gradeLoadFor = useRef<number | null>(null);
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
    setStatusFilter(null);
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
  // The status filter narrows only the table; the assignment summary and
  // "Save & next" still use every submission of the chosen assignment.
  const tableSubmissions = statusFilter ? shownSubmissions.filter((s) => s.status === statusFilter) : shownSubmissions;

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

  // The rubric a submission's assignment is graded with; null when the
  // assignment has none (then any rubric of the subject may be used).
  function assignmentRubricFor(submissionId: number | null): number | null {
    const submission = submissions.find((s) => s.id === submissionId);
    return assignments.find((a) => a.id === submission?.assignment_id)?.rubric_id ?? null;
  }

  // ---- Auto-evaluation ----

  function openAutoevalPanel(submissionId: number) {
    setAutoevalSubmissionId(submissionId);
    setAutoevalResult(null);
    setAutoevalMsg(null);
    setAutoevalRubricId(assignmentRubricFor(submissionId) ?? rubrics[0]?.id ?? null);
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
    for (const c of autoevalResult.criterion_breakdown) prefill[c.name] = String(roundMark(c.score));
    const submissionId = autoevalSubmissionId;
    const rubricId = autoevalResult.rubric_id;
    confirmDiscardThen(() => {
      setAutoevalSubmissionId(null);
      openGradingPanel(submissionId, rubricId, prefill);
    });
  }

  // ---- Manual grading ----

  function openGradingPanel(submissionId: number, rubricId: number | null = null, prefill: Record<string, string> = {}) {
    setGradingSubmissionId(submissionId);
    setGradingMsg(null);
    setGradingComments("");
    const submission = submissions.find((s) => s.id === submissionId);
    // The assignment's own rubric always wins: grading with another one is refused.
    setGradingRubricId(assignmentRubricFor(submissionId) ?? rubricId ?? rubrics[0]?.id ?? null);
    setCriterionScores(prefill);
    setGradingMode("criteria");
    setFinalMark("");
    // Auto-evaluation scores (prefill) are not saved yet, so they count as unsaved marks.
    setGradingBaseline(gradingSnapshot("criteria", {}, "", ""));
    setShowEmptyMarks(false);
    setSavedGradeNote(null);
    setLoadingSavedGrade(false);
    setGradingScrollRequest((n) => n + 1);
    gradeLoadFor.current = null;
    // Re-grade starts from the saved grade, not a blank form. Auto-evaluation
    // scores (prefill) take precedence: the instructor asked for those.
    if (submission?.status === "graded" && Object.keys(prefill).length === 0) {
      loadSavedGrade(submissionId);
    }
  }

  async function loadSavedGrade(submissionId: number) {
    gradeLoadFor.current = submissionId;
    setLoadingSavedGrade(true);
    try {
      const grade = await apiFetch<Grade | null>(`/submissions/${submissionId}/grade`);
      if (gradeLoadFor.current !== submissionId || !grade) return; // another panel was opened meanwhile
      const comments = grade.comments ?? "";
      setGradingComments(comments);
      const lockedRubric = assignmentRubricFor(submissionId);
      if (lockedRubric !== null && grade.rubric_id !== lockedRubric) {
        // Graded before the assignment's rubric changed: those marks belong to
        // other criteria, so the marks start blank.
        setGradingBaseline(gradingSnapshot("criteria", {}, "", comments));
        setSavedGradeNote(
          `The saved grade (${grade.total_score}) used a different rubric than this assignment now uses. ` +
            "Enter the marks again with the rubric below.",
        );
        return;
      }
      if (rubrics.some((r) => r.id === grade.rubric_id)) setGradingRubricId(grade.rubric_id);
      // A grade saved with "Final mark only" has no per-criterion marks.
      if (Object.keys(grade.criterion_scores).length === 0) {
        setGradingMode("final");
        setFinalMark(String(grade.total_score));
        setGradingBaseline(gradingSnapshot("final", {}, String(grade.total_score), comments));
      } else {
        const scores = Object.fromEntries(
          Object.entries(grade.criterion_scores).map(([name, score]) => [name, String(score)]),
        );
        setCriterionScores(scores);
        setGradingBaseline(gradingSnapshot("criteria", scores, "", comments));
      }
      setSavedGradeNote(
        `Showing the saved grade (${grade.total_score})` +
          (grade.graded_by ? ` by ${grade.graded_by}` : "") +
          `, ${formatDateTime(grade.graded_at)}. Saving creates a new grade.`,
      );
    } catch (err) {
      if (gradeLoadFor.current === submissionId) {
        setGradingMsg({
          text: `Could not load the saved grade: ${err instanceof Error ? err.message : err}`,
          kind: "error",
        });
      }
    } finally {
      if (gradeLoadFor.current === submissionId) setLoadingSavedGrade(false);
    }
  }

  const gradingRubric = rubrics.find((r) => r.id === gradingRubricId) || null;
  const scoreErrors: Record<string, string> = {};
  for (const c of gradingRubric?.criteria ?? []) {
    const error = scoreError(criterionScores[c.name], c.max_points);
    if (error) scoreErrors[c.name] = error;
  }
  // Running total of the valid marks only; an invalid mark adds nothing until it is fixed.
  const criteriaTotal = (gradingRubric?.criteria ?? []).reduce(
    (sum, c) => sum + (scoreErrors[c.name] ? 0 : Number(criterionScores[c.name] || 0)),
    0,
  );
  const finalMarkError = scoreError(finalMark, gradingRubric?.max_total ?? 0);
  const cannotSave =
    loadingSavedGrade ||
    (gradingMode === "final" ? finalMark.trim() === "" || finalMarkError !== null : Object.keys(scoreErrors).length > 0);
  // Empty boxes are saved as 0, and the grey "max N" hint can make them look filled.
  const emptyCriteria =
    gradingMode === "criteria"
      ? (gradingRubric?.criteria ?? []).filter((c) => (criterionScores[c.name] ?? "").trim() === "")
      : [];

  const gradingDirty =
    gradingSubmissionId !== null &&
    gradingSnapshot(gradingMode, criterionScores, finalMark, gradingComments) !== gradingBaseline;

  function closeGradingPanel() {
    setGradingSubmissionId(null);
    gradeLoadFor.current = null;
  }

  /** Runs `action` (which replaces or closes the grading form) straight away, or
   * after the instructor confirms when the form has unsaved marks or comments. */
  function confirmDiscardThen(action: () => void) {
    if (!gradingDirty) return action();
    setGradingConfirm({
      title: "Discard unsaved marks?",
      message: `The marks or comments you entered for ${studentLabel(gradingSubmissionId)} have not been saved.`,
      confirmLabel: "Discard",
      onConfirm: () => {
        setGradingConfirm(null);
        action();
      },
    });
  }

  const cannotSaveReason = !cannotSave
    ? undefined
    : loadingSavedGrade
      ? "Loading the saved grade..."
      : gradingMode === "final" && finalMark.trim() === ""
        ? "Enter the final mark first"
        : "Fix the marks shown in red first";

  // "Save & next": the next ungraded submission after this one, in the table's
  // order (wrapping round to the top); null when every other one is graded.
  const nextUngradedId = (() => {
    const i = shownSubmissions.findIndex((s) => s.id === gradingSubmissionId);
    if (i === -1) return null;
    const after = [...shownSubmissions.slice(i + 1), ...shownSubmissions.slice(0, i)];
    return after.find((s) => s.status !== "graded")?.id ?? null;
  })();

  function handleSaveGrade(nextId: number | null = null) {
    if (cannotSave) return;
    const save = async () => {
      const savedFor = gradingSubmissionId;
      if (!(await saveGrade()) || nextId === null || savedFor === null) return;
      openGradingPanel(nextId);
      setGradingMsg({ text: `Grade saved for ${studentLabel(savedFor)}.`, kind: "success" });
    };
    if (emptyCriteria.length === 0) return save();
    setShowEmptyMarks(true);
    const n = emptyCriteria.length;
    setGradingConfirm({
      title: "Save with empty marks?",
      message:
        `${n} ${n === 1 ? "criterion is" : "criteria are"} empty and will be saved as 0:\n` +
        emptyCriteria.map((c) => `• ${c.name} (max ${c.max_points})`).join("\n"),
      confirmLabel: "Save anyway",
      onConfirm: async () => {
        setGradingConfirm(null);
        await save();
      },
    });
  }

  /** Saves the form; true when the grade was saved. */
  async function saveGrade(): Promise<boolean> {
    if (gradingSubmissionId === null || gradingRubricId === null || cannotSave) return false;
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
      setGradingBaseline(gradingSnapshot(gradingMode, criterionScores, finalMark, gradingComments));
      setSavedGradeNote(null); // it described the grade this one replaces
      if (subjectId !== null) await loadSubmissions(subjectId);
      return true;
    } catch (err) {
      setGradingMsg({ text: `Failed to save grade: ${err instanceof Error ? err.message : err}`, kind: "error" });
      return false;
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

          {/* Student self-check history */}
          <SelfCheckHistoryPanel assignments={assignments} />

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

            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Filter by status">
              <span className="font-semibold">Show</span>
              {STATUS_FILTERS.map((f) => {
                const count = f.status ? shownSubmissions.filter((s) => s.status === f.status).length : shownSubmissions.length;
                const active = statusFilter === f.status;
                return (
                  <button
                    key={f.label}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setStatusFilter(f.status);
                      setFilesOpenFor(null);
                    }}
                    className={`rounded-md px-3 py-1 text-xs font-semibold ${
                      active ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                    }`}
                  >
                    {f.label} ({count})
                  </button>
                );
              })}
            </div>

            {/* Scrolls sideways inside the page on narrow screens instead of widening it. */}
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
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
                  {tableSubmissions.length === 0 && (
                    <tr>
                      <td colSpan={7} className="border border-gray-200 px-3 py-3 text-center text-gray-500">
                        {shownSubmissions.length > 0
                          ? `No ${statusFilter === "graded" ? "graded" : "ungraded"} submissions here.`
                          : submissionFilter === "all"
                            ? "No submissions yet."
                            : "No submissions for this assignment yet."}
                      </td>
                    </tr>
                  )}
                  {tableSubmissions.map((s) => (
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
                            onClick={() => confirmDiscardThen(() => openGradingPanel(s.id))}
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
            </div>
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
              <RubricField
                id="autoeval-rubric"
                rubrics={rubrics}
                value={autoevalRubricId}
                locked={assignmentRubricFor(autoevalSubmissionId) !== null}
                onChange={setAutoevalRubricId}
              />
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
              {loadingSavedGrade && <p className="mt-1 text-sm text-gray-500">Loading the saved grade...</p>}
              {savedGradeNote && (
                <p className="mt-2 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700">{savedGradeNote}</p>
              )}
              <RubricField
                id="grading-rubric"
                rubrics={rubrics}
                value={gradingRubricId}
                locked={assignmentRubricFor(gradingSubmissionId) !== null}
                onChange={setGradingRubricId}
              />

              {/* A plain div, not <fieldset>: browsers draw a fieldset's border through its legend. */}
              <div
                role="radiogroup"
                aria-labelledby="grading-mode-label"
                className="mb-3 rounded-md border border-blue-100 bg-blue-50 p-3"
              >
                <p id="grading-mode-label" className="text-sm font-semibold">
                  How to grade
                </p>
                <div className="mt-2 flex flex-wrap gap-4 text-sm">
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
                        placeholder={`max ${gradingRubric?.max_total ?? 0}`}
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
              </div>

              {gradingMode === "criteria" && (
                <>
                  <div className="space-y-2">
                    {gradingRubric?.criteria.map((c) => {
                      const error = scoreErrors[c.name];
                      const empty = showEmptyMarks && (criterionScores[c.name] ?? "").trim() === "";
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
                              placeholder={`max ${c.max_points}`}
                              aria-invalid={Boolean(error)}
                              aria-describedby={error || empty ? `${inputId}-error` : undefined}
                              onChange={(e) => setCriterionScores((prev) => ({ ...prev, [c.name]: e.target.value }))}
                              className={`w-full rounded-md border px-2 py-1.5 text-sm ${
                                error
                                  ? "border-red-500 bg-red-50"
                                  : empty
                                    ? "border-amber-500 bg-amber-50"
                                    : "border-gray-300"
                              }`}
                            />
                            {error ? (
                              <p id={`${inputId}-error`} className="mt-1 text-xs text-red-700">
                                {error}
                              </p>
                            ) : (
                              empty && (
                                <p id={`${inputId}-error`} className="mt-1 text-xs text-amber-700">
                                  Empty: saved as 0.
                                </p>
                              )
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <p className="mt-3 text-sm font-semibold">
                    Final mark:{" "}
                    {criteriaTotal} / {gradingRubric?.max_total ?? 0}
                    {Object.keys(scoreErrors).length > 0 && (
                      <span className="ml-2 text-xs font-normal text-red-700">Marks shown in red are not counted.</span>
                    )}
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

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => handleSaveGrade()}
                  disabled={cannotSave}
                  title={cannotSaveReason}
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Save grade
                </button>
                {nextUngradedId !== null && (
                  <button
                    type="button"
                    onClick={() => handleSaveGrade(nextUngradedId)}
                    disabled={cannotSave}
                    title={cannotSaveReason ?? `Save, then grade ${studentLabel(nextUngradedId)}`}
                    className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Save &amp; next
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => confirmDiscardThen(closeGradingPanel)}
                  className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
                >
                  Cancel
                </button>
              </div>
              <Message state={gradingMsg} />
              <ConfirmDialog request={gradingConfirm} onCancel={() => setGradingConfirm(null)} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
