"use client";

import { KeyboardEvent, useRef, useState } from "react";
import { apiFetch, CodeRun, CodeSubmit, StudentAssignment } from "@/lib/api";
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
 * What the student sees as soon as the code is handed in: that it is final, how many test cases
 * passed (the same report Run gives) and their mark. The mark is left out while the instructor
 * holds marks back until a release date, and when the tests could not be run just now.
 */
export function CodeSubmitResult({ result, releaseAt }: { result: CodeSubmit; releaseAt: string | null }) {
  const mark =
    result.earned !== null && result.total !== null
      ? `Your mark: ${formatMark(result.earned, result.total)} (the points of the test cases you passed).`
      : result.marked
        ? releaseAt
          ? `Your mark will be released on ${formatDateTime(releaseAt)}.`
          : "Your mark is on the assignment page."
        : null;
  return (
    <div className="mt-3" data-testid="submit-result">
      <p className="rounded-md bg-green-50 px-3 py-2 text-sm font-semibold text-green-800" data-testid="submitted-banner">
        ✓ Submitted. Your code is final: it cannot be changed now.
      </p>
      {result.run ? (
        <CodeRunResults run={result.run} submitted />
      ) : (
        <p className="mt-3 rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800" data-testid="not-marked">
          The test cases could not be run just now, so your code has no mark yet. Your instructor will mark it.
        </p>
      )}
      {mark && (
        <p className="mt-3 text-sm font-semibold" data-testid="submit-mark">
          {mark}
        </p>
      )}
    </div>
  );
}

/**
 * A code challenge is answered here, not by uploading a file: the student types their code and
 * has three buttons. Run checks it against every test case and shows how many passed (practice:
 * nothing is submitted or marked). Submit asks for confirmation, then saves the code, runs every
 * test case, saves the points of the tests passed as the mark and shows the result at once. That is
 * final: the box locks and the only button left is Close. The typed code is saved as one file
 * (main.py, main.rb) on the server, which also refuses any later change.
 */
export default function CodeEditorForm({
  assignment,
  onDone,
  onCancel,
}: {
  assignment: StudentAssignment;
  // The card passes the same props to every form. A code challenge is never edited once
  // submitted (the server refuses it), so only "submit" is ever used here.
  mode?: "submit" | "edit";
  onDone: (text: string) => Promise<void>;
  onCancel: () => void;
}) {
  const languages = editorLanguages(assignment);
  const [language, setLanguage] = useState<CodeLanguageId>(languages[0].id);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<MessageState>(null);
  const [run, setRun] = useState<CodeRun | null>(null);
  const [result, setResult] = useState<CodeSubmit | null>(null); // set once the code is handed in
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const escaped = useRef(false); // Esc was pressed: the next Tab leaves the box instead of indenting
  const busy = running || submitting;
  const final = result !== null;
  const editorId = `code-editor-${assignment.id}`;

  /** A change to the code or the language makes the last Run's result stale: drop it. */
  function edit(next: string) {
    setCode(next);
    setRun(null);
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
    edit(code.slice(0, start) + indent + code.slice(end));
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + indent.length;
    });
  }

  async function runCode() {
    if (!code.trim()) return setMsg({ text: "Write some code first.", kind: "error" });
    setMsg(null);
    setRun(null);
    setRunning(true);
    try {
      setRun(await apiFetch<CodeRun>(`/assignments/${assignment.id}/run-code`, { method: "POST", json: { code, language } }));
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
    setConfirm({
      title: "Submit your code?",
      message:
        "Your code will be run against every test case and marked at once.\nA submission is final: you cannot change or withdraw it afterwards.",
      confirmLabel: "Submit",
      onConfirm: submit,
    });
  }

  async function submit() {
    setConfirm(null);
    setMsg(null);
    setRun(null);
    setSubmitting(true);
    try {
      setResult(
        await apiFetch<CodeSubmit>(`/assignments/${assignment.id}/submit-code`, { method: "POST", json: { code, language } }),
      );
    } catch (err) {
      setMsg({ text: `Submission failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-4 rounded-md border border-gray-200 p-4" data-testid="code-editor">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <label className="text-sm font-semibold" htmlFor={editorId}>
          Your code
        </label>
        {languages.length > 1 ? (
          <select
            aria-label="Language"
            value={language}
            disabled={busy || final}
            onChange={(e) => {
              setLanguage(e.target.value as CodeLanguageId);
              setRun(null);
            }}
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
        id={editorId}
        value={code}
        onChange={(e) => edit(e.target.value)}
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

      <div className="mt-3 flex flex-wrap gap-2">
        {!final && (
          <>
            <button
              type="button"
              onClick={runCode}
              disabled={busy}
              className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
            >
              {running ? "Running…" : "Run"}
            </button>
            <button
              type="button"
              onClick={askToSubmit}
              disabled={busy}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {submitting ? "Submitting…" : "Submit"}
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
          Run checks your code against all the test cases without submitting it. Submit is final: your code is run
          against every test case, marked at once, and cannot be changed afterwards.
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
      {result && <CodeSubmitResult result={result} releaseAt={assignment.marks_release_at} />}
      <ConfirmDialog request={confirm} onCancel={() => setConfirm(null)} />
    </div>
  );
}
