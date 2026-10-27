"use client";

import { useState } from "react";
import { apiFetch, TestResult, TestRun } from "@/lib/api";
import Badge from "@/components/Badge";
import Message, { MessageState } from "@/components/Message";

const STATUS: Record<TestResult["status"], { label: string; tone: string }> = {
  passed: { label: "Passed", tone: "bg-green-50 text-green-800" },
  failed: { label: "Wrong output", tone: "bg-red-50 text-red-700" },
  error: { label: "Crashed", tone: "bg-red-50 text-red-700" },
  timeout: { label: "Timed out", tone: "bg-yellow-50 text-yellow-800" },
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
export default function TestRunPanel({ submissionId, testCount }: { submissionId: number; testCount: number }) {
  const [run, setRun] = useState<TestRun | null>(null);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  async function start() {
    setMsg(null);
    setRun(null);
    setRunning(true);
    try {
      setRun(await apiFetch<TestRun>(`/submissions/${submissionId}/run-tests`, { method: "POST" }));
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div data-testid="test-run-panel">
      <button
        type="button"
        onClick={start}
        disabled={running}
        className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {running ? "Running…" : run ? "Run again" : `Run ${testCount} test${testCount === 1 ? "" : "s"}`}
      </button>
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
            <span className="ml-2 text-xs font-normal text-gray-500">
              ran {run.file} ({run.language})
            </span>
          </p>
          <ul className="mt-2 space-y-2">
            {run.results.map((r) => (
              <TestRow key={r.test_id} r={r} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
