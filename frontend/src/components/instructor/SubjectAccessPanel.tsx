"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch, SubjectAccess } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";

/**
 * "Student access" of one subject: the instructor sets a password and opens the subject to students. Every
 * student then sees it under "Join a subject" and gets in by typing the password (GET/PUT
 * /instructor/subjects/{id}/access). Closing it stops new students joining; the ones already in stay.
 */
export default function SubjectAccessPanel({ subjectId }: { subjectId: number }) {
  const [saved, setSaved] = useState<SubjectAccess | null>(null);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<SubjectAccess>(`/instructor/subjects/${subjectId}/access`)
      .then((a) => {
        if (cancelled) return;
        setSaved(a);
        setOpen(a.open);
        setPassword(a.password);
      })
      .catch((err) => !cancelled && setMsg({ text: `Could not load: ${err instanceof Error ? err.message : err}`, kind: "error" }));
    return () => {
      cancelled = true;
    };
  }, [subjectId]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      const a = await apiFetch<SubjectAccess>(`/instructor/subjects/${subjectId}/access`, {
        method: "PUT",
        json: { open, password },
      });
      setSaved(a);
      setOpen(a.open);
      setPassword(a.password);
      setMsg({
        text: a.open
          ? "Saved. Students can now see this subject and join it with the password."
          : "Saved. The subject is closed: no new students can join.",
        kind: "success",
      });
    } catch (err) {
      setMsg({ text: `Could not save: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm" data-testid="subject-access">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold">Student access</h2>
        {saved && (
          <span
            className={`rounded px-2 py-0.5 text-xs font-semibold ${
              saved.open ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-700"
            }`}
            data-testid="subject-access-status"
          >
            {saved.open ? "Open to students" : "Closed"}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-gray-600">
        Students are not added to a subject by the admin. Set a password and open the subject: students then see it
        under &ldquo;Join a subject&rdquo; and get in by typing the password. Share the password with them yourself.
      </p>
      <form onSubmit={save} className="mt-3">
        <label className="block text-sm font-semibold" htmlFor="subject-join-password">
          Password for students
        </label>
        <input
          id="subject-join-password"
          value={password}
          maxLength={100}
          autoComplete="off"
          onChange={(e) => setPassword(e.target.value)}
          placeholder="e.g. cs101-2026"
          className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm sm:max-w-sm"
          data-testid="subject-join-password"
        />
        <label className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <input
            type="checkbox"
            checked={open}
            onChange={(e) => setOpen(e.target.checked)}
            className="h-4 w-4"
            data-testid="subject-open-toggle"
          />
          Open this subject to students
        </label>
        <button
          disabled={saving || saved === null}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <Message state={msg} />
      </form>
    </section>
  );
}
