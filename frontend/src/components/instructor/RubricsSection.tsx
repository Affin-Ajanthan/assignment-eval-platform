"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, Rubric } from "@/lib/api";
import { takeFlash } from "@/lib/flash";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Badge from "@/components/Badge";
import { errText, redBtn } from "@/components/instructor/RubricParts";

/**
 * The Rubrics tab of the subject page: the subject's rubrics as boxes, and "+ New" for another. A box opens that rubric
 * to edit it (/instructor/subjects/<id>/rubrics/<rubric id>); Delete on it removes it (not one that graded submissions).
 */
export default function RubricsSection({
  subjectId,
  rubrics,
  onChanged,
}: {
  subjectId: number;
  rubrics: Rubric[];
  onChanged: () => Promise<void>;
}) {
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // The page that saved or deleted a rubric sends the instructor back here with a message to show.
  useEffect(() => {
    const flash = takeFlash();
    if (flash) setMsg({ text: flash, kind: "success" });
  }, []);

  function askDelete(r: Rubric) {
    if (r.locked) {
      return setMsg({
        text: `"${r.name}" can't be deleted: ${r.graded_count} submission(s) have been graded with it.`,
        kind: "error",
      });
    }
    setConfirm({
      title: `Delete rubric "${r.name}"?`,
      message:
        `Are you sure you want to delete this rubric and its ${r.criteria.length} criteria?` +
        (r.assignment_names.length
          ? `\n\nAssignments using it (${r.assignment_names.join(", ")}) will be left without a rubric.`
          : "") +
        "\n\nAny automated evaluations run with this rubric will also be removed.",
      onConfirm: async () => {
        setConfirmBusy(true);
        try {
          await apiFetch(`/rubrics/${r.id}`, { method: "DELETE" });
          setMsg({ text: `Rubric "${r.name}" deleted.`, kind: "success" });
          await onChanged();
        } catch (err) {
          setMsg({ text: `Failed to delete rubric: ${errText(err)}`, kind: "error" });
        } finally {
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  return (
    <section className="mt-6 card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">Rubrics</h2>
          <p className="mt-1 text-sm text-gray-600">
            A rubric holds all of its criteria. Click a box to edit it or add criteria; use + New for another rubric.
          </p>
        </div>
        <Link
          href={`/instructor/subjects/${subjectId}/rubrics/new`}
          className="btn-primary rounded-md px-4 py-2 text-sm font-semibold"
          data-testid="new-rubric"
        >
          + New
        </Link>
      </div>
      <Message state={msg} />

      {rubrics.length === 0 ? (
        <p className="empty-state mt-4" data-testid="no-rubrics">
          No rubrics yet. Use + New to create the first one.
        </p>
      ) : (
        <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="rubric-list">
          {rubrics.map((r) => (
            <li
              key={r.id}
              className="relative flex flex-col rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:border-blue-500 hover:bg-blue-50"
              data-testid="rubric-box"
            >
              {/* The name is a link stretched over the whole box; Delete sits above it. */}
              <Link
                href={`/instructor/subjects/${subjectId}/rubrics/${r.id}`}
                className="break-words text-base font-bold after:absolute after:inset-0"
              >
                {r.name}
              </Link>
              <p className="mt-2 text-xs text-gray-600">
                {r.criteria.length} criteria · {r.max_total} points
              </p>
              {r.assignment_names.length > 0 && (
                <p className="mt-1 text-xs text-gray-600">Used by: {r.assignment_names.join(", ")}</p>
              )}
              {r.locked && (
                <div className="mt-2">
                  <Badge tone="bg-yellow-50 text-yellow-800">Locked · {r.graded_count} graded</Badge>
                </div>
              )}
              <div className="relative z-10 mt-auto pt-4">
                <button type="button" className={redBtn} onClick={() => askDelete(r)}>
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
