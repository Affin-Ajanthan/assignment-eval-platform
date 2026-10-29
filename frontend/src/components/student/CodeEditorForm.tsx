"use client";

import { KeyboardEvent, useRef, useState } from "react";
import { apiFetch, CodeAnswer, CodeQuestion, CodeRun, CodeWork, StudentAssignment } from "@/lib/api";
import { formatDateTime, formatMark } from "@/lib/datetime";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Message, { MessageState } from "@/components/Message";
import RichText from "@/components/RichText";
import LineNumberedTextarea from "@/components/student/LineNumberedTextarea";
import { CodeLanguageId, languagesFor } from "@/lib/codeLanguages";
import { taskName } from "@/lib/tasks";

/** The languages the server can run tests for: must match LANGUAGES in app/evaluator/code_testing.py. */
const RUNNABLE: CodeLanguageId[] = ["python", "ruby"];
const MAX_CODE_CHARS = 50_000; // must match MAX_CODE_CHARS in app/routers/student_runs.py
const INDENT: Partial<Record<CodeLanguageId, string>> = { python: "    ", ruby: "  " };
const PLACEHOLDER: Partial<Record<CodeLanguageId, string>> = {
  python: "# Read the input with input() and print the answer with print()",
  ruby: "# Read the input with gets and print the answer with puts",
};

const pre =
  "mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-white p-2 font-mono text-xs";

// A test the instructor did not name is stored as "Test 2" (its place among ALL the tests,
// hidden ones included), which means little to a student: show "Sample 1" instead.
const GENERATED_NAME = /^Test \d+$/;

/** "Sample 2: Palindrome with punctuation", or just "Sample 2" for a test without a real name. */
export function sampleLabel(name: string, index: number): string {
  const trimmed = name.trim();
  return !trimmed || GENERATED_NAME.test(trimmed) ? `Sample ${index + 1}` : `Sample ${index + 1}: ${trimmed}`;
}

/** The languages a code challenge can be written in on the page: its own, if the server can run them. */
export function editorLanguages(assignment: StudentAssignment) {
  return languagesFor(assignment.code_languages).filter((l) => RUNNABLE.includes(l.id));
}

/**
 * The result of Run, and of a task that is handed in (which shows the same thing): the code was
 * run against every test case of the task, hidden ones included. Always "X of Y test cases
 * passed"; then, for each VISIBLE test that failed, only what was expected and what the program
 * printed. A hidden test is only ever counted.
 */
export function CodeRunResults({ run, submitted = false }: { run: CodeRun; submitted?: boolean }) {
  // Runs left only matter for practice: handing a task in uses none.
  const left = submitted ? "" : `${run.remaining_runs} run${run.remaining_runs === 1 ? "" : "s"} left this hour.`;
  if (run.all_passed) {
    return (
      <div className="mt-3 rounded-md border border-green-200 bg-green-50 px-3 py-2" data-testid="run-result">
        <p className="text-sm font-semibold text-green-800" data-testid="run-summary">
          ✓ {run.passed} of {run.total} test case{run.total === 1 ? "" : "s"} passed: all passed.
        </p>
        {!submitted && (
          <p className="mt-1 text-xs text-green-800">
            Press Submit to hand in your code: it is final, you cannot change it afterwards. {left}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3" data-testid="run-result">
      <p className="text-sm font-semibold text-red-800" data-testid="run-summary">
        {run.passed} of {run.total} test case{run.total === 1 ? "" : "s"} passed.
      </p>
      {run.failures.map((f) => (
        <div key={f.sample} className="mt-2 rounded-md border border-red-100 bg-white p-3" data-testid="run-failure">
          <p className="text-sm font-semibold">
            {sampleLabel(f.name, f.sample - 1)} did not pass
            {f.status === "timeout" ? " (it ran out of time)" : ""}
          </p>
          {f.status === "error" ? (
            // The program crashed, so there is no output to compare: only where it went wrong. (A result saved
            // before this was how it is shown holds the whole traceback in `error`: that is not printed.)
            <p className="mt-1 text-sm font-semibold text-red-800" data-testid="compiler-error">
              {f.error.startsWith("Compiler error") ? f.error : "Compiler error."}
            </p>
          ) : (
            <>
              {f.input !== undefined && (
                <div className="mt-1 min-w-0">
                  <p className="text-xs font-semibold text-gray-600">Input</p>
                  <pre className={pre}>{f.input === "" ? "(none)" : f.input}</pre>
                </div>
              )}
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-gray-600">Expected output</p>
                  <pre className={pre}>{f.expected_output}</pre>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-gray-600">Actual output</p>
                  <pre className={pre}>{f.actual_output === "" ? "(empty)" : f.actual_output}</pre>
                </div>
              </div>
              {f.error && <p className="mt-2 text-xs text-red-700">{f.error}</p>}
            </>
          )}
        </div>
      ))}
      {run.hidden_failed > 0 && (
        <p className="mt-2 text-xs text-red-800">
          {run.hidden_failed} hidden test case{run.hidden_failed === 1 ? "" : "s"} did not pass. Hidden test cases are
          not shown.
        </p>
      )}
      {left && <p className="mt-2 text-xs text-gray-600">{left}</p>}
    </div>
  );
}

/**
 * The student's mark so far, or their mark once every task is handed in and marked: the points of
 * the test cases they passed out of the points of ALL the tasks. Or, when the instructor holds marks
 * back until a release date, when it will be shown. Nothing while no answer is marked yet.
 */
export function MarkBox({ work, releaseAt }: { work: CodeWork; releaseAt: string | null }) {
  const final = work.complete && work.questions.every((q) => q.marked);
  let headline: string;
  let detail: string;
  if (work.earned !== null && work.total !== null) {
    headline = `${final ? "Your mark" : "Your mark so far"}: ${formatMark(work.earned, work.total)}`;
    detail = final
      ? "the points of the test cases you passed"
      : "it adds up as the other tasks are handed in and marked";
  } else if (work.marked) {
    headline = releaseAt ? `Your mark will be released on ${formatDateTime(releaseAt)}` : "Your mark is saved";
    detail = releaseAt ? "it is already saved" : "you will see it on the assignment page";
  } else {
    return null;
  }
  return (
    <p className="mb-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-blue-900" data-testid="submit-mark">
      <span className="text-base font-bold">{headline}</span>
      <span className="ml-2 text-xs">({detail})</span>
    </p>
  );
}

/**
 * What the student sees under a task they have handed in: that it is final, how it did (the same
 * report Run gives) and the points it earned. When the tests could not be run at that moment, the
 * answer has no result yet and `onGetMarks` asks the server to run them now.
 */
function HandedIn({
  answer,
  next,
  onNext,
  onGetMarks,
  gettingMarks,
}: {
  answer: CodeAnswer;
  /** The next task still to hand in, if there is one. */
  next: CodeQuestion | null;
  onNext: () => void;
  onGetMarks: () => void;
  gettingMarks: boolean;
}) {
  return (
    <div className="mt-3" data-testid="question-report">
      <p className="rounded-md bg-green-50 px-3 py-2 text-sm font-semibold text-green-800" data-testid="submitted-banner">
        ✓ Submitted. Your answer is final: it cannot be changed now.
      </p>
      {answer.marked ? (
        <>
          {answer.run ? (
            <CodeRunResults run={answer.run} submitted />
          ) : (
            <p className="mt-2 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700">This answer is marked.</p>
          )}
          {answer.earned !== null && answer.total !== null && (
            <p className="mt-2 text-sm font-semibold" data-testid="question-points">
              Points for this answer: {formatMark(answer.earned, answer.total)}
            </p>
          )}
        </>
      ) : (
        <div className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800" data-testid="not-marked">
          <p>
            The test cases could not be run just now, so this answer has no mark yet. Try again in a moment; your
            instructor can also mark it.
          </p>
          <button
            type="button"
            onClick={onGetMarks}
            disabled={gettingMarks}
            className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {gettingMarks ? "Getting your marks…" : "Get my marks"}
          </button>
        </div>
      )}
      {next && (
        <button
          type="button"
          onClick={onNext}
          className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          data-testid="next-question"
        >
          Go to {taskName(next)} →
        </button>
      )}
    </div>
  );
}

/** What a student has typed for one task that is not handed in yet. */
type Answer = { code: string; language: CodeLanguageId };

/**
 * The code editor of a code challenge, on the challenge's own page (app/student/code/[id]), which the
 * student reaches with "Do assignment": the questions are shown here and nowhere before. The student does
 * the tasks one at a time: with several, they are tabs, each with its own question, language and code,
 * and they can be done in any order (or, when the instructor set it, only in order: a task's tab stays locked
 * until the one before it is handed in). Run checks the code of the task that is open against all of that
 * task's test cases and shows how many passed (practice: nothing is handed in or marked). Submit asks for
 * confirmation, then hands that task in: the server runs every test case of the task, saves the points
 * as the mark and the page shows the result at once. A task handed in is final: its box locks and shows
 * the code that was handed in, and the student moves on to the next one. `work` is what the server holds
 * so far (also after a reload); every Submit and "Get my marks" gives back a newer one, passed to `onWork`.
 */
export default function CodeEditorForm({
  assignment,
  work,
  onWork,
}: {
  assignment: StudentAssignment;
  work: CodeWork;
  onWork: (work: CodeWork) => void;
}) {
  const languages = editorLanguages(assignment);
  const questions: CodeQuestion[] = assignment.questions?.length
    ? assignment.questions
    : [{ id: 1, title: "", statement: "" }]; // a challenge made before tasks existed has the one
  const many = questions.length > 1;
  const open = assignment.status === "open";
  /** A task's code box before the student types: the instructor's starting code for it, if there is any. */
  const starterOf = (id: number) => questions.find((q) => q.id === id)?.starter_code ?? "";
  const blankFor = (id: number): Answer => ({ code: starterOf(id), language: languages[0].id });
  /** The answer the student handed in for a task, or null while it is not handed in. */
  const handedIn = (id: number): CodeAnswer | null => work.questions.find((q) => q.question === id && q.submitted) ?? null;
  /** When the tasks go in order: the first earlier task not handed in yet, which this one waits for (else null). */
  const waitingFor = (id: number): number | null =>
    assignment.tasks_in_order && open ? (questions.find((q) => q.id < id && handedIn(q.id) === null)?.id ?? null) : null;

  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [runs, setRuns] = useState<Record<number, CodeRun | null>>({}); // the last Run of each task
  const [current, setCurrent] = useState(() => (questions.find((q) => handedIn(q.id) === null) ?? questions[0]).id);
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [gettingMarks, setGettingMarks] = useState(false);
  const escaped = useRef(false); // Esc was pressed: the next Tab leaves the box instead of indenting
  const busy = running || submitting;
  const editorId = `code-editor-${assignment.id}`;

  const answerOf = (id: number): Answer => answers[id] ?? blankFor(id);
  const question = questions.find((q) => q.id === current) ?? questions[0];
  const saved = handedIn(question.id);
  const locked = saved !== null || !open; // handed in (final), or the deadline has passed
  const typed = answerOf(question.id);
  const code = saved ? (saved.code ?? "") : typed.code;
  const language = (saved?.language ?? typed.language) as CodeLanguageId;
  const run = runs[question.id] ?? null;
  const handedInCount = questions.filter((q) => handedIn(q.id) !== null).length;
  const todo = questions.filter((q) => q.id !== question.id && handedIn(q.id) === null);
  const next = open ? (todo.find((q) => q.id > question.id) ?? todo[0] ?? null) : null;

  /** A change to a task's code or language makes its last Run's result stale: drop it. */
  function change(id: number, patch: Partial<Answer>) {
    setAnswers((all) => ({ ...all, [id]: { ...(all[id] ?? blankFor(id)), ...patch } }));
    setRuns((all) => ({ ...all, [id]: null }));
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (busy || locked) return; // the box is read-only while code is being run, and once a task is handed in
    if (e.key === "Escape") {
      escaped.current = true;
      return;
    }
    if (e.key !== "Tab" || e.shiftKey || escaped.current) {
      escaped.current = false;
      return;
    }
    e.preventDefault(); // Tab indents; Esc then Tab (or Shift+Tab) moves on, so keyboard users are not trapped
    const el = e.currentTarget;
    const { selectionStart: start, selectionEnd: end } = el;
    const indent = INDENT[language] ?? "  ";
    change(question.id, { code: code.slice(0, start) + indent + code.slice(end) });
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + indent.length;
    });
  }

  async function runCode() {
    if (!code.trim()) return setMsg({ text: "Write some code first.", kind: "error" });
    const id = question.id; // the boxes are read-only while this runs, so the result belongs to this code
    setMsg(null);
    setRuns((all) => ({ ...all, [id]: null }));
    setRunning(true);
    try {
      const report = await apiFetch<CodeRun>(`/assignments/${assignment.id}/run-code`, {
        method: "POST",
        json: { code, language, question: id },
      });
      setRuns((all) => ({ ...all, [id]: report }));
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setRunning(false);
    }
  }

  /** Submit asks first: it cannot be undone. */
  function askToSubmit() {
    if (!code.trim()) return setMsg({ text: "Write some code first.", kind: "error" });
    setMsg(null);
    const lines = [
      many
        ? `Your code for ${taskName(question)} will be run against every test case of this task and marked at once.`
        : "Your code will be run against every test case and marked at once.",
    ];
    if (todo.length > 0) {
      lines.push(
        `You can still hand in ${todo.length === 1 ? "the other task" : `the other ${todo.length} tasks`} afterwards, one at a time.`,
      );
    }
    lines.push("A submission is final: you cannot change or withdraw it afterwards.");
    setConfirm({
      title: many ? `Submit ${taskName(question)}?` : "Submit your code?",
      message: lines.join("\n"),
      confirmLabel: "Submit",
      onConfirm: submit,
    });
  }

  /** What the server holds now: after a Submit that failed it may still have gone through (the answer got lost). */
  async function reload() {
    try {
      onWork(await apiFetch<CodeWork>(`/assignments/${assignment.id}/my-code`));
    } catch {
      /* keep what is on the screen */
    }
  }

  async function submit() {
    const id = question.id;
    setConfirm(null);
    setMsg(null);
    setSubmitting(true);
    try {
      const updated = await apiFetch<CodeWork>(`/assignments/${assignment.id}/submit-code`, {
        method: "POST",
        json: { question: id, code, language },
      });
      setRuns((all) => ({ ...all, [id]: null }));
      onWork(updated);
    } catch (err) {
      setMsg({ text: `Submission failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
      await reload();
    } finally {
      setSubmitting(false);
    }
  }

  /** Some answers were handed in but their tests could not be run: ask the server to run them now. */
  async function getMarks() {
    setGettingMarks(true);
    setMsg(null);
    try {
      const marked = await apiFetch<CodeWork>(`/assignments/${assignment.id}/mark-my-code`, { method: "POST" });
      onWork(marked);
      if (marked.questions.some((q) => q.submitted && !q.marked)) {
        setMsg({ text: "The test cases could not be run just now. Please try again in a moment.", kind: "error" });
      }
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setGettingMarks(false);
    }
  }

  // Every task is named, a single one too ("Task 1"), so the student always sees what they are working on.
  const heading = taskName(question);
  const hasQuestion = question.statement.trim() !== "";
  // A challenge made before tasks existed keeps its question in the description, which the page shows above.
  const noQuestion = !hasQuestion && assignment.description.trim() === "";
  const languageName = languages.find((l) => l.id === language)?.name ?? language;
  return (
    <div className="mt-4 rounded-md border border-gray-200 p-4" data-testid="code-editor">
      <MarkBox work={work} releaseAt={assignment.marks_release_at} />
      {many && (
        <>
          <p className="mb-2 text-sm text-gray-700" data-testid="progress">
            {work.complete
              ? `All ${questions.length} tasks are handed in.`
              : `${handedInCount} of ${questions.length} tasks handed in.${
                  open
                    ? assignment.tasks_in_order
                      ? " Hand them in one at a time, in order: a task opens once the one before it is handed in."
                      : " Hand them in one at a time, in any order."
                    : ""
                }`}
          </p>
          <div
            role="tablist"
            aria-label="Tasks"
            className="mb-3 flex flex-wrap gap-1 border-b border-gray-200"
            data-testid="question-tabs"
          >
            {questions.map((q) => {
              const selected = q.id === question.id;
              // A tick once the task is handed in, a dot while the student has changed the code for it
              // (the starting code alone does not count).
              const typedCode = answers[q.id]?.code.trim() ?? "";
              const waiting = waitingFor(q.id);
              const mark = waiting !== null
                ? "🔒 "
                : handedIn(q.id)
                  ? "✓ "
                  : typedCode !== "" && typedCode !== starterOf(q.id).trim()
                    ? "• "
                    : "";
              return (
                <button
                  key={q.id}
                  type="button"
                  role="tab"
                  id={`${editorId}-tab-${q.id}`}
                  aria-selected={selected}
                  aria-controls={`${editorId}-panel`}
                  disabled={waiting !== null}
                  title={waiting !== null ? `Hand in ${taskName(questions.find((x) => x.id === waiting) ?? q)} first` : undefined}
                  onClick={() => setCurrent(q.id)}
                  className={`-mb-px max-w-[16rem] truncate rounded-t-md border px-3 py-1.5 text-sm font-semibold ${
                    selected
                      ? "border-gray-200 border-b-white bg-white text-blue-700"
                      : waiting !== null
                        ? "cursor-not-allowed border-transparent text-gray-400"
                        : "border-transparent text-gray-600 hover:text-gray-900"
                  }`}
                >
                  {mark}
                  {taskName(q)}
                </button>
              );
            })}
          </div>
        </>
      )}

      <div
        id={`${editorId}-panel`}
        role={many ? "tabpanel" : undefined}
        aria-labelledby={many ? `${editorId}-tab-${question.id}` : undefined}
      >
        <div className="mb-3 rounded-md bg-gray-50 p-3" data-testid="question-statement">
          <p className="text-sm font-bold">{heading}</p>
          {hasQuestion && (
            <>
              <p className="mt-2 text-xs font-semibold text-gray-600">Question</p>
              <RichText text={question.statement} className="text-sm text-gray-800" />
            </>
          )}
          {noQuestion && (
            <p className="mt-1 text-sm text-gray-600" data-testid="no-question">
              Your instructor has not written the question for this task yet.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-end justify-between gap-2">
          <label className="text-sm font-semibold" htmlFor={editorId}>
            {saved ? "The code you handed in" : "Your code"}
          </label>
          {!locked && languages.length > 1 ? (
            <select
              aria-label="Language"
              value={language}
              disabled={busy}
              onChange={(e) => change(question.id, { language: e.target.value as CodeLanguageId })}
              className="rounded-md border border-gray-300 px-2 py-1 text-sm"
            >
              {languages.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          ) : (
            (saved || !locked) && <span className="text-xs text-gray-600">{languageName}</span>
          )}
        </div>
        <LineNumberedTextarea
          key={question.id}
          id={editorId}
          value={code}
          onChange={(e) => change(question.id, { code: e.target.value })}
          onKeyDown={onKeyDown}
          rows={18}
          maxLength={MAX_CODE_CHARS}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          wrap="off"
          readOnly={busy || locked}
          placeholder={locked ? undefined : PLACEHOLDER[language]}
          className="resize-none read-only:bg-gray-50"
        />
        {!locked && starterOf(question.id).trim() !== "" && (
          <p className="mt-1 text-xs text-gray-600" data-testid="starter-note">
            Your instructor gave you starting code for this task. Write your answer on top of it.
          </p>
        )}
        {!locked && (
          <p className="mt-1 text-xs text-gray-500">
            Tab indents; press Esc then Tab to move to the next control. {code.length} / {MAX_CODE_CHARS} characters.
          </p>
        )}
      </div>

      {!locked && (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={runCode}
              disabled={busy}
              className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
            >
              {running ? "Running…" : many ? "Run this task" : "Run"}
            </button>
            <button
              type="button"
              onClick={askToSubmit}
              disabled={busy}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {submitting ? "Submitting…" : many ? "Submit this task" : "Submit"}
            </button>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            Run checks your code against all the test cases of {many ? "this task" : "the challenge"} without
            handing it in. Submit is final: {many ? "this task is" : "your code is"} run against every test case,
            marked at once, and cannot be changed afterwards.
            {many && " The other tasks stay open until you hand them in."}
          </p>
        </>
      )}
      {!saved && !open && (
        <p className="mt-3 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700" data-testid="not-handed-in">
          The deadline has passed. This task was not handed in, so it earns no points.
        </p>
      )}
      {running && (
        <p className="mt-2 text-xs text-gray-600">Running every test case in a safe sandbox: a few seconds each.</p>
      )}
      {submitting && (
        <p className="mt-2 text-xs text-gray-600">
          Saving your code and running every test case in a safe sandbox: a few seconds each. Please wait.
        </p>
      )}
      <Message state={msg} />
      {!saved && run && <CodeRunResults run={run} />}
      {saved && (
        <HandedIn
          answer={saved}
          next={next}
          onNext={() => next && setCurrent(next.id)}
          onGetMarks={getMarks}
          gettingMarks={gettingMarks}
        />
      )}
      <ConfirmDialog request={confirm} onCancel={() => setConfirm(null)} />
    </div>
  );
}
