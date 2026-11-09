"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, Assignment, AssignmentKind, AssignmentStatus } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { takeFlash } from "@/lib/flash";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Badge from "@/components/Badge";

const STATUS_STYLE: Record<AssignmentStatus, { text: string; cls: string }> = {
  upcoming: { text: "Not yet open", cls: "bg-gray-100 text-gray-700" },
  open: { text: "Open", cls: "bg-green-50 text-green-800" },
  closed: { text: "Closed", cls: "bg-yellow-50 text-yellow-800" },
};

/** What the list of each kind is called on its page. */
export const KIND_LIST_LABEL: Record<AssignmentKind, { title: string; empty: string }> = {
  submission: { title: "Submission assignments", empty: "No submission assignments yet." },
  code_challenge: { title: "Code challenges", empty: "No code challenges yet." },
};

/**
 * The existing assignments of one kind in the subject, one box each. A box opens the assignment page (grading, similarity,
 * AI content, batch evaluation, with an Edit button there); Edit on the box goes straight to the edit page with its
 * details filled in (/instructor/assignments/<id>), and Delete removes it. New ones are created with "+ New" at the top
 * of the page.
 */
export default function AssignmentsSection({
  subjectId,
  kind,
  assignments,
  onChanged,
}: {
  subjectId: number;
  kind: AssignmentKind;
  assignments: Assignment[];
  onChanged: () => Promise<void>;
}) {
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const shown = assignments.filter((a) => (a.assignment_type === "code_challenge" ? "code_challenge" : "submission") === kind);

  // The page that saved an assignment sends the instructor back here with a message to show.
  useEffect(() => {
    const flash = takeFlash();
    if (flash) setMsg({ text: flash, kind: "success" });
  }, []);

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

  return (
    <section className="card">
      <Message state={msg} />

      {shown.length === 0 ? (
        <p className="empty-state" data-testid="no-assignments">
          {KIND_LIST_LABEL[kind].empty} Use + New at the top right to create the first one.
        </p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="assignment-list">
          {shown.map((a) => (
            <li
              key={a.id}
              className="relative flex flex-col rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:border-blue-500 hover:bg-blue-50"
              data-testid="assignment-card"
            >
              {/* The name is a link stretched over the whole box; Edit and Delete sit above it. */}
              <Link
                href={`/instructor/subjects/${subjectId}/assignments/${a.id}`}
                className="text-base font-bold after:absolute after:inset-0"
                data-testid="open-assignment"
              >
                {a.name}
              </Link>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge tone={STATUS_STYLE[a.status].cls}>{STATUS_STYLE[a.status].text}</Badge>
              </div>
              <dl className="mt-3 space-y-1 text-xs text-gray-600">
                <div className="flex gap-1">
                  <dt className="font-semibold">Deadline:</dt>
                  <dd>{formatDateTime(a.deadline)}</dd>
                </div>
                <div className="flex gap-1">
                  <dt className="font-semibold">Submissions:</dt>
                  <dd>
                    {a.submission_count} ({a.graded_count} graded)
                  </dd>
                </div>
              </dl>
              <div className="relative z-10 mt-auto flex gap-2 pt-4">
                <Link
                  href={`/instructor/assignments/${a.id}`}
                  className="btn-secondary rounded-md px-3 py-1.5 text-xs font-semibold"
                  data-testid="edit-assignment"
                >
                  Edit
                </Link>
                <button
                  type="button"
                  onClick={() => askDelete(a)}
                  className="btn-danger rounded-md px-3 py-1.5 text-xs font-semibold"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </section>
  );
}
