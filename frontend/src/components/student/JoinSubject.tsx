"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch, OpenSubject } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";

function JoinRow({ subject, onJoined }: { subject: OpenSubject; onJoined: (s: OpenSubject) => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  async function join(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/student/subjects/${subject.id}/join`, { method: "POST", json: { password } });
      onJoined(subject);
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
      setBusy(false);
    }
  }

  return (
    <li className="px-4 py-3" data-testid="open-subject">
      <form onSubmit={join} className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="font-semibold">
            {subject.name} <span className="font-normal text-gray-600">({subject.code})</span>
          </span>
          <span className="block text-xs text-gray-500">
            {subject.batch ? `Batch ${subject.batch}` : "All batches"}
            {subject.instructors.length > 0 && ` · ${subject.instructors.join(", ")}`}
          </span>
        </div>
        <div className="flex items-end gap-2">
          <div>
            <label className="block text-xs font-semibold" htmlFor={`join-password-${subject.id}`}>
              Password from your instructor
            </label>
            <input
              id={`join-password-${subject.id}`}
              required
              value={password}
              maxLength={100}
              autoComplete="off"
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-48 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
            />
          </div>
          <button
            disabled={busy}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {busy ? "Joining..." : "Join"}
          </button>
        </div>
      </form>
      <Message state={msg} />
    </li>
  );
}

/**
 * "Join a subject": the subjects the instructors have opened (GET /student/open-subjects), each joined by typing
 * its password (POST /student/subjects/{id}/join). `onJoined` runs after a join so the page can show the subject.
 */
export default function JoinSubject({ onJoined }: { onJoined: (s: OpenSubject) => void | Promise<void> }) {
  // null until the first load.
  const [subjects, setSubjects] = useState<OpenSubject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<MessageState>(null);

  const load = useCallback(async () => {
    try {
      setSubjects(await apiFetch<OpenSubject[]>("/student/open-subjects"));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function joined(s: OpenSubject) {
    setNotice({ text: `You joined ${s.name}.`, kind: "success" });
    await onJoined(s);
    await load();
  }

  return (
    <section className="mt-6" data-testid="join-subject">
      <h2 className="text-lg font-bold">Join a subject</h2>
      <p className="mt-1 text-sm text-gray-600">
        Your instructor opens a subject and gives you its password. Type it next to the subject to join.
      </p>
      <Message state={notice} />
      {loadError && (
        <p role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load the subjects: {loadError}
        </p>
      )}
      {subjects !== null && subjects.length === 0 && !loadError && (
        <p className="mt-2 text-sm text-gray-600">No subjects are open to join right now.</p>
      )}
      {subjects !== null && subjects.length > 0 && (
        <ul className="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white text-sm shadow-sm">
          {subjects.map((s) => (
            <JoinRow key={s.id} subject={s} onJoined={joined} />
          ))}
        </ul>
      )}
    </section>
  );
}
