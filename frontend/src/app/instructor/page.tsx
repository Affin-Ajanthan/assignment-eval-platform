"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  apiFetch,
  AutoEvaluation,
  Criterion,
  Rubric,
  SimilarityCheckResult,
  Submission,
} from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import Message, { MessageState } from "@/components/Message";

type CriterionRow = { name: string; description: string; maxPoints: string };

function emptyCriterionRow(): CriterionRow {
  return { name: "", description: "", maxPoints: "" };
}

export default function InstructorPage() {
  const { user, ready } = useRequireRole("instructor");

  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);

  // Rubric creation
  const [rubricName, setRubricName] = useState("");
  const [criteriaRows, setCriteriaRows] = useState<CriterionRow[]>([emptyCriterionRow()]);
  const [rubricMsg, setRubricMsg] = useState<MessageState>(null);

  // Similarity check
  const [similarityAssignment, setSimilarityAssignment] = useState("");
  const [similarityResult, setSimilarityResult] = useState<SimilarityCheckResult | null>(null);
  const [similarityMsg, setSimilarityMsg] = useState<MessageState>(null);

  // Auto-evaluation panel
  const [autoevalSubmissionId, setAutoevalSubmissionId] = useState<number | null>(null);
  const [autoevalRubricId, setAutoevalRubricId] = useState<number | null>(null);
  const [autoevalResult, setAutoevalResult] = useState<AutoEvaluation | null>(null);
  const [autoevalMsg, setAutoevalMsg] = useState<MessageState>(null);
  const [autoevalRunning, setAutoevalRunning] = useState(false);

  // Grading panel
  const [gradingSubmissionId, setGradingSubmissionId] = useState<number | null>(null);
  const [gradingRubricId, setGradingRubricId] = useState<number | null>(null);
  const [criterionScores, setCriterionScores] = useState<Record<string, string>>({});
  const [gradingComments, setGradingComments] = useState("");
  const [gradingMsg, setGradingMsg] = useState<MessageState>(null);

  const loadRubrics = useCallback(async (forSubject: number) => {
    setRubrics(await apiFetch<Rubric[]>(`/rubrics?subject_id=${forSubject}`));
  }, []);

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
    loadSubmissions(subjectId);
  }, [subjectId, loadRubrics, loadSubmissions]);

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

  // ---- Rubric creation ----

  function updateCriterionRow(index: number, patch: Partial<CriterionRow>) {
    setCriteriaRows((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }
  function removeCriterionRow(index: number) {
    setCriteriaRows((rows) => rows.filter((_, i) => i !== index));
  }

  async function handleSaveRubric(e: FormEvent) {
    e.preventDefault();
    setRubricMsg(null);
    if (subjectId === null) {
      setRubricMsg({ text: "Pick a subject first.", kind: "error" });
      return;
    }
    const criteria: Criterion[] = criteriaRows
      .map((row) => ({
        name: row.name.trim(),
        description: row.description.trim(),
        max_points: parseFloat(row.maxPoints),
      }))
      .filter((c) => c.name && !Number.isNaN(c.max_points));

    if (criteria.length === 0) {
      setRubricMsg({ text: "Add at least one named criterion with a max point value.", kind: "error" });
      return;
    }

    try {
      await apiFetch("/rubrics", { method: "POST", json: { name: rubricName, subject_id: subjectId, criteria } });
      setRubricMsg({ text: "Rubric saved.", kind: "success" });
      setRubricName("");
      setCriteriaRows([emptyCriterionRow()]);
      await loadRubrics(subjectId);
    } catch (err) {
      setRubricMsg({ text: `Failed to save rubric: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
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
    try {
      const result = await apiFetch<SimilarityCheckResult>(
        `/subjects/${subjectId}/assignments/${encodeURIComponent(similarityAssignment)}/check-similarity`,
        { method: "POST" }
      );
      setSimilarityResult(result);
      const flaggedCount = result.pairs.filter((p) => p.flagged).length;
      setSimilarityMsg({
        text: `Compared ${result.compared} submissions -- ${flaggedCount} pair(s) flagged for review.`,
        kind: flaggedCount ? "error" : "success",
      });
    } catch (err) {
      setSimilarityMsg({ text: `Similarity check failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }

  // ---- Auto-evaluation ----

  function openAutoevalPanel(submissionId: number) {
    setAutoevalSubmissionId(submissionId);
    setAutoevalResult(null);
    setAutoevalMsg(null);
    setAutoevalRubricId(rubrics[0]?.id ?? null);
  }

  async function handleRunAutoeval() {
    if (autoevalSubmissionId === null || autoevalRubricId === null) return;
    setAutoevalMsg(null);
    setAutoevalRunning(true);
    try {
      const result = await apiFetch<AutoEvaluation>(`/submissions/${autoevalSubmissionId}/auto-evaluate`, {
        method: "POST",
        json: { rubric_id: autoevalRubricId },
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
    setGradingRubricId(rubricId ?? rubrics[0]?.id ?? null);
    setCriterionScores(prefill);
  }

  const gradingRubric = rubrics.find((r) => r.id === gradingRubricId) || null;

  async function handleSaveGrade() {
    if (gradingSubmissionId === null || gradingRubricId === null) return;
    setGradingMsg(null);
    const scores: Record<string, number> = {};
    for (const c of gradingRubric?.criteria ?? []) {
      scores[c.name] = parseFloat(criterionScores[c.name] || "0");
    }
    try {
      await apiFetch(`/submissions/${gradingSubmissionId}/grade`, {
        method: "POST",
        json: { rubric_id: gradingRubricId, criterion_scores: scores, comments: gradingComments },
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
        Upload a rubric, run the automated evaluator, then grade manually or accept its scores as a starting
        point -- you always have the final say.
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
          {/* Rubrics */}
          <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold">Rubrics</h2>
            <form onSubmit={handleSaveRubric} className="mt-3">
              <label className="block text-sm font-semibold" htmlFor="rubric_name">
                Rubric name
              </label>
              <input
                id="rubric_name"
                required
                value={rubricName}
                onChange={(e) => setRubricName(e.target.value)}
                placeholder="Assignment 2 rubric"
                className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />

              <label className="block text-sm font-semibold">Criteria</label>
              <div className="mt-1 space-y-2">
                {criteriaRows.map((row, i) => (
                  <div key={i} data-testid="criterion-row" className="flex items-center gap-2">
                    <input
                      placeholder="Criterion name"
                      value={row.name}
                      onChange={(e) => updateCriterionRow(i, { name: e.target.value })}
                      className="w-1/3 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                    />
                    <input
                      placeholder="Description"
                      value={row.description}
                      onChange={(e) => updateCriterionRow(i, { description: e.target.value })}
                      className="flex-1 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                    />
                    <input
                      type="number"
                      min={0}
                      step={0.5}
                      placeholder="Max pts"
                      value={row.maxPoints}
                      onChange={(e) => updateCriterionRow(i, { maxPoints: e.target.value })}
                      className="w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => removeCriterionRow(i)}
                      className="rounded-md bg-gray-600 px-2 py-1.5 text-xs font-semibold text-white hover:bg-gray-700"
                    >
                      x
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setCriteriaRows((rows) => [...rows, emptyCriterionRow()])}
                className="mt-2 rounded-md bg-gray-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
              >
                + Add criterion
              </button>
              <div>
                <button className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
                  Save rubric
                </button>
              </div>
              <Message state={rubricMsg} />
            </form>

            <h3 className="mt-5 text-sm font-bold uppercase tracking-wide text-gray-500">
              Existing rubrics for this subject
            </h3>
            <table className="mt-2 w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="border border-gray-200 px-3 py-1.5">Name</th>
                  <th className="border border-gray-200 px-3 py-1.5">Criteria</th>
                  <th className="border border-gray-200 px-3 py-1.5">Max total</th>
                </tr>
              </thead>
              <tbody>
                {rubrics.map((r) => (
                  <tr key={r.id}>
                    <td className="border border-gray-200 px-3 py-1.5">{r.name}</td>
                    <td className="border border-gray-200 px-3 py-1.5">{r.criteria.map((c) => c.name).join(", ")}</td>
                    <td className="border border-gray-200 px-3 py-1.5">{r.max_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Similarity check */}
          <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold">Similarity check</h2>
            <p className="mt-1 text-sm text-gray-600">
              Compares every code submission for one assignment pairwise and flags likely copies.
            </p>
            <label className="mt-3 block text-sm font-semibold" htmlFor="similarity-assignment">
              Assignment
            </label>
            <select
              id="similarity-assignment"
              value={similarityAssignment}
              onChange={(e) => setSimilarityAssignment(e.target.value)}
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
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Check similarity
            </button>
            <Message state={similarityMsg} />

            {similarityResult && similarityResult.pairs.length > 0 && (
              <table className="mt-4 w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-left">
                    <th className="border border-gray-200 px-3 py-1.5">Student A</th>
                    <th className="border border-gray-200 px-3 py-1.5">Student B</th>
                    <th className="border border-gray-200 px-3 py-1.5">Jaccard</th>
                    <th className="border border-gray-200 px-3 py-1.5">Containment</th>
                    <th className="border border-gray-200 px-3 py-1.5">Flag</th>
                  </tr>
                </thead>
                <tbody>
                  {similarityResult.pairs.map((p, i) => (
                    <tr key={i} className={p.flagged ? "bg-red-50" : undefined}>
                      <td className="border border-gray-200 px-3 py-1.5">{studentLabel(p.submission_a_id)}</td>
                      <td className="border border-gray-200 px-3 py-1.5">{studentLabel(p.submission_b_id)}</td>
                      <td className="border border-gray-200 px-3 py-1.5">{(p.jaccard * 100).toFixed(0)}%</td>
                      <td className="border border-gray-200 px-3 py-1.5">{(p.containment * 100).toFixed(0)}%</td>
                      <td className="border border-gray-200 px-3 py-1.5">{p.flagged ? "⚑ review" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* Submissions */}
          <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold">Submissions for this subject</h2>
            <table className="mt-2 w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left">
                  <th className="border border-gray-200 px-3 py-1.5">Student</th>
                  <th className="border border-gray-200 px-3 py-1.5">Assignment</th>
                  <th className="border border-gray-200 px-3 py-1.5">Submitted</th>
                  <th className="border border-gray-200 px-3 py-1.5">Status</th>
                  <th className="border border-gray-200 px-3 py-1.5"></th>
                </tr>
              </thead>
              <tbody>
                {submissions.map((s) => (
                  <tr key={s.id}>
                    <td className="border border-gray-200 px-3 py-1.5">
                      {s.student_name}
                      <br />
                      <small className="text-gray-500">{s.student_email}</small>
                    </td>
                    <td className="border border-gray-200 px-3 py-1.5">{s.assignment_name}</td>
                    <td className="border border-gray-200 px-3 py-1.5">{new Date(s.submitted_at).toLocaleString()}</td>
                    <td className="border border-gray-200 px-3 py-1.5">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          s.status === "graded" ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"
                        }`}
                      >
                        {s.status}
                      </span>
                    </td>
                    <td className="space-x-1 border border-gray-200 px-3 py-1.5">
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
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Auto-evaluation panel */}
          {autoevalSubmissionId !== null && (
            <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
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
              <div className="space-x-2">
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
                    {autoevalResult.grader} grader)
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
            <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
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
                    {r.name}
                  </option>
                ))}
              </select>

              <div className="space-y-2">
                {gradingRubric?.criteria.map((c) => (
                  <div key={c.name} className="flex items-center gap-3">
                    <label className="flex-1 text-sm">
                      {c.name}{" "}
                      <small className="text-gray-500">
                        ({c.description || "no description"}, max {c.max_points})
                      </small>
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={c.max_points}
                      step={0.5}
                      value={criterionScores[c.name] ?? ""}
                      onChange={(e) => setCriterionScores((prev) => ({ ...prev, [c.name]: e.target.value }))}
                      className="w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                    />
                  </div>
                ))}
              </div>

              <label className="mt-3 block text-sm font-semibold" htmlFor="grading-comments">
                Comments
              </label>
              <textarea
                id="grading-comments"
                value={gradingComments}
                onChange={(e) => setGradingComments(e.target.value)}
                placeholder="Feedback for the student"
                className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                rows={3}
              />

              <div className="space-x-2">
                <button
                  type="button"
                  onClick={handleSaveGrade}
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
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
