"use client";

import { FormEvent, useState } from "react";
import { apiFetch, getToken, setSession, StudentSubject, UserInfo } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";

/**
 * The password box of a subject the student has not joined (POST /student/subjects/{id}/join). A right password
 * enrols them and the page is reloaded, so it comes back as the subject's own page with its teachers and
 * assignments. Until the instructor allows registration there is nothing to type, and it says so.
 */
export default function JoinForm({ subject }: { subject: StudentSubject }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  if (!subject.registration_open) {
    return (
      <p className="empty-state mt-4" data-testid="registration-closed">
        Registration for this subject is closed right now (not opened yet, or its end date has passed). Ask your
        instructor to open it and give you the password.
      </p>
    );
  }

  async function join(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/student/subjects/${subject.id}/join`, { method: "POST", json: { password } });
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
      setBusy(false);
      return;
    }
    // The login keeps a copy of the account: refresh it, then reload the page as a joined student.
    try {
      const me = await apiFetch<UserInfo>("/auth/me");
      const token = getToken();
      if (token) setSession(token, me);
    } catch {
      /* the reload below is what counts */
    }
    window.location.reload();
  }

  return (
    <form onSubmit={join} className="card mt-4 max-w-md" data-testid="join-form">
      <h2 className="text-lg font-semibold">Join this subject</h2>
      <p className="mt-1 text-sm text-gray-600">
        Enter the password your instructor gave you to see the subject&apos;s teachers and assignments.
      </p>
      {subject.registration_ends_at && (
        <p className="mt-1 text-sm font-semibold text-amber-800" data-testid="registration-ends">
          Registration closes on {formatDateTime(subject.registration_ends_at)}.
        </p>
      )}
      <label className="mt-3 block text-sm font-semibold" htmlFor="join-password">
        Password
      </label>
      <input
        id="join-password"
        required
        value={password}
        maxLength={100}
        autoComplete="off"
        onChange={(e) => setPassword(e.target.value)}
        className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
      />
      <button disabled={busy} className="btn-primary mt-3 rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-60">
        {busy ? "Checking..." : "Join subject"}
      </button>
      <Message state={msg} />
    </form>
  );
}
