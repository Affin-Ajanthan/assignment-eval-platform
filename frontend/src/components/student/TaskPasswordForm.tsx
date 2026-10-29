"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";

/**
 * The password the instructor set for a code challenge, asked when the student presses Do task. The server
 * checks it (POST /assignments/{id}/unlock-tasks) and only then sends the questions; `onUnlocked` is called
 * once it accepted the password.
 */
export default function TaskPasswordForm({
  assignmentId,
  onUnlocked,
}: {
  assignmentId: number;
  onUnlocked: () => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<MessageState>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password.trim()) return setMsg({ text: "Enter the password.", kind: "error" });
    setMsg(null);
    setBusy(true);
    try {
      await apiFetch(`/assignments/${assignmentId}/unlock-tasks`, { method: "POST", json: { password } });
      await onUnlocked();
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 max-w-sm" noValidate data-testid="task-password-form">
      <label className="block text-sm font-semibold" htmlFor="task-password-input">
        Password
      </label>
      <p className="text-xs text-gray-600">Your instructor gives you the password to start the tasks.</p>
      <input
        id="task-password-input"
        type="password"
        autoComplete="off"
        autoFocus
        value={password}
        maxLength={200}
        disabled={busy}
        onChange={(e) => setPassword(e.target.value)}
        className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
      />
      <button
        type="submit"
        disabled={busy}
        className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        data-testid="task-password-submit"
      >
        {busy ? "Checking…" : "Start"}
      </button>
      <Message state={msg} />
    </form>
  );
}
