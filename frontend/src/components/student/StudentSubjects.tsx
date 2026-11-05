"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch, getToken, setSession, StudentSubject, UserInfo } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";

function SubjectDetails({ subject }: { subject: StudentSubject }) {
  return (
    <>
      <span className="block text-lg font-bold">{subject.name}</span>
      <span className="block text-xs text-gray-500">
        {subject.code}
        {subject.batch ? ` · Batch ${subject.batch}` : ""}
      </span>
      {subject.instructors.length > 0 && (
        <span className="mt-1 block text-xs text-gray-500">{subject.instructors.join(", ")}</span>
      )}
    </>
  );
}

/** A subject the student is not in: its assignments stay closed until they join with the instructor's password. */
function LockedSubject({ subject, onJoined }: { subject: StudentSubject; onJoined: (s: StudentSubject) => void }) {
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
    <li className="rounded-lg border border-gray-200 bg-gray-50 p-5" data-testid="locked-subject">
      <SubjectDetails subject={subject} />
      <span className="mt-2 inline-block rounded bg-gray-200 px-2 py-0.5 text-xs font-semibold text-gray-700">
        Not joined · assignments are hidden
      </span>
      {subject.registration_open ? (
        <form onSubmit={join} className="mt-3">
          <label className="block text-xs font-semibold" htmlFor={`join-password-${subject.id}`}>
            Password from your instructor
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id={`join-password-${subject.id}`}
              required
              value={password}
              maxLength={100}
              autoComplete="off"
              onChange={(e) => setPassword(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm"
            />
            <button
              disabled={busy}
              className="btn-primary rounded-md px-4 py-1.5 text-sm font-semibold disabled:opacity-60"
            >
              {busy ? "Joining..." : "Join"}
            </button>
          </div>
        </form>
      ) : (
        <p className="mt-3 text-xs font-semibold text-gray-600" data-testid="registration-closed">
          Registration not open yet. Your instructor has to allow it first.
        </p>
      )}
      <Message state={msg} />
    </li>
  );
}

/**
 * Every subject there is (GET /student/subjects), as boxes. A subject the student joined opens its own page with its
 * assignments (/student/subjects/<id>). One they have not joined stays locked: it shows a password box once the
 * instructor allowed registration (POST /student/subjects/{id}/join), or says that registration is not open yet.
 */
export default function StudentSubjects() {
  // null until the first load.
  const [subjects, setSubjects] = useState<StudentSubject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<MessageState>(null);

  const load = useCallback(async () => {
    try {
      setSubjects(await apiFetch<StudentSubject[]>("/student/subjects"));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function joined(s: StudentSubject) {
    // The login keeps a copy of the account, so refresh it: the subject is now one of theirs.
    try {
      const me = await apiFetch<UserInfo>("/auth/me");
      const token = getToken();
      if (token) setSession(token, me);
    } catch {
      /* the list below is what counts */
    }
    setNotice({ text: `You joined ${s.name}. Open it to see its assignments.`, kind: "success" });
    await load();
  }

  const mine = (subjects ?? []).filter((s) => s.joined);

  return (
    <section className="mt-6" data-testid="student-subjects">
      <h2 className="text-xl font-semibold">Subjects</h2>
      <p className="mt-1 text-sm text-gray-600">
        Every subject is listed. Open one you have joined to see its assignments. To join another, type the password
        your instructor gave you once registration is open.
      </p>
      <Message state={notice} />
      {loadError && (
        <p role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load the subjects: {loadError}
        </p>
      )}
      {subjects !== null && subjects.length === 0 && !loadError && (
        <p className="empty-state mt-2">There are no subjects yet.</p>
      )}
      {subjects !== null && subjects.length > 0 && (
        <>
          {mine.length === 0 && (
            <p className="empty-state mt-3">You have not joined any subject yet. Join one below to see its assignments.</p>
          )}
          <ul className="mt-4 grid gap-4 sm:grid-cols-2" data-testid="student-subject-list">
            {subjects.map((s) =>
              s.joined ? (
                <li key={s.id}>
                  <Link
                    href={`/student/subjects/${s.id}`}
                    className="block h-full rounded-lg border border-gray-200 bg-white p-5 shadow-sm hover:border-blue-500 hover:bg-blue-50"
                    data-testid="subject-card"
                  >
                    <SubjectDetails subject={s} />
                    <span className="mt-2 inline-block rounded bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-800">
                      Joined · open
                    </span>
                  </Link>
                </li>
              ) : (
                <LockedSubject key={s.id} subject={s} onJoined={joined} />
              ),
            )}
          </ul>
        </>
      )}
    </section>
  );
}
