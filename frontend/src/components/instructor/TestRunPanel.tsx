"use client";

import { useState } from "react";
import { apiFetch, TestResult, TestRun } from "@/lib/api";
import { taskName } from "@/lib/tasks";
import Badge from "@/components/Badge";
import Message, { MessageState } from "@/components/Message";

const STATUS: Record<TestResult["status"], { label: string; tone: string }> = {
  passed: { label: "Passed", tone: "bg-green-50 text-green-800" },
  failed: { label: "Wrong output", tone: "bg-red-50 text-red-700" },
  error: { label: "Crashed", tone: "bg-red-50 text-red-700" },
  timeout: { label: "Timed out", tone: "bg-yellow-50 text-yellow-800" },
  skipped: { label: "No answer", tone: "bg-gray-100 text-gray-700" },
};

const MATCH_LABEL = { exact: "exact output", contains: "output contains" } as const;

const pre = "mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-gray-50 p-2 font-mono text-xs";

/** Whole numbers without a decimal point: "16", "2.5". */
const num = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""));

function Output({ label, text }: { label: string; text: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-semibold text-gray-600">{label}</p>
      <pre className={pre}>{text === "" ? "(empty)" : text}</pre>
    </div>
  );
}

function TestRow({ r }: { r: TestResult }) {
  const status = STATUS[r.status];
  return (
    <li className="rounded-md border border-gray-200 bg-white" data-testid="test-result">
      {/* Failed tests start open: that is what the instructor came to look at. */}
      <details open={!r.passed}>
        <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-sm">
          <Badge tone={status.tone}>{status.label}</Badge>
          <span className="font-semibold">{r.name}</span>
          <span className="text-xs text-gray-500">
            {r.passed ? num(r.points) : 0} / {num(r.points)} points · {MATCH_LABEL[r.match]} ·{" "}
            {r.visible ? "visible to students" : "hidden"}
          </span>
        </summary>
        <div className="space-y-2 border-t border-gray-100 px-3 py-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Output label="Expected output" text={r.expected_output} />
            <Output label="Actual output" text={r.actual_output} />
          </div>
          {r.stderr && (
            <div>
              <p className="text-xs font-semibold text-red-700">Error output</p>
              <pre className={`${pre} border-red-100 bg-red-50`}>{r.stderr}</pre>
            </div>
          )}
        </div>
      </details>
    </li>
  );
}

/**
 * Runs an assignment's test cases on one submission's code (in the server's
 * Docker sandbox) and shows each test's expected and actual output. This is the
 * instructor's view: hidden tests are included and marked as hidden.
 */
export default function TestRunPanel({
  submissionId,
  testCount,
  isChallenge,
  onSaved,
}: {
  submissionId: number;
  testCount: number;
  /** A code challenge is marked from its tests: the panel can save the score as the mark. */
  isChallenge: boolean;
  /** Called after a mark was saved, so the submissions table shows it. */
  onSaved: () => void;
}) {
  const [run, setRun] = useState<TestRun | null>(null);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  /** Run the tests; with `save`, also keep the points of the tests passed as the submission's mark. */
  async function start(save: boolean) {
    setMsg(null);
    setRun(null);
    setRunning(true);
    try {
      const path = save ? "mark-from-tests" : "run-tests";
      const result = await apiFetch<TestRun>(`/submissions/${submissionId}/${path}`, { method: "POST" });
      setRun(result);
      if (result.saved) {
        setMsg({
          text: `Saved as this submission's mark: ${num(result.earned_points)} / ${num(result.total_points)}.`,
          kind: "success",
        });
        onSaved();
      }
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setRunning(false);
    }
  }

  const button = "rounded-md px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-60";
  return (
    <div data-testid="test-run-panel">
      <div className="flex flex-wrap gap-2">
        {isChallenge && (
          <button
            type="button"
            onClick={() => start(true)}
            disabled={running}
            title="Runs every test again and saves the points of the tests passed as the mark, replacing any earlier mark (a student's code is already marked when they press Submit)"
            className={`${button} bg-blue-600 hover:bg-blue-700`}
          >
            {running ? "Running…" : `Run ${testCount} test${testCount === 1 ? "" : "s"} and save as mark`}
          </button>
        )}
        <button
          type="button"
          onClick={() => start(false)}
          disabled={running}
          className={`${button} ${isChallenge ? "bg-gray-600 hover:bg-gray-700" : "bg-blue-600 hover:bg-blue-700"}`}
        >
          {running ? "Running…" : isChallenge ? "Run without saving" : run ? "Run again" : `Run ${testCount} test${testCount === 1 ? "" : "s"}`}
        </button>
      </div>
      {running && (
        <p className="mt-2 text-xs text-gray-600">
          Running each test in the sandbox: this takes a few seconds per test. Keep this page open.
        </p>
      )}
      <Message state={msg} />
      {run && (
        <div className="mt-3">
          <p className="text-sm font-semibold" data-testid="test-run-summary">
            {run.passed} / {run.total} tests passed · {num(run.earned_points)} / {num(run.total_points)} points
            {run.questions.length <= 1 && (
              <span className="ml-2 text-xs font-normal text-gray-500">
                ran {run.file} ({run.language})
              </span>
            )}
          </p>
          {run.questions.length > 1 ? (
            run.questions.map((q) => (
              <section key={q.question} className="mt-3" data-testid="test-run-question">
                <h4 className="text-sm font-semibold">
                  {taskName({ id: q.question, title: q.title })}
                  <span className="ml-2 text-xs font-normal text-gray-500">
                    {q.answered
                      ? `${q.passed} / ${q.total} tests · ${num(q.earned_points)} / ${num(q.total_points)} points · ran ${q.file} (${q.language})`
                      : `no code was submitted · 0 / ${num(q.total_points)} points`}
                  </span>
                </h4>
                {q.answered && (
                  <ul className="mt-2 space-y-2">
                    {run.results
                      .filter((r) => r.question === q.question)
                      .map((r) => (
                        <TestRow key={r.test_id} r={r} />
                      ))}
                  </ul>
                )}
              </section>
            ))
          ) : (
            <ul className="mt-2 space-y-2">
              {run.results.map((r) => (
                <TestRow key={r.test_id} r={r} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
