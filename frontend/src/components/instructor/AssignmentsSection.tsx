"use client";

import { FormEvent, useState } from "react";
import { apiFetch, Assignment, AssignmentStatus, Rubric } from "@/lib/api";
import { combineLocal, formatDateTime, splitLocal } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";

const STATUS_STYLE: Record<AssignmentStatus, { text: string; cls: string }> = {
  upcoming: { text: "Not yet open", cls: "bg-gray-100 text-gray-700" },
  open: { text: "Open", cls: "bg-green-50 text-green-800" },
  closed: { text: "Closed", cls: "bg-yellow-50 text-yellow-800" },
};

type FormState = {
  name: string;
  description: string;
  fromDate: string;
  fromTime: string;
  dueDate: string;
  dueTime: string;
  rubricId: string; // "" = no rubric
};

const EMPTY: FormState = { name: "", description: "", fromDate: "", fromTime: "", dueDate: "", dueTime: "", rubricId: "" };

const input = "mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm";

export default function AssignmentsSection({
  subjectId,
  assignments,
  rubrics,
  onChanged,
}: {
  subjectId: number;
  assignments: Assignment[];
  rubrics: Rubric[];
  onChanged: () => Promise<void>;
}) {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function startEdit(a: Assignment) {
    const from = splitLocal(a.available_from);
    const due = splitLocal(a.deadline);
    setEditingId(a.id);
    setMsg(null);
    setForm({
      name: a.name,
      description: a.description,
      fromDate: from.date,
      fromTime: from.time,
      dueDate: due.date,
      dueTime: due.time,
      rubricId: a.rubric_id ? String(a.rubric_id) : "",
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY);
    setMsg(null);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    // Same checks the API enforces, so the instructor gets a clear message early.
    if (!form.name.trim()) return setMsg({ text: "Assignment name is required.", kind: "error" });
    const from = combineLocal(form.fromDate, form.fromTime);
    const due = combineLocal(form.dueDate, form.dueTime);
    if (!from) return setMsg({ text: "Enter a valid 'available from' date and time.", kind: "error" });
    if (!due) return setMsg({ text: "Enter a valid submission deadline date and time.", kind: "error" });
    if (due <= from) {
      return setMsg({ text: "The submission deadline must be later than the available-from date and time.", kind: "error" });
    }

    const body = {
      name: form.name.trim(),
      description: form.description,
      available_from: from.toISOString(),
      deadline: due.toISOString(),
      rubric_id: form.rubricId ? parseInt(form.rubricId, 10) : null,
    };
    setSaving(true);
    try {
      if (editingId === null) {
        await apiFetch("/assignments", { method: "POST", json: { ...body, subject_id: subjectId } });
        setMsg({ text: "Assignment saved.", kind: "success" });
      } else {
        await apiFetch(`/assignments/${editingId}`, { method: "PUT", json: body });
        setMsg({ text: "Assignment updated.", kind: "success" });
      }
      setEditingId(null);
      setForm(EMPTY);
      await onChanged();
    } catch (err) {
      setMsg({ text: `Failed to save assignment: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  function askDelete(a: Assignment) {
    setConfirm({
      title: `Delete "${a.name}"?`,
      message:
        "Are you sure you want to delete this assignment? Students will no longer see it or be able to submit to it." +
        (a.submission_count
          ? `\n\nIts ${a.submission_count} existing submission(s) and any grades are kept as records under the name "${a.name}".`
          : ""),
      onConfirm: async () => {
        setConfirmBusy(true);
        try {
          await apiFetch(`/assignments/${a.id}`, { method: "DELETE" });
          if (editingId === a.id) cancelEdit();
          setMsg({ text: `Assignment "${a.name}" deleted.`, kind: "success" });
          await onChanged();
        } catch (err) {
          setMsg({ text: `Failed to delete assignment: ${err instanceof Error ? err.message : err}`, kind: "error" });
        } finally {
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  const selectedRubric = rubrics.find((r) => String(r.id) === form.rubricId);

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Assignments</h2>
      <p className="mt-1 text-sm text-gray-600">
        Enter the details, set when submissions open and close, and choose the rubric used to grade it (create rubrics
        below).
      </p>

      <form onSubmit={handleSave} className="mt-3" noValidate>
        <h3 className="text-sm font-bold">{editingId === null ? "Create assignment" : "Edit assignment"}</h3>
        <label className="mt-2 block text-sm font-semibold" htmlFor="assignment-name">
          Assignment name
        </label>
        <input
          id="assignment-name"
          required
          maxLength={200}
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Assignment 1"
          className={input}
        />

        <label className="mt-3 block text-sm font-semibold" htmlFor="assignment-description">
          Description / instructions
        </label>
        <textarea
          id="assignment-description"
          rows={4}
          maxLength={10000}
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          placeholder="Enter assignment instructions here..."
          className={input}
        />

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <fieldset>
            <legend className="text-sm font-semibold">Available from</legend>
            <div className="flex gap-2">
              <input
                type="date"
                aria-label="Available from date"
                value={form.fromDate}
                onChange={(e) => set("fromDate", e.target.value)}
                className={input}
              />
              <input
                type="time"
                aria-label="Available from time"
                value={form.fromTime}
                onChange={(e) => set("fromTime", e.target.value)}
                className={input}
              />
            </div>
          </fieldset>
          <fieldset>
            <legend className="text-sm font-semibold">Submission deadline</legend>
            <div className="flex gap-2">
              <input
                type="date"
                aria-label="Deadline date"
                value={form.dueDate}
                onChange={(e) => set("dueDate", e.target.value)}
                className={input}
              />
              <input
                type="time"
                aria-label="Deadline time"
                value={form.dueTime}
                onChange={(e) => set("dueTime", e.target.value)}
                className={input}
              />
            </div>
          </fieldset>
        </div>
        <p className="mt-1 text-xs text-gray-500">Times are in your local time zone.</p>

        <label className="mt-3 block text-sm font-semibold" htmlFor="assignment-rubric">
          Rubric
        </label>
        <select
          id="assignment-rubric"
          value={form.rubricId}
          onChange={(e) => set("rubricId", e.target.value)}
          className={input}
        >
          <option value="">— No rubric yet —</option>
          {rubrics.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} ({r.criteria.length} criteria, {r.max_total} pts)
            </option>
          ))}
        </select>
        {selectedRubric && (
          <p className="mt-1 text-xs text-gray-600">
            Criteria: {selectedRubric.criteria.map((c) => `${c.name} (${c.max_points})`).join(", ")} — total{" "}
            {selectedRubric.max_total} points.
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? "Saving..." : editingId === null ? "Save assignment" : "Update assignment"}
          </button>
          {editingId !== null && (
            <button
              type="button"
              onClick={cancelEdit}
              className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
            >
              Cancel edit
            </button>
          )}
        </div>
        <Message state={msg} />
      </form>

      <h3 className="mt-6 text-sm font-bold uppercase tracking-wide text-gray-500">Assignments in this subject</h3>
      {assignments.length === 0 ? (
        <p className="mt-2 text-sm text-gray-600">No assignments yet.</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {assignments.map((a) => (
            <li key={a.id} className="rounded-md border border-gray-200 p-4" data-testid="assignment-card">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h4 className="font-bold">{a.name}</h4>
                  <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[a.status].cls}`}>
                    {STATUS_STYLE[a.status].text}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => startEdit(a)}
                    className="rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => askDelete(a)}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700"
                  >
                    Delete
                  </button>
                </div>
              </div>
              {a.description && <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{a.description}</p>}
              <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
                <dt className="font-semibold">Available from</dt>
                <dd>{formatDateTime(a.available_from)}</dd>
                <dt className="font-semibold">Deadline</dt>
                <dd>{formatDateTime(a.deadline)}</dd>
                <dt className="font-semibold">Rubric</dt>
                <dd>{a.rubric_name ? `${a.rubric_name} (${a.max_points} pts)` : "None selected"}</dd>
                <dt className="font-semibold">Submissions</dt>
                <dd>
                  {a.submission_count} ({a.graded_count} graded)
                </dd>
              </dl>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </section>
  );
}
