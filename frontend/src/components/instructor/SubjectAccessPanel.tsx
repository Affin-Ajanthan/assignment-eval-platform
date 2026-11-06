"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch, SubjectAccess } from "@/lib/api";
import { combineLocal, formatDateTime, splitLocal } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";

/**
 * "Student access" of one subject: every student sees the subject as soon as it exists. The instructor sets a
 * password and allows registration, and from then on a student gets in by typing the password
 * (GET/PUT /instructor/subjects/{id}/access). An end date is optional: registration then closes by itself at that
 * time, and is opened again by saving a later date, with the same password or a new one. Switching registration
 * off, a new password or an end date never removes the students who already joined; a new password only means the
 * old one stops working.
 */
export default function SubjectAccessPanel({ subjectId }: { subjectId: number }) {
  const [saved, setSaved] = useState<SubjectAccess | null>(null);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [endDate, setEndDate] = useState(""); // local "YYYY-MM-DD", "" for no end date
  const [endTime, setEndTime] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  /** Puts a saved state into the form. A registration that ended is shown as switched on, with its old date to replace. */
  function show(a: SubjectAccess) {
    setSaved(a);
    setOpen(a.open || a.expired);
    setPassword(a.password);
    const split = a.ends_at ? splitLocal(a.ends_at) : { date: "", time: "" };
    setEndDate(split.date);
    setEndTime(split.time);
  }

  useEffect(() => {
    let cancelled = false;
    apiFetch<SubjectAccess>(`/instructor/subjects/${subjectId}/access`)
      .then((a) => {
        if (!cancelled) show(a);
      })
      .catch((err) => !cancelled && setMsg({ text: `Could not load: ${err instanceof Error ? err.message : err}`, kind: "error" }));
    return () => {
      cancelled = true;
    };
  }, [subjectId]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    let ends_at: string | null = null;
    if (endDate || endTime) {
      const when = combineLocal(endDate, endTime);
      if (!when) {
        setMsg({ text: "Give both the date and the time registration ends, or clear both.", kind: "error" });
        return;
      }
      ends_at = when.toISOString();
    }
    setSaving(true);
    try {
      const a = await apiFetch<SubjectAccess>(`/instructor/subjects/${subjectId}/access`, {
        method: "PUT",
        json: { open, password, ends_at },
      });
      show(a);
      setMsg({
        text: a.open
          ? a.ends_at
            ? `Saved. Students can register with the password until ${formatDateTime(a.ends_at)}.`
            : "Saved. Students can now register for this subject with the password."
          : "Saved. Registration is off: no new students can join.",
        kind: "success",
      });
    } catch (err) {
      setMsg({ text: `Could not save: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  const badge = !saved
    ? null
    : saved.open
      ? { text: saved.ends_at ? `Registration open until ${formatDateTime(saved.ends_at)}` : "Registration open", tone: "bg-green-100 text-green-800" }
      : saved.expired
        ? { text: `Registration ended ${formatDateTime(saved.ends_at)}`, tone: "bg-amber-100 text-amber-800" }
        : { text: "Registration closed", tone: "bg-gray-100 text-gray-700" };

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm" data-testid="subject-access">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold">Student access</h2>
        {badge && (
          <span className={`rounded px-2 py-0.5 text-xs font-semibold ${badge.tone}`} data-testid="subject-access-status">
            {badge.text}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-gray-600">
        Every student sees this subject. Set a password and allow registration: students can then join by typing the
        password, until the end date if you set one. Share the password with them yourself. To open registration again
        after it ended, save a later date (or none), with the same password or a new one. Students who already joined
        stay in whatever you change; a new password only stops the old one from working.
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
        <label className="block text-sm font-semibold" htmlFor="subject-end-date">
          Registration ends <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <div className="mt-1 mb-3 flex flex-wrap items-center gap-2">
          <input
            id="subject-end-date"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
            data-testid="subject-end-date"
          />
          <input
            type="time"
            aria-label="Registration end time"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
            data-testid="subject-end-time"
          />
          {(endDate || endTime) && (
            <button
              type="button"
              onClick={() => {
                setEndDate("");
                setEndTime("");
              }}
              className="text-sm font-semibold text-blue-700 hover:underline"
            >
              Remove end date
            </button>
          )}
        </div>
        <label className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <input
            type="checkbox"
            checked={open}
            onChange={(e) => setOpen(e.target.checked)}
            className="h-4 w-4"
            data-testid="subject-open-toggle"
          />
          Allow students to register for this subject
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
