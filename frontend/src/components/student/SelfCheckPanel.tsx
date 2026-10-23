"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiFetch,
  MySubmission,
  SelfCheck,
  SelfCheckBand,
  SelfCheckKind,
  SelfCheckStatus,
  StudentAssignment,
} from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";

const BAND_STYLE: Record<SelfCheckBand, { cls: string; similarity: string; ai: string }> = {
  low: { cls: "bg-green-100 text-green-800 border-green-300", similarity: "Low similarity", ai: "Low likelihood" },
  moderate: {
    cls: "bg-yellow-100 text-yellow-800 border-yellow-300",
    similarity: "Moderate similarity",
    ai: "Moderate likelihood",
  },
  high: { cls: "bg-red-100 text-red-800 border-red-300", similarity: "High similarity", ai: "High likelihood" },
};

const HIGHLIGHT_BORDER: Record<SelfCheckBand, string> = {
  low: "border-green-400",
  moderate: "border-yellow-400",
  high: "border-red-400",
};

const CHECKS: { kind: SelfCheckKind; label: string; button: string }[] = [
  { kind: "code_similarity", label: "Code similarity", button: "Check my code" },
  { kind: "report_similarity", label: "Report similarity", button: "Check my report" },
  { kind: "ai_content", label: "AI-content detection", button: "Check for AI content" },
];

function Band({ band, ai = false }: { band: SelfCheckBand; ai?: boolean }) {
  const style = BAND_STYLE[band];
  return (
    <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${style.cls}`}>
      {ai ? style.ai : style.similarity}
    </span>
  );
}

// What each band means for the student. Similarity is symmetric -- an original
// author matches whoever copied them -- so "high" never reads as an accusation.
const MEANING: Record<SelfCheckBand, { code: string; report: string }> = {
  high: {
    code: "Your code closely matches at least one other submission. If this is your own work, you don't need to do anything: your instructor reviews every match.",
    report: "Your report closely matches at least one other report. If this is your own work, you don't need to do anything: your instructor reviews every match.",
  },
  moderate: {
    code: "Parts of your code are more similar to another submission than is usual for this assignment. Check that the highlighted parts are your own work.",
    report: "Parts of your report are more similar to another report than is usual for this assignment. Check that the highlighted passages are your own words or properly cited.",
  },
  low: {
    code: "Your code doesn't stand out: it only shares the kind of patterns most solutions to this assignment have.",
    report: "Your report doesn't stand out: it only shares the kind of wording most reports for this assignment have.",
  },
};

function SimilarityResult({ check }: { check: SelfCheck }) {
  const r = check.result!;
  const band = r.band ?? "low";
  const part = check.kind === "code_similarity" ? "code" : "report";
  return (
    <div className="mt-2 text-sm">
      <p>
        <Band band={band} />{" "}
        {r.note ? r.note : `Compared with ${r.compared} other submission(s); ${r.similar_submissions} stand out as similar.`}
      </p>
      {!r.note && <p className="mt-1 text-gray-700">{MEANING[band][part]}</p>}
      {check.kind === "code_similarity" && (r.highlights?.length ?? 0) > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-gray-700">Parts of your code with potential matches</p>
          {r.highlights!.map((h, i) => (
            <div key={i} className="mt-1">
              <p className="text-xs text-gray-500">
                {h.file}, lines {h.start_line}–{h.end_line}
                {h.truncated ? " (first lines shown)" : ""}
              </p>
              <pre
                className={`overflow-x-auto rounded border-l-4 bg-gray-50 px-3 py-2 text-xs ${HIGHLIGHT_BORDER[band]}`}
              >
                {h.text}
              </pre>
            </div>
          ))}
        </div>
      )}
      {check.kind === "report_similarity" && (r.passages?.length ?? 0) > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-gray-700">Passages of your report with potential matches</p>
          {r.passages!.map((text, i) => (
            <blockquote
              key={i}
              className={`mt-1 border-l-4 bg-gray-50 px-3 py-2 text-xs text-gray-700 ${HIGHLIGHT_BORDER[band]}`}
            >
              {text}
            </blockquote>
          ))}
        </div>
      )}
      <p className="mt-2 text-xs text-gray-500">
        An indicator, not proof of plagiarism: common code patterns and shared course material can match too. Your
        instructor reviews every result and it never changes your mark by itself.
      </p>
    </div>
  );
}

function AiResult({ check }: { check: SelfCheck }) {
  const r = check.result!;
  return (
    <div className="mt-2 text-sm">
      <ul className="space-y-1">
        <li>
          Report: {r.report ? <Band band={r.report} ai /> : <span className="text-gray-500">not assessed</span>}
        </li>
        <li>
          Code: {r.code ? <Band band={r.code} ai /> : <span className="text-gray-500">not assessed</span>}
        </li>
      </ul>
      <p className="mt-2 text-xs text-gray-500">
        Statistical estimates of machine-generated text. They can be wrong, especially for formal or non-native
        English writing and for tidy code, and they never change your mark.
      </p>
    </div>
  );
}

// A hidden result is remembered per check (by its id), so it stays hidden after a
// reload but a NEW check of that kind shows again.
const HIDDEN_KEY = "selfcheck.hidden";

function readHidden(): number[] {
  try {
    const raw = window.localStorage.getItem(HIDDEN_KEY);
    return raw ? (JSON.parse(raw) as number[]) : [];
  } catch {
    return [];
  }
}

function writeHidden(ids: number[]) {
  try {
    window.localStorage.setItem(HIDDEN_KEY, JSON.stringify(ids.slice(-200)));
  } catch {
    // storage unavailable: hiding still works until the page is reloaded
  }
}

/** "Check my submission": similarity and AI-content self-checks while the assignment is open. */
export default function SelfCheckPanel({ assignment, submission }: { assignment: StudentAssignment; submission: MySubmission }) {
  const [status, setStatus] = useState<SelfCheckStatus | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [starting, setStarting] = useState<SelfCheckKind | null>(null);
  const [hidden, setHidden] = useState<number[]>([]);

  useEffect(() => setHidden(readHidden()), []);

  function toggleHidden(checkId: number) {
    const next = hidden.includes(checkId) ? hidden.filter((id) => id !== checkId) : [...hidden, checkId];
    setHidden(next);
    writeHidden(next);
  }

  const load = useCallback(async () => {
    try {
      setStatus(await apiFetch<SelfCheckStatus>(`/submissions/${submission.id}/self-checks`));
    } catch (err) {
      setMsg({ text: `Could not load your checks: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }, [submission.id]);

  useEffect(() => {
    load();
  }, [load, submission.submitted_at]);

  // Poll while any check is still running.
  const running = status ? CHECKS.some((c) => status.latest[c.kind]?.status === "running") : false;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  async function start(kind: SelfCheckKind) {
    setMsg(null);
    setStarting(kind);
    try {
      await apiFetch(`/submissions/${submission.id}/self-checks`, { method: "POST", json: { kind } });
      await load();
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setStarting(null);
    }
  }

  if (!status || !status.can_run || !(status.similarity_enabled || status.ai_enabled)) return null;

  const available = CHECKS.filter((c) =>
    c.kind === "ai_content"
      ? status.ai_enabled && (submission.has_code || submission.has_report)
      : status.similarity_enabled && (c.kind === "code_similarity" ? submission.has_code : submission.has_report),
  );
  if (available.length === 0) return null;

  return (
    <div className="mt-4 rounded-md border border-blue-100 bg-blue-50/40 p-4" data-testid="self-check-panel">
      <h4 className="font-bold">Check my submission</h4>
      <p className="mt-1 text-xs text-gray-600">
        Available until the deadline ({formatDateTime(assignment.deadline)}). You can run each check{" "}
        {status.limit_per_hour} times per hour. Results show only your own work.
      </p>
      <div className="mt-3 space-y-4">
        {available.map((c) => {
          const check = status.latest[c.kind];
          const busy = check?.status === "running" || starting === c.kind;
          const left = status.remaining[c.kind];
          return (
            <div key={c.kind} className="rounded-md border border-gray-200 bg-white p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold">{c.label}</p>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">
                    {left} of {status.limit_per_hour} left this hour
                  </span>
                  <button
                    type="button"
                    onClick={() => start(c.kind)}
                    disabled={busy || left === 0}
                    className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {busy ? "Checking..." : c.button}
                  </button>
                </div>
              </div>
              {check?.status === "running" && (
                <p className="mt-2 text-xs text-gray-600">
                  {c.kind === "ai_content"
                    ? "Checking... this can take about a minute."
                    : "Comparing with the other submissions..."}
                </p>
              )}
              {check?.status === "failed" && <p className="mt-2 text-sm text-red-700">{check.error}</p>}
              {check?.status === "done" && check.result && (
                <>
                  {!hidden.includes(check.id) &&
                    (c.kind === "ai_content" ? <AiResult check={check} /> : <SimilarityResult check={check} />)}
                  <div className="mt-1 flex flex-wrap items-center gap-3">
                    <span className="text-xs text-gray-400">
                      Checked {formatDateTime(check.finished_at ?? check.created_at)}
                    </span>
                    <button
                      type="button"
                      onClick={() => toggleHidden(check.id)}
                      aria-expanded={!hidden.includes(check.id)}
                      className="text-xs font-semibold text-blue-700 hover:underline"
                    >
                      {hidden.includes(check.id) ? "Show result" : "Hide result"}
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
      <Message state={msg} />
    </div>
  );
}
