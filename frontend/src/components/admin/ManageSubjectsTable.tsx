"use client";

import { FormEvent, useState } from "react";
import { apiFetch, Subject } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import { BatchCombobox } from "@/components/admin/StudentIdFields";

/**
 * Existing subjects, each with Edit (name, code and batch). Changes go to PUT /admin/subjects/{id};
 * `onChanged` reloads the list. `batches` are the choices of the Batch box.
 */
export default function ManageSubjectsTable({
  subjects,
  batches,
  onChanged,
}: {
  subjects: Subject[];
  batches: string[];
  onChanged: () => Promise<void>;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [batch, setBatch] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);

  function startEdit(s: Subject) {
    setEditingId(s.id);
    setName(s.name);
    setCode(s.code);
    setBatch(s.batch ?? "");
    setMsg(null);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (editingId === null) return;
    setSaving(true);
    setMsg(null);
    try {
      await apiFetch(`/admin/subjects/${editingId}`, { method: "PUT", json: { name, code, batch } });
      await onChanged();
      setEditingId(null);
      setMsg({ text: "Saved.", kind: "success" });
    } catch (err) {
      setMsg({ text: `Could not save: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  const cell = "border border-gray-200 px-3 py-1.5";

  return (
    <>
      <Message state={msg} />
      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-left">
            <th className={cell}>Name</th>
            <th className={cell}>Code</th>
            <th className={cell}>Batch</th>
            <th className={cell}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {subjects.length === 0 && (
            <tr>
              <td colSpan={4} className={`${cell} text-gray-500`}>
                No subjects yet.
              </td>
            </tr>
          )}
          {subjects.map((s) =>
            editingId === s.id ? (
              <tr key={s.id} className="bg-blue-50">
                <td colSpan={4} className={cell}>
                  <form onSubmit={save} className="py-1">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <div>
                        <label className="block text-sm font-semibold" htmlFor={`edit-subject-name-${s.id}`}>
                          Subject name
                        </label>
                        <input
                          id={`edit-subject-name-${s.id}`}
                          required
                          maxLength={200}
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-semibold" htmlFor={`edit-subject-code-${s.id}`}>
                          Subject code
                        </label>
                        <input
                          id={`edit-subject-code-${s.id}`}
                          required
                          maxLength={50}
                          value={code}
                          onChange={(e) => setCode(e.target.value)}
                          className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-semibold" htmlFor={`edit-subject-batch-${s.id}`}>
                          Batch
                        </label>
                        <BatchCombobox
                          id={`edit-subject-batch-${s.id}`}
                          value={batch}
                          onChange={setBatch}
                          options={batches}
                          testId="edit-subject-batch"
                        />
                      </div>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="submit"
                        disabled={saving}
                        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                      >
                        {saving ? "Saving..." : "Save changes"}
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => setEditingId(null)}
                        className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                </td>
              </tr>
            ) : (
              <tr key={s.id}>
                <td className={cell}>{s.name}</td>
                <td className={cell}>{s.code}</td>
                <td className={cell}>{s.batch || <span className="text-gray-400">-</span>}</td>
                <td className={`${cell} whitespace-nowrap`}>
                  <button
                    type="button"
                    onClick={() => startEdit(s)}
                    className="rounded-md border border-blue-600 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50"
                  >
                    Edit
                  </button>
                </td>
              </tr>
            )
          )}
        </tbody>
      </table>
    </>
  );
}
