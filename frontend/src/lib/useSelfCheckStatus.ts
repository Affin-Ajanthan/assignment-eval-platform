"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, SelfCheckKind, SelfCheckStatus } from "@/lib/api";
import { MessageState } from "@/components/Message";
import { CHECKS } from "@/lib/selfCheckBands";

/** One submission's self-checks: loads them, polls while one is running, starts new ones. */
export function useSelfCheckStatus(submissionId: number, submittedAt: string) {
  const [status, setStatus] = useState<SelfCheckStatus | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [starting, setStarting] = useState<SelfCheckKind | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await apiFetch<SelfCheckStatus>(`/submissions/${submissionId}/self-checks`));
    } catch (err) {
      setMsg({ text: `Could not load your checks: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }, [submissionId]);

  // Reload when the submission changes (e.g. the student replaced a file).
  useEffect(() => {
    load();
  }, [load, submittedAt]);

  // Poll while any check is still running.
  const running = status ? CHECKS.some((c) => status.latest[c.kind]?.status === "running") : false;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  // A used-up check frees up at its next_available time: reload then, so its button comes back on its own.
  const nextFree = Object.values(status?.next_available ?? {})
    .filter((t): t is string => !!t)
    .map((t) => new Date(t).getTime())
    .sort((a, b) => a - b)[0];
  useEffect(() => {
    if (nextFree === undefined) return;
    const timer = window.setTimeout(load, Math.max(0, nextFree - Date.now()) + 1000);
    return () => window.clearTimeout(timer);
  }, [nextFree, load]);

  async function start(kind: SelfCheckKind) {
    setMsg(null);
    setStarting(kind);
    try {
      await apiFetch(`/submissions/${submissionId}/self-checks`, { method: "POST", json: { kind } });
      await load();
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setStarting(null);
    }
  }

  return { status, msg, starting, start };
}
