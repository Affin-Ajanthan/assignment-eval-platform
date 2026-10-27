"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  apiFetch,
  apiFetchBlob,
  SampleRun,
  StudentAssignment,
  Submission,
  SubmissionFile,
  submissionFileUrl,
} from "@/lib/api";
import Badge from "@/components/Badge";
import Message, { MessageState } from "@/components/Message";
import { CodeLanguageId, languagesFor } from "@/lib/codeLanguages";

/** The languages the server can run tests for: must match LANGUAGES in app/evaluator/code_testing.py. */
const RUNNABLE: CodeLanguageId[] = ["python", "ruby"];
const MAX_CODE_CHARS = 50_000; // must match MAX_CODE_CHARS in app/routers/sample_runs.py
const INDENT: Partial<Record<CodeLanguageId, string>> = { python: "    ", ruby: "  " };
const PLACEHOLDER: Partial<Record<CodeLanguageId, string>> = {
  python: "# Read the input with input() and print the answer with print()",
  ruby: "# Read the input with gets and print the answer with puts",
};

const STATUS = {
  passed: { label: "Passed", tone: "bg-green-50 text-green-800" },
  failed: { label: "Wrong output", tone: "bg-red-50 text-red-700" },
  error: { label: "Crashed", tone: "bg-red-50 text-red-700" },
  timeout: { label: "Timed out", tone: "bg-yellow-50 text-yellow-800" },
} as const;

const pre =
  "mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-gray-50 p-2 font-mono text-xs";

const extOf = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

/** The languages a code challenge can be written in on the page: its own, if the server can run them. */
export function editorLanguages(assignment: StudentAssignment) {
  return languagesFor(assignment.code_languages).filter((l) => RUNNABLE.includes(l.id));
}

function SampleRunResults({ run }: { run: SampleRun }) {
  const all = run.passed === run.total;
  return (
    <div className="mt-3" data-testid="sample-run">
      <p className="text-sm font-semibold" data-testid="sample-run-summary">
        {run.passed} / {run.total} sample tests passed
      </p>
      <p className="text-xs text-gray-600">
        {all && run.total > 0 ? "All sample tests passed. " : ""}
        {run.hidden_test_count > 0
          ? `${run.hidden_test_count} hidden test${run.hidden_test_count === 1 ? " is" : "s are"} run when your work is marked. `
          : ""}
        {run.remaining_runs} sample run{run.remaining_runs === 1 ? "" : "s"} left this hour.
      </p>
      <ul className="mt-2 space-y-2">
        {run.results.map((r, i) => (
          <li key={i} className="rounded-md border border-gray-200 bg-white" data-testid="sample-result">
            {/* A failed test starts open: that is the one to look at. */}
            <details open={!r.passed}>
              <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-sm">
                <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                <span className="font-semibold">{r.name}</span>
                <span className="text-xs text-gray-500">{r.match === "contains" ? "output contains" : "exact output"}</span>
              </summary>
              <div className="space-y-2 border-t border-gray-100 px-3 py-2">
                <div>
                  <p className="text-xs font-semibold text-gray-600">Input</p>
                  <pre className={pre}>{r.input === "" ? "(none)" : r.input}</pre>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-gray-600">Expected output</p>
                    <pre className={pre}>{r.expected_output}</pre>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-gray-600">Your output</p>
                    <pre className={pre}>{r.actual_output === "" ? "(empty)" : r.actual_output}</pre>
                  </div>
                </div>
                {r.stderr && (
                  <div>
                    <p className="text-xs font-semibold text-red-700">Error message</p>
                    <pre className={`${pre} border-red-100 bg-red-50`}>{r.stderr}</pre>
                  </div>
                )}
              </div>
            </details>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A code challenge is answered here, not by uploading a file: the student types
 * their code, practises with "Run sample tests" (the visible tests only, nothing
 * is submitted or marked), and submits. The typed code is saved as one file
 * (main.py, main.rb) through the same endpoints as an upload.
 */
export default function CodeEditorForm({
  assignment,
  mode,
  onDone,
  onCancel,
}: {
  assignment: StudentAssignment;
  mode: "submit" | "edit";
  onDone: (text: string) => Promise<void>;
  onCancel: () => void;
}) {
  const languages = editorLanguages(assignment);
  const [language, setLanguage] = useState<CodeLanguageId>(languages[0].id);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(mode === "edit");
  const [msg, setMsg] = useState<MessageState>(null);
  const [run, setRun] = useState<SampleRun | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const escaped = useRef(false); // Esc was pressed: the next Tab leaves the box instead of indenting
  const busy = loading || running || submitting;
  const editorId = `code-editor-${assignment.id}`;

  // Editing: start from the code that was submitted, when it is one Python or Ruby file.
  useEffect(() => {
    if (mode !== "edit" || !assignment.my_submission) return;
    const submissionId = assignment.my_submission.id;
    let cancelled = false;
    (async () => {
      try {
        const files = (await apiFetch<SubmissionFile[]>(`/submissions/${submissionId}/files`)).filter(
          (f) => f.kind === "code",
        );
        const lang = files.length === 1 ? languages.find((l) => l.extensions[0] === extOf(files[0].name)) : undefined;
        if (!lang) {
          if (!cancelled) {
            setMsg({
              text: "Your current submission isn't a single Python or Ruby file, so it can't be shown here. Saving replaces it with the code below.",
              kind: "error",
            });
          }
          return;
        }
        const text = await (await apiFetchBlob(submissionFileUrl(submissionId, files[0]))).text();
        if (!cancelled) {
          setCode(text);
          setLanguage(lang.id);
        }
      } catch (err) {
        if (!cancelled) setMsg({ text: `Could not load your code: ${err instanceof Error ? err.message : err}`, kind: "error" });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, assignment.my_submission?.id]);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
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
    setCode(code.slice(0, start) + indent + code.slice(end));
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + indent.length;
    });
  }

  async function runSample() {
    if (!code.trim()) return setMsg({ text: "Write some code first.", kind: "error" });
    setMsg(null);
    setRunning(true);
    try {
      setRun(await apiFetch<SampleRun>(`/assignments/${assignment.id}/sample-run`, { method: "POST", json: { code, language } }));
    } catch (err) {
      setRun(null);
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setRunning(false);
    }
  }

  async function submit() {
    if (!code.trim()) return setMsg({ text: "Write some code first.", kind: "error" });
    setMsg(null);
    setSubmitting(true);
    try {
      const lang = languages.find((l) => l.id === language) ?? languages[0];
      const form = new FormData();
      form.append("code", new File([code], `main${lang.extensions[0]}`, { type: "text/plain" }));
      if (mode === "submit") {
        form.append("subject_id", String(assignment.subject_id));
        form.append("assignment_id", String(assignment.id));
        const submission = await apiFetch<Submission>("/submissions", { method: "POST", body: form });
        await onDone(`Submitted! Your submission id is ${submission.id}.`);
      } else {
        await apiFetch(`/submissions/${assignment.my_submission!.id}`, { method: "PUT", body: form });
        await onDone("Submission updated.");
      }
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
            disabled={busy}
            onChange={(e) => setLanguage(e.target.value as CodeLanguageId)}
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
        onChange={(e) => setCode(e.target.value)}
        onKeyDown={onKeyDown}
        rows={18}
        maxLength={MAX_CODE_CHARS}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        wrap="off"
        disabled={loading}
        placeholder={loading ? "Loading your code…" : PLACEHOLDER[language]}
        className="mt-1 block w-full overflow-auto rounded-md border border-gray-300 bg-white p-3 font-mono text-sm leading-5 disabled:bg-gray-50"
      />
      <p className="mt-1 text-xs text-gray-500">
        Tab indents; press Esc then Tab to move to the next control. {code.length} / {MAX_CODE_CHARS} characters.
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={runSample}
          disabled={busy}
          className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
        >
          {running ? "Running…" : "Run sample tests"}
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={busy}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {submitting ? "Submitting…" : mode === "submit" ? "Submit" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
        >
          Cancel
        </button>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Running the sample tests is practice: nothing is submitted or marked. Submit when you are happy with your code.
      </p>
      {running && <p className="mt-2 text-xs text-gray-600">Running your code in a safe sandbox: a few seconds per test.</p>}
      <Message state={msg} />
      {run && <SampleRunResults run={run} />}
    </div>
  );
}
