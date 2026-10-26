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
