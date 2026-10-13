"use client";

import { FormEvent, useState } from "react";
import { apiFetch, Subject, UserInfo } from "@/lib/api";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Message, { MessageState } from "@/components/Message";

export function SubjectCheckboxes({
  id,
  subjects,
  checked,
  onToggle,
}: {
  id: string;
  subjects: Subject[];
  checked: Set<number>;
  onToggle: (id: number) => void;
}) {
  if (subjects.length === 0) {
    return <p className="text-sm text-gray-500">Add a subject above first.</p>;
  }
  return (
    <div id={id} className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-300 px-3 py-2">
      {subjects.map((s) => (
        <label key={s.id} className="flex items-center gap-2 text-sm font-normal">
          <input type="checkbox" checked={checked.has(s.id)} onChange={() => onToggle(s.id)} className="h-4 w-4" />
          {s.name} ({s.code})
        </label>
      ))}
    </div>
  );
}

function subjectNames(subjects: Subject[]): string {
  return subjects.length ? subjects.map((s) => s.name).join(", ") : "(none)";
}

/**
 * Existing instructors or students, each with Edit (name, email, new
 * password, subjects) and Delete. Changes go to PUT/DELETE
 * /admin/{instructors|students}/{id}; `onChanged` reloads the list.
 */
export default function ManageUsersTable({
  role,
  users,
  subjects,
  onChanged,
}: {
  role: "instructor" | "student";
  users: UserInfo[];
  subjects: Subject[];
  onChanged: () => Promise<void>;
}) {
  const base = role === "instructor" ? "/admin/instructors" : "/admin/students";
  const label = role === "instructor" ? "instructor" : "student";

  const [editingId, setEditingId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [subjectIds, setSubjectIds] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [deleting, setDeleting] = useState(false);

  function startEdit(u: UserInfo) {
    setEditingId(u.id);
    setName(u.full_name);
    setEmail(u.email);
    setPassword("");
    setSubjectIds(new Set(u.subjects.map((s) => s.id)));
    setMsg(null);
  }

  function toggleSubject(id: number) {
    const next = new Set(subjectIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSubjectIds(next);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (editingId === null) return;
    setSaving(true);
    setMsg(null);
    try {
      await apiFetch(`${base}/${editingId}`, {
        method: "PUT",
        json: { full_name: name, email, password: password || null, subject_ids: Array.from(subjectIds) },
      });
      await onChanged();
      setEditingId(null);
      setMsg({
        text: password
          ? `Saved. The new password is active and ${name} has been logged out of open sessions.`
          : "Saved.",
        kind: "success",
      });
    } catch (err) {
      setMsg({ text: `Could not save: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  function askDelete(u: UserInfo) {
    const count = u.submission_count ?? 0;
    const lines =
      role === "student"
        ? [
            `${u.full_name} (${u.email}) will no longer be able to log in.`,
            count
              ? `Their ${count} submission(s) will be deleted too, with all grades, automated evaluations, ` +
                "similarity results and uploaded files."
              : "They have no submissions.",
          ]
        : [
            `${u.full_name} (${u.email}) will no longer be able to log in and is removed from all subjects.`,
            "Grades they gave stay (with their name). Assignments and rubrics they created stay.",
          ];
    setConfirm({
      title: `Delete ${label}?`,
      message: `${lines.join("\n\n")}\n\nThis cannot be undone.`,
      confirmLabel: `Delete ${label}`,
      onConfirm: async () => {
        setDeleting(true);
        setMsg(null);
        try {
          await apiFetch(`${base}/${u.id}`, { method: "DELETE" });
          if (editingId === u.id) setEditingId(null);
          await onChanged();
          setMsg({ text: `${u.full_name} was deleted.`, kind: "success" });
        } catch (err) {
          setMsg({ text: `Could not delete: ${err instanceof Error ? err.message : err}`, kind: "error" });
        } finally {
          setDeleting(false);
          setConfirm(null);
        }
      },
    });
  }

  const cell = "border border-gray-200 px-3 py-1.5";

  return (
    <>
      <Message state={msg} />
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className={cell}>Name</th>
              <th className={cell}>Email</th>
              <th className={cell}>Subjects</th>
              {role === "student" && <th className={cell}>Submissions</th>}
              <th className={cell}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr>
                <td colSpan={role === "student" ? 5 : 4} className={`${cell} text-gray-500`}>
                  No {label}s yet.
                </td>
              </tr>
            )}
            {users.map((u) =>
              editingId === u.id ? (
                <tr key={u.id} className="bg-blue-50">
                  <td colSpan={role === "student" ? 5 : 4} className={cell}>
                    <form onSubmit={save} className="py-1">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                          <label className="block text-sm font-semibold" htmlFor={`edit-name-${u.id}`}>
                            Full name
                          </label>
                          <input
                            id={`edit-name-${u.id}`}
                            required
                            maxLength={200}
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-semibold" htmlFor={`edit-email-${u.id}`}>
                            Email
                          </label>
                          <input
                            id={`edit-email-${u.id}`}
                            type="email"
                            required
                            maxLength={254}
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                          />
                        </div>
                      </div>
                      <label className="mt-3 block text-sm font-semibold" htmlFor={`edit-password-${u.id}`}>
                        New password <span className="font-normal text-gray-500">(leave blank to keep the current one)</span>
                      </label>
                      <input
                        id={`edit-password-${u.id}`}
                        value={password}
                        minLength={4}
                        maxLength={200}
                        autoComplete="new-password"
                        onChange={(e) => setPassword(e.target.value)}
                        className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                      />
                      <label className="mt-3 block text-sm font-semibold">Subjects</label>
                      <div className="mt-1 bg-white">
                        <SubjectCheckboxes
                          id={`edit-subjects-${u.id}`}
                          subjects={subjects}
                          checked={subjectIds}
                          onToggle={toggleSubject}
                        />
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
                <tr key={u.id}>
                  <td className={cell}>{u.full_name}</td>
                  <td className={cell}>{u.email}</td>
                  <td className={cell}>{subjectNames(u.subjects)}</td>
                  {role === "student" && <td className={cell}>{u.submission_count ?? 0}</td>}
                  <td className={`${cell} whitespace-nowrap`}>
                    <button
                      type="button"
                      onClick={() => startEdit(u)}
                      className="rounded-md border border-blue-600 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => askDelete(u)}
                      className="ml-2 rounded-md border border-red-600 px-2.5 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>
      <ConfirmDialog request={confirm} busy={deleting} onCancel={() => !deleting && setConfirm(null)} />
    </>
  );
}
