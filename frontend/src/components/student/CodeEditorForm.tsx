"use client";

import { KeyboardEvent, useRef, useState } from "react";
import { apiFetch, CodeQuestion, CodeQuestionResult, CodeRun, CodeSubmit, StudentAssignment } from "@/lib/api";
import { formatDateTime, formatMark } from "@/lib/datetime";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Message, { MessageState } from "@/components/Message";
import { CodeLanguageId, languagesFor } from "@/lib/codeLanguages";

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

// The server titles a question "Question 2" when the instructor gave it no title of its own.
const GENERATED_QUESTION = /^Question \d+$/;

/** "Question 2: Triple it", or just "Question 2" for a question without a title of its own. */
export function questionName(q: Pick<CodeQuestion, "id" | "title">): string {
  const title = q.title.trim();
  return !title || GENERATED_QUESTION.test(title) ? `Question ${q.id}` : `Question ${q.id}: ${title}`;
}

/** The languages a code challenge can be written in on the page: its own, if the server can run them. */
export function editorLanguages(assignment: StudentAssignment) {
  return languagesFor(assignment.code_languages).filter((l) => RUNNABLE.includes(l.id));
}

/**
 * The result of Run, and of Submit (which shows the same thing once the code is handed in): the
 * code was run against every test case, hidden ones included. Always "X of Y test cases passed";
 * then, for each VISIBLE test that failed, only what was expected and what the program printed.
 * A hidden test is only ever counted.
 */
export function CodeRunResults({ run, submitted = false }: { run: CodeRun; submitted?: boolean }) {
  // Runs left only matter for practice: Submit uses none.
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
            {f.status === "timeout" ? " (it ran out of time)" : f.status === "error" ? " (the program crashed)" : ""}
          </p>
          <div className="mt-1 grid gap-2 sm:grid-cols-2">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-600">Expected output</p>
              <pre className={pre}>{f.expected_output}</pre>
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-600">Actual output</p>
              <pre className={pre}>{f.actual_output === "" ? "(empty)" : f.actual_output}</pre>
            </div>
          </div>
          {f.error && (
            <div className="mt-2">
              <p className="text-xs font-semibold text-red-700">Error message</p>
              <pre className={`${pre} border-red-100 bg-red-50`}>{f.error}</pre>
            </div>
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
 * How each question of a marked submission did: the same report Run gives (counts, and expected vs actual
 * output of a visible test that failed). A challenge with several questions gets a heading for each, and a
 * question the student left empty says so.
 */
export function SubmitReport({ questions }: { questions: CodeQuestionResult[] }) {
  const many = questions.length > 1;
  return (
    <>
      {questions.map((q) => (
        <div key={q.question} data-testid="question-report">
          {many && <p className="mt-3 text-sm font-bold">{questionName({ id: q.question, title: q.title })}</p>}
          {q.run ? (
            <CodeRunResults run={q.run} submitted />
          ) : (
            <p className="mt-2 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700" data-testid="question-unanswered">
              You wrote no code for this question, so none of its test cases passed.
            </p>
          )}
        </div>
      ))}
    </>
  );
}

/**
 * The box with a student's mark once their code is marked: the mark itself (points of the test
 * cases passed out of all the points), or when it will be shown if the instructor holds marks back
 * until a release date. Nothing while the code has no mark yet.
 */
export function MarkBox({ result, releaseAt }: { result: CodeSubmit; releaseAt: string | null }) {
  let headline: string;
  let detail: string;
  if (result.earned !== null && result.total !== null) {
    headline = `Your mark: ${formatMark(result.earned, result.total)}`;
    detail = "the points of the test cases you passed";
  } else if (result.marked) {
    headline = releaseAt ? `Your mark will be released on ${formatDateTime(releaseAt)}` : "Your mark is saved";
    detail = releaseAt ? "it is already saved" : "you will see it on the assignment page";
  } else {
    return null;
  }
  return (
    <p className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-blue-900" data-testid="submit-mark">
      <span className="text-base font-bold">{headline}</span>
      <span className="ml-2 text-xs">({detail})</span>
    </p>
  );
}

/**
 * What the student sees as soon as the code is handed in: that it is final, how many test cases
 * passed (the same report Run gives) and their mark. When the tests could not be run just now the
 * code is still submitted, and `onGetMarks` lets the student ask for the mark again.
 */
export function CodeSubmitResult({
  result,
  releaseAt,
  onGetMarks,
  gettingMarks = false,
}: {
  result: CodeSubmit;
  releaseAt: string | null;
  onGetMarks?: () => void;
  gettingMarks?: boolean;
}) {
  return (
    <div className="mt-3" data-testid="submit-result">
      <p className="rounded-md bg-green-50 px-3 py-2 text-sm font-semibold text-green-800" data-testid="submitted-banner">
        ✓ Submitted. Your code is final: it cannot be changed now.
      </p>
      {result.marked ? (
        <SubmitReport questions={result.questions} />
      ) : (
        <div className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800" data-testid="not-marked">
          <p>
            The test cases could not be run just now, so your code has no mark yet. Try again in a moment; your
            instructor can also mark it.
          </p>
          {onGetMarks && (
            <button
              type="button"
              onClick={onGetMarks}
              disabled={gettingMarks}
              className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {gettingMarks ? "Getting your marks…" : "Get my marks"}
            </button>
          )}
        </div>
      )}
      <MarkBox result={result} releaseAt={releaseAt} />
    </div>
  );
}

/** What a student has typed for one question. */
type Answer = { code: string; language: CodeLanguageId };

/**
 * A code challenge is answered here, not by uploading a file: the student types their code and
 * has three buttons. A challenge has one or more questions; with several, they are tabs, each with
 * its own description, language and code. Run checks the code of the question that is open against
 * all of that question's test cases and shows how many passed (practice: nothing is submitted or
 * marked). Submit asks for confirmation, then saves the code of every question, runs every test
 * case, saves the points of the tests passed as the mark and shows the result at once. That is
 * final: the boxes lock and the only button left is Close. The typed code is saved on the server
 * as main.py / main.rb for one question, or q1.py, q2.rb, ... for several, which also refuses any
 * later change.
 */
export default function CodeEditorForm({
  assignment,
  onDone,
  onCancel,
  onSaved,
}: {
  assignment: StudentAssignment;
  // The card passes the same props to every form. A code challenge is never edited once
  // submitted (the server refuses it), so only "submit" is ever used here.
  mode?: "submit" | "edit";
  onDone: (text: string) => Promise<void>;
  onCancel: () => void;
  /** Called once the code is submitted and marked, so the card above shows the new status and mark at once. */
  onSaved?: () => Promise<void>;
}) {
  const languages = editorLanguages(assignment);
  const questions: CodeQuestion[] = assignment.questions?.length
    ? assignment.questions
    : [{ id: 1, title: "", statement: "" }]; // a challenge made before questions existed has the one
  const many = questions.length > 1;
  const blankAnswer: Answer = { code: "", language: languages[0].id };

  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [runs, setRuns] = useState<Record<number, CodeRun | null>>({}); // the last Run of each question
  const [current, setCurrent] = useState(questions[0].id); // the question that is open
  const [msg, setMsg] = useState<MessageState>(null);
  const [result, setResult] = useState<CodeSubmit | null>(null); // set once the code is handed in
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [gettingMarks, setGettingMarks] = useState(false);
  const escaped = useRef(false); // Esc was pressed: the next Tab leaves the box instead of indenting
  const busy = running || submitting;
  const final = result !== null;
  const editorId = `code-editor-${assignment.id}`;

  const answerOf = (id: number): Answer => answers[id] ?? blankAnswer;
  const written = (id: number) => answerOf(id).code.trim() !== "";
  const question = questions.find((q) => q.id === current) ?? questions[0];
  const { code, language } = answerOf(question.id);
  const run = runs[question.id] ?? null;

  /** A change to a question's code or language makes its last Run's result stale: drop it. */
  function change(id: number, patch: Partial<Answer>) {
    setAnswers((all) => ({ ...all, [id]: { ...(all[id] ?? blankAnswer), ...patch } }));
    setRuns((all) => ({ ...all, [id]: null }));
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (busy || final) return; // the box is read-only while code is being run or after it is handed in
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
    const blank = questions.filter((q) => !written(q.id));
    if (blank.length === questions.length) return setMsg({ text: "Write some code first.", kind: "error" });
    setMsg(null);
    const lines = [
      many
        ? `Your code for ${questions.length - blank.length} of ${questions.length} questions will be run against every test case and marked at once.`
        : "Your code will be run against every test case and marked at once.",
    ];
    if (blank.length > 0) {
      lines.push(
        `${blank.map((q) => questionName(q)).join(", ")} ${blank.length === 1 ? "has" : "have"} no code and will earn no points.`,
      );
    }
    lines.push("A submission is final: you cannot change or withdraw it afterwards.");
    setConfirm({ title: "Submit your code?", message: lines.join("\n"), confirmLabel: "Submit", onConfirm: submit });
  }

  async function submit() {
    setConfirm(null);
    setMsg(null);
    setRuns({});
    setSubmitting(true);
    try {
      // A question left empty is simply not sent: it earns nothing.
      const answered = questions.filter((q) => written(q.id)).map((q) => ({ question: q.id, ...answerOf(q.id) }));
      setResult(
        await apiFetch<CodeSubmit>(`/assignments/${assignment.id}/submit-code`, { method: "POST", json: { answers: answered } }),
      );
      onSaved?.().catch(() => {}); // the card's status and mark; the result below does not depend on it
    } catch (err) {
      setMsg({ text: `Submission failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  /** The tests could not be run at Submit: ask the server to mark the saved code now. */
  async function getMarks() {
    setGettingMarks(true);
    setMsg(null);
    try {
      const marked = await apiFetch<CodeSubmit>(`/assignments/${assignment.id}/mark-my-code`, { method: "POST" });
      if (marked.marked) {
        setResult(marked);
        onSaved?.().catch(() => {});
      } else {
        setMsg({ text: "The test cases could not be run just now. Please try again in a moment.", kind: "error" });
      }
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setGettingMarks(false);
    }
  }

  const heading = many ? questionName(question) : question.title.trim();
  return (
    <div className="mt-4 rounded-md border border-gray-200 p-4" data-testid="code-editor">
      {many && (
        <div
          role="tablist"
          aria-label="Questions"
          className="mb-3 flex flex-wrap gap-1 border-b border-gray-200"
          data-testid="question-tabs"
        >
          {questions.map((q) => {
            const selected = q.id === question.id;
            // A tick once a Run passed every test case of the question, a dot once some code is typed.
            // Nothing after Submit: the report below says how each question did.
            const mark = final ? "" : runs[q.id]?.all_passed ? "✓ " : written(q.id) ? "• " : "";
            return (
              <button
                key={q.id}
                type="button"
                role="tab"
                id={`${editorId}-tab-${q.id}`}
                aria-selected={selected}
                aria-controls={`${editorId}-panel`}
                onClick={() => setCurrent(q.id)}
                className={`-mb-px max-w-[16rem] truncate rounded-t-md border px-3 py-1.5 text-sm font-semibold ${
                  selected
                    ? "border-gray-200 border-b-white bg-white text-blue-700"
                    : "border-transparent text-gray-600 hover:text-gray-900"
                }`}
              >
                {mark}
                {questionName(q)}
              </button>
            );
          })}
        </div>
      )}

      <div
        id={`${editorId}-panel`}
        role={many ? "tabpanel" : undefined}
        aria-labelledby={many ? `${editorId}-tab-${question.id}` : undefined}
      >
        {(heading || question.statement.trim()) && (
          <div className="mb-3 rounded-md bg-gray-50 p-3" data-testid="question-statement">
            {heading && <p className="text-sm font-bold">{heading}</p>}
            {question.statement.trim() && <p className="whitespace-pre-wrap text-sm text-gray-800">{question.statement}</p>}
          </div>
        )}

        <div className="flex flex-wrap items-end justify-between gap-2">
          <label className="text-sm font-semibold" htmlFor={editorId}>
            Your code
          </label>
          {languages.length > 1 ? (
            <select
              aria-label="Language"
              value={language}
              disabled={busy || final}
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
            <span className="text-xs text-gray-600">{languages[0].name}</span>
          )}
        </div>
        <textarea
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
          readOnly={busy || final}
          placeholder={PLACEHOLDER[language]}
          className="mt-1 block w-full overflow-auto rounded-md border border-gray-300 bg-white p-3 font-mono text-sm leading-5 read-only:bg-gray-50"
        />
        {!final && (
          <p className="mt-1 text-xs text-gray-500">
            Tab indents; press Esc then Tab to move to the next control. {code.length} / {MAX_CODE_CHARS} characters.
          </p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {!final && (
          <>
            <button
              type="button"
              onClick={runCode}
              disabled={busy}
              className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
            >
              {running ? "Running…" : many ? "Run this question" : "Run"}
            </button>
            <button
              type="button"
              onClick={askToSubmit}
              disabled={busy}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {submitting ? "Submitting…" : many ? "Submit all" : "Submit"}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => (result ? onDone(`Submitted! Your submission id is ${result.submission_id}.`) : onCancel())}
          disabled={submitting}
          className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
        >
          {final ? "Close" : "Cancel"}
        </button>
      </div>
      {!final && (
        <p className="mt-2 text-xs text-gray-500">
          {many
            ? "Run checks the question that is open against all of its test cases without submitting anything. "
            : "Run checks your code against all the test cases without submitting it. "}
          Submit is final: your code{many ? " for every question" : ""} is run against every test case, marked at once,
          and cannot be changed afterwards.
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
      {run && <CodeRunResults run={run} />}
      {result && (
        <CodeSubmitResult
          result={result}
          releaseAt={assignment.marks_release_at}
          onGetMarks={getMarks}
          gettingMarks={gettingMarks}
        />
      )}
      <ConfirmDialog request={confirm} onCancel={() => setConfirm(null)} />
    </div>
  );
}
