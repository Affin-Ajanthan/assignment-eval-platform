"use client";

import { FormEvent, useState } from "react";
import { apiFetch, Assignment, AssignmentKind, AssignmentStatus, Rubric, SubmissionType } from "@/lib/api";
import { combineLocal, formatDateTime, splitLocal } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import ReportTemplateControl from "@/components/instructor/ReportTemplateControl";
import Badge from "@/components/Badge";
import { CODE_LANGUAGES, CodeLanguageId, languageNames } from "@/lib/codeLanguages";
import QuestionsEditor, {
  emptyQuestionRow,
  QuestionRow,
  questionRowsPayload,
  toQuestionRows,
} from "@/components/instructor/QuestionsEditor";

const STATUS_STYLE: Record<AssignmentStatus, { text: string; cls: string }> = {
  upcoming: { text: "Not yet open", cls: "bg-gray-100 text-gray-700" },
  open: { text: "Open", cls: "bg-green-50 text-green-800" },
  closed: { text: "Closed", cls: "bg-yellow-50 text-yellow-800" },
};

type FormState = {
  kind: AssignmentKind | null; // null: not chosen yet (creating): the form shows the choice first
  name: string;
  description: string;
  fromDate: string;
  fromTime: string;
  dueDate: string;
  dueTime: string;
  rubricId: string; // "" = no rubric
  types: SubmissionType[];
  starterCode: string; // "" = no starter code
  starterFilename: string;
  languages: CodeLanguageId[]; // [] = any supported language
  selfSimilarity: boolean; // students may run similarity self-checks before the deadline
  selfAi: boolean; // students may run AI-content self-checks before the deadline
  ignoreCommon: boolean; // code similarity ignores code most of the class shares
  releaseDate: string; // "" (with releaseTime "") = show each mark as soon as it is saved
  releaseTime: string;
  questions: QuestionRow[]; // only used by a code challenge: at least one question, each with its test cases
  testMainFile: string; // the file the tests run (a challenge with one question); "" = picked automatically
};

const TYPE_OPTIONS: { value: SubmissionType; label: string; hint: string }[] = [
  { value: "code", label: "Code", hint: "a source file or .zip" },
  { value: "report", label: "Report", hint: "PDF or DOCX" },
  { value: "video", label: "Video", hint: "presentation video" },
];

const typeLabel = (t: SubmissionType) => TYPE_OPTIONS.find((o) => o.value === t)?.label ?? t;

const KIND_OPTIONS: { value: AssignmentKind; title: string; text: string }[] = [
  {
    value: "submission",
    title: "Submission",
    text: "Students upload their work: code, a report and/or a video. You grade it with a rubric, with the automated evaluation as a second opinion.",
  },
  {
    value: "code_challenge",
    title: "Code challenge",
    text: "HackerRank style: students submit code only, for one question or several. It is run against your test cases, and the marks come from the tests passed.",
  },
];
const kindTitle = (k: AssignmentKind) => KIND_OPTIONS.find((o) => o.value === k)?.title ?? k;

function toggleType(current: SubmissionType[], t: SubmissionType): SubmissionType[] {
  return current.includes(t) ? current.filter((x) => x !== t) : [...current, t];
}

const EMPTY: FormState = {
  kind: null,
  name: "",
  description: "",
  fromDate: "",
  fromTime: "",
  dueDate: "",
  dueTime: "",
  rubricId: "",
  types: ["code", "report", "video"],
  starterCode: "",
  starterFilename: "",
  languages: [],
  selfSimilarity: true,
  selfAi: true,
  ignoreCommon: true,
  releaseDate: "",
  releaseTime: "",
  questions: [emptyQuestionRow()],
  testMainFile: "",
};

// Starter code is one source file (not a notebook): the backend's CODE_EXTENSIONS (app/common.py).
const CODE_EXTENSIONS = [...new Set(CODE_LANGUAGES.flatMap((l) => l.extensions))].filter((e) => e !== ".ipynb");

const input = "mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm";

export default function AssignmentsSection({
  subjectId,
  assignments,
  rubrics,
  onChanged,
}: {
  subjectId: number;
  assignments: Assignment[];
  rubrics: Rubric[];
  onChanged: () => Promise<void>;
}) {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function startEdit(a: Assignment) {
    const from = splitLocal(a.available_from);
    const due = splitLocal(a.deadline);
    const release = a.marks_release_at ? splitLocal(a.marks_release_at) : { date: "", time: "" };
    setEditingId(a.id);
    setMsg(null);
    setForm({
      kind: a.assignment_type ?? "submission",
      name: a.name,
      description: a.description,
      fromDate: from.date,
      fromTime: from.time,
      dueDate: due.date,
      dueTime: due.time,
      rubricId: a.rubric_id ? String(a.rubric_id) : "",
      types: a.submission_types,
      starterCode: a.starter_code,
      starterFilename: a.starter_code_filename,
      languages: a.code_languages ?? [],
      selfSimilarity: a.student_similarity_check ?? true,
      selfAi: a.student_ai_check ?? true,
      ignoreCommon: a.ignore_common_code ?? true,
      releaseDate: release.date,
      releaseTime: release.time,
      questions: toQuestionRows(a),
      testMainFile: a.test_main_file ?? "",
    });
  }

  /** The first step of creating: a code challenge accepts code only, a submission starts with every type. */
  function chooseKind(kind: AssignmentKind) {
    setForm((f) => ({ ...f, kind, types: kind === "code_challenge" ? ["code"] : ["code", "report", "video"] }));
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY);
    setMsg(null);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (form.kind === null) return setMsg({ text: "Choose the assignment type first.", kind: "error" });
    const challenge = form.kind === "code_challenge";
    // Same checks the API enforces, so the instructor gets a clear message early.
    if (!form.name.trim()) return setMsg({ text: "Assignment name is required.", kind: "error" });
    const from = combineLocal(form.fromDate, form.fromTime);
    const due = combineLocal(form.dueDate, form.dueTime);
    if (!from) return setMsg({ text: "Enter a valid 'available from' date and time.", kind: "error" });
    if (!due) return setMsg({ text: "Enter a valid submission deadline date and time.", kind: "error" });
    if (due <= from) {
      return setMsg({ text: "The submission deadline must be later than the available-from date and time.", kind: "error" });
    }
    const hasStarter = form.starterCode.trim() !== "";
    const starterExt = form.starterFilename.trim().toLowerCase().match(/\.[a-z0-9]+$/)?.[0] ?? "";
    if (hasStarter && !CODE_EXTENSIONS.includes(starterExt)) {
      return setMsg({
        text: `Give the starter code a file name with a code extension (${CODE_EXTENSIONS.join(", ")}), e.g. starter.py.`,
        kind: "error",
      });
    }

    if (form.types.length === 0) return setMsg({ text: "Choose at least one submission type.", kind: "error" });
    // Both empty = no release date (marks show as soon as they are saved).
    const releaseSet = form.releaseDate !== "" || form.releaseTime !== "";
    const release = releaseSet ? combineLocal(form.releaseDate, form.releaseTime) : null;
    if (releaseSet && !release) {
      return setMsg({ text: "Enter both a date and a time to release the marks, or leave both empty.", kind: "error" });
    }
    // Questions and test cases belong to code challenges only, and every question needs at least one test case.
    const questionsPayload = challenge ? questionRowsPayload(form.questions) : { questions: [], tests: [], error: null };
    if (questionsPayload.error !== null) return setMsg({ text: questionsPayload.error, kind: "error" });
    const body = {
      name: form.name.trim(),
      description: form.description,
      available_from: from.toISOString(),
      deadline: due.toISOString(),
      // A code challenge has no rubric (null also detaches one from an older challenge).
      rubric_id: !challenge && form.rubricId ? parseInt(form.rubricId, 10) : null,
      assignment_type: form.kind,
      // A code challenge is code only: set when creating, left alone when editing.
      submission_types: challenge ? (editingId === null ? ["code"] : undefined) : form.types,
      starter_code: hasStarter ? form.starterCode : "",
      starter_code_filename: hasStarter ? form.starterFilename.trim() : "",
      // Only meaningful when students submit code; otherwise no restriction.
      code_languages: form.types.includes("code") ? form.languages : [],
      student_similarity_check: form.selfSimilarity,
      student_ai_check: form.selfAi,
      ignore_common_code: form.ignoreCommon,
      // null also clears an earlier date, releasing the marks straight away.
      marks_release_at: release ? release.toISOString() : null,
      test_cases: questionsPayload.tests,
      questions: questionsPayload.questions,
      // Only a challenge with one question runs a named file; with several, each question has its own file.
      test_main_file: challenge && form.questions.length === 1 ? form.testMainFile.trim() : "",
    };
    setSaving(true);
    try {
      if (editingId === null) {
        await apiFetch("/assignments", { method: "POST", json: { ...body, subject_id: subjectId } });
        setMsg({ text: "Assignment saved.", kind: "success" });
      } else {
        await apiFetch(`/assignments/${editingId}`, { method: "PUT", json: body });
        setMsg({ text: "Assignment updated.", kind: "success" });
      }
      setEditingId(null);
      setForm(EMPTY);
      await onChanged();
    } catch (err) {
      setMsg({ text: `Failed to save assignment: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  function askDelete(a: Assignment) {
    setConfirm({
      title: `Delete "${a.name}"?`,
      message:
        "Are you sure you want to delete this assignment? Students will no longer see it or be able to submit to it." +
        (a.submission_count
          ? `\n\nIts ${a.submission_count} existing submission(s) and any grades are kept as records under the name "${a.name}".`
          : ""),
      onConfirm: async () => {
        setConfirmBusy(true);
        try {
          await apiFetch(`/assignments/${a.id}`, { method: "DELETE" });
          if (editingId === a.id) cancelEdit();
          setMsg({ text: `Assignment "${a.name}" deleted.`, kind: "success" });
          await onChanged();
        } catch (err) {
          setMsg({ text: `Failed to delete assignment: ${err instanceof Error ? err.message : err}`, kind: "error" });
        } finally {
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  const selectedRubric = rubrics.find((r) => String(r.id) === form.rubricId);
  // Once any student has submitted, the accepted types are fixed (the API refuses changes).
  const typesLocked = (assignments.find((a) => a.id === editingId)?.submission_count ?? 0) > 0;

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Assignments</h2>
      <p className="mt-1 text-sm text-gray-600">
        Enter the details, set when submissions open and close, and choose the rubric used to grade it (create rubrics
        below).
      </p>

      <form onSubmit={handleSave} className="mt-3" noValidate>
        <h3 className="text-sm font-bold">{editingId === null ? "Create assignment" : "Edit assignment"}</h3>

        {form.kind === null ? (
          <div className="mt-2" data-testid="assignment-type-chooser">
            <p className="text-sm text-gray-600">What kind of assignment is this?</p>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              {KIND_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => chooseKind(o.value)}
                  className="rounded-md border border-gray-300 p-4 text-left hover:border-blue-500 hover:bg-blue-50"
                >
                  <span className="block font-bold">{o.title}</span>
                  <span className="mt-1 block text-sm text-gray-600">{o.text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
        <p className="mt-2 text-sm" data-testid="assignment-type">
          <span className="font-semibold">Type:</span> {kindTitle(form.kind)}{" "}
          {editingId === null ? (
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, kind: null }))}
              className="ml-1 text-xs font-semibold text-blue-700 hover:underline"
            >
              Change
            </button>
          ) : (
            <span className="text-xs text-gray-500">(fixed once created)</span>
          )}
        </p>
        <label className="mt-2 block text-sm font-semibold" htmlFor="assignment-name">
          Assignment name
        </label>
        <input
          id="assignment-name"
          required
          maxLength={200}
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Assignment 1"
          className={input}
        />

        <label className="mt-3 block text-sm font-semibold" htmlFor="assignment-description">
          Description / instructions
        </label>
        <textarea
          id="assignment-description"
          rows={4}
          maxLength={10000}
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          placeholder="Enter assignment instructions here..."
          className={input}
        />

        {form.kind === "submission" && (
        <fieldset className="mt-3">
          <legend className="text-sm font-semibold">Students can submit</legend>
          <div className="mt-1 flex flex-wrap gap-4">
            {TYPE_OPTIONS.map((t) => (
              <label key={t.value} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.types.includes(t.value)}
                  disabled={typesLocked}
                  onChange={() => set("types", toggleType(form.types, t.value))}
                />
                {t.label} <span className="text-xs text-gray-500">({t.hint})</span>
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {typesLocked
              ? "Locked: students have already submitted to this assignment."
              : "Students can upload only the kinds you tick. Pick at least one."}
          </p>
        </fieldset>
        )}

        {form.types.includes("code") && (
          <fieldset className="mt-3">
            <legend className="text-sm font-semibold">
              Programming language <span className="font-normal text-gray-500">(optional)</span>
            </legend>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {CODE_LANGUAGES.map((l) => (
                <label key={l.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.languages.includes(l.id)}
                    disabled={typesLocked}
                    onChange={() =>
                      set(
                        "languages",
                        form.languages.includes(l.id)
                          ? form.languages.filter((x) => x !== l.id)
                          : [...form.languages, l.id],
                      )
                    }
                  />
                  {l.name}
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {typesLocked
                ? "Locked: students have already submitted to this assignment."
                : form.languages.length
                  ? `Students must submit code in ${languageNames(form.languages)}; code in any other language is refused.`
                  : "None ticked: students can submit code in any supported language."}
            </p>
          </fieldset>
        )}

        {form.kind === "code_challenge" && (
          <>
            <QuestionsEditor rows={form.questions} onChange={(rows) => set("questions", rows)} locked={typesLocked} />
            {form.questions.length === 1 && form.questions[0].tests.length > 0 && (
              <div className="mt-3">
                <label className="block text-sm font-semibold" htmlFor="test-main-file">
                  Main file to run <span className="font-normal text-gray-500">(optional)</span>
                </label>
                <input
                  id="test-main-file"
                  value={form.testMainFile}
                  maxLength={200}
                  placeholder="student_management.rb"
                  onChange={(e) => set("testMainFile", e.target.value)}
                  className={input}
                />
                <p className="mt-1 text-xs text-gray-500">
                  The file name (or path) the tests run: Python (.py) and Ruby (.rb) only. Empty: the only Python or
                  Ruby file in the submission, or one named main, app, run, program or index. Code that students type
                  in the editor is always saved and run as main.py or main.rb, so leave this empty for it.
                </p>
              </div>
            )}
          </>
        )}

        {form.types.includes("code") && (
          <fieldset className="mt-3">
            <legend className="text-sm font-semibold">Code similarity</legend>
            <label className="mt-1 flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={form.ignoreCommon}
                onChange={(e) => set("ignoreCommon", e.target.checked)}
              />
              <span>
                Ignore code most of the class shares <span className="text-xs text-gray-500">(recommended)</span>
              </span>
            </label>
            <p className="mt-1 text-xs text-gray-500">
              Code patterns found in more than half of the submissions (menu loops, input helpers, file saving) are
              left out before comparing, so honest solutions to the same task don&apos;t look alike. Copies still
              match. Applies to your Similarity Code Check and to students&apos; self-checks; you can change it at any
              time.
            </p>
          </fieldset>
        )}

        <fieldset className="mt-3">
          <legend className="text-sm font-semibold">Student self-checks before the deadline</legend>
          <div className="mt-1 flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.selfSimilarity}
                onChange={(e) => set("selfSimilarity", e.target.checked)}
              />
              Similarity check <span className="text-xs text-gray-500">(code and report)</span>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.selfAi} onChange={(e) => set("selfAi", e.target.checked)} />
              AI-content detection
            </label>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Students see Low / Moderate / High bands and their own matching passages, never other students&apos; work.
            You can change these at any time, even after students have submitted.
          </p>
        </fieldset>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <fieldset>
            <legend className="text-sm font-semibold">Available from</legend>
            <div className="flex gap-2">
              <input
                type="date"
                aria-label="Available from date"
                value={form.fromDate}
                onChange={(e) => set("fromDate", e.target.value)}
                className={input}
              />
              <input
                type="time"
                aria-label="Available from time"
                value={form.fromTime}
                onChange={(e) => set("fromTime", e.target.value)}
                className={input}
              />
            </div>
          </fieldset>
          <fieldset>
            <legend className="text-sm font-semibold">Submission deadline</legend>
            <div className="flex gap-2">
              <input
                type="date"
                aria-label="Deadline date"
                value={form.dueDate}
                onChange={(e) => set("dueDate", e.target.value)}
                className={input}
              />
              <input
                type="time"
                aria-label="Deadline time"
                value={form.dueTime}
                onChange={(e) => set("dueTime", e.target.value)}
                className={input}
              />
            </div>
          </fieldset>
        </div>
        <p className="mt-1 text-xs text-gray-500">Times are in your local time zone.</p>

        <fieldset className="mt-3">
          <legend className="text-sm font-semibold">
            Release marks to students <span className="font-normal text-gray-500">(optional)</span>
          </legend>
          <div className="flex flex-wrap items-center gap-2 sm:max-w-md">
            <input
              type="date"
              aria-label="Marks release date"
              value={form.releaseDate}
              onChange={(e) => set("releaseDate", e.target.value)}
              className={`${input} flex-1`}
            />
            <input
              type="time"
              aria-label="Marks release time"
              value={form.releaseTime}
              onChange={(e) => set("releaseTime", e.target.value)}
              className={`${input} flex-1`}
            />
            {(form.releaseDate || form.releaseTime) && (
              <button
                type="button"
                onClick={() => setForm((f) => ({ ...f, releaseDate: "", releaseTime: "" }))}
                className="mt-1 rounded-md bg-gray-600 px-3 py-2 text-xs font-semibold text-white hover:bg-gray-700"
              >
                Clear
              </button>
            )}
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {form.releaseDate || form.releaseTime
              ? "Students see no marks or feedback until then, so the whole class gets them at the same time."
              : "Empty: students see each mark and their feedback as soon as you save the grade."}
          </p>
        </fieldset>

        {form.kind === "code_challenge" ? (
          <p className="mt-3 text-xs text-gray-600" data-testid="no-rubric-note">
            No rubric: a code challenge is marked by its test cases (the points of the tests passed).
          </p>
        ) : (
          <>
        <label className="mt-3 block text-sm font-semibold" htmlFor="assignment-rubric">
          Rubric
        </label>
        <select
          id="assignment-rubric"
          value={form.rubricId}
          onChange={(e) => set("rubricId", e.target.value)}
          className={input}
        >
          <option value="">— No rubric yet —</option>
          {rubrics.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} ({r.criteria.length} criteria, {r.max_total} pts)
            </option>
          ))}
        </select>
        {selectedRubric && (
          <p className="mt-1 text-xs text-gray-600">
            Criteria: {selectedRubric.criteria.map((c) => `${c.name} (${c.max_points})`).join(", ")} — total{" "}
            {selectedRubric.max_total} points.
          </p>
        )}
          </>
        )}

        <label className="mt-3 block text-sm font-semibold" htmlFor="assignment-starter-code">
          Starter code (optional)
        </label>
        <p className="text-xs text-gray-600">
          Code you give every student. It is left out of the token similarity check, so students aren&apos;t flagged
          for sharing it. Only compared against submitted files with the same extension. Not shown to students.
        </p>
        <input
          aria-label="Starter code file name"
          maxLength={200}
          value={form.starterFilename}
          onChange={(e) => set("starterFilename", e.target.value)}
          placeholder="starter.py"
          className={input}
        />
        <textarea
          id="assignment-starter-code"
          rows={6}
          maxLength={200000}
          value={form.starterCode}
          onChange={(e) => set("starterCode", e.target.value)}
          placeholder="Paste the starter code here..."
          spellCheck={false}
          className={`${input} font-mono`}
        />

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? "Saving..." : editingId === null ? "Save assignment" : "Update assignment"}
          </button>
          {editingId !== null && (
            <button
              type="button"
              onClick={cancelEdit}
              className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
            >
              Cancel edit
            </button>
          )}
        </div>
          </>
        )}
        <Message state={msg} />
      </form>

      <h3 className="mt-6 text-sm font-bold uppercase tracking-wide text-gray-500">Assignments in this subject</h3>
      {assignments.length === 0 ? (
        <p className="mt-2 text-sm text-gray-600">No assignments yet.</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {assignments.map((a) => (
            <li key={a.id} className="rounded-md border border-gray-200 p-4" data-testid="assignment-card">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h4 className="font-bold">{a.name}</h4>
                  {a.assignment_type === "code_challenge" && (
                    <Badge tone="bg-purple-50 text-purple-800">Code challenge</Badge>
                  )}
                  <Badge tone={STATUS_STYLE[a.status].cls}>{STATUS_STYLE[a.status].text}</Badge>
                  <p className="mt-1 text-xs text-gray-600">Accepts: {a.submission_types.map(typeLabel).join(", ")}</p>
                  {a.submission_types.includes("code") && a.code_languages?.length > 0 && (
                    <p className="text-xs text-gray-600">Language: {languageNames(a.code_languages)}</p>
                  )}
                  <p className="text-xs text-gray-600">
                    Student self-checks: similarity {a.student_similarity_check ? "on" : "off"} · AI{" "}
                    {a.student_ai_check ? "on" : "off"}
                  </p>
                  {a.test_cases?.length > 0 && (
                    <p className="text-xs text-gray-600" data-testid="test-cases-summary">
                      {a.questions?.length > 1 && `Questions: ${a.questions.length} · `}
                      Test cases: {a.test_cases.length} ({a.test_cases.filter((t) => t.visible).length} visible) ·{" "}
                      {a.test_cases.reduce((sum, t) => sum + t.points, 0)} points
                    </p>
                  )}
                  {a.submission_types.includes("code") && (
                    <p className="text-xs text-gray-600">
                      Code similarity: {a.ignore_common_code ? "ignores code most of the class shares" : "compares all code"}
                    </p>
                  )}
                  <p className="text-xs text-gray-600" data-testid="marks-release">
                    Marks for students:{" "}
                    {a.marks_released ? (
                      "visible"
                    ) : (
                      <span className="font-semibold text-yellow-800">
                        hidden until {formatDateTime(a.marks_release_at!)}
                      </span>
                    )}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => startEdit(a)}
                    className="rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => askDelete(a)}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700"
                  >
                    Delete
                  </button>
                </div>
              </div>
              {a.description && <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{a.description}</p>}
              <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
                <dt className="font-semibold">Available from</dt>
                <dd>{formatDateTime(a.available_from)}</dd>
                <dt className="font-semibold">Deadline</dt>
                <dd>{formatDateTime(a.deadline)}</dd>
                <dt className="font-semibold">Rubric</dt>
                <dd>{a.rubric_name ? `${a.rubric_name} (${a.max_points} pts)` : "None selected"}</dd>
                <dt className="font-semibold">Starter code</dt>
                <dd>
                  {a.starter_code
                    ? `${a.starter_code_filename} (${a.starter_code.split("\n").length} lines, excluded from similarity)`
                    : "None"}
                </dd>
                <dt className="font-semibold">Report template (PDF)</dt>
                <dd>
                  <ReportTemplateControl assignment={a} onChanged={onChanged} />
                </dd>
                <dt className="font-semibold">Submissions</dt>
                <dd>
                  {a.submission_count} ({a.graded_count} graded)
                </dd>
              </dl>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </section>
  );
}
