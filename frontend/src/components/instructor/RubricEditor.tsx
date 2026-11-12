"use client";

import { useState } from "react";
import { apiFetch, Rubric } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import {
  blueBtn,
  CriterionFields,
  emptyRow,
  errText,
  grayBtn,
  input,
  redBtn,
  Row,
  toCriterion,
} from "@/components/instructor/RubricParts";

/**
 * One rubric with everything editable: rename it, edit / add / delete its criteria, delete it. A rubric that already
 * graded submissions is locked: criteria names and points stay (so existing marks keep their meaning), descriptions
 * can still change, and it can't be deleted.
 */
export default function RubricEditor({
  rubric: r,
  onChanged,
  onDeleted,
}: {
  rubric: Rubric;
  onChanged: () => Promise<void>;
  /** After the rubric was deleted: the page leaves. */
  onDeleted: (message: string) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null); // the new name while renaming
  const [editing, setEditing] = useState<{ criterionId: number; row: Row } | null>(null);
  const [adding, setAdding] = useState<Row | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMsg(null);
    try {
      await action();
      setMsg({ text: success, kind: "success" });
      setRenaming(null);
      setEditing(null);
      setAdding(null);
      await onChanged();
    } catch (err) {
      setMsg({ text: errText(err), kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  function saveCriterionEdit() {
    if (!editing) return;
    const c = toCriterion(editing.row);
    if (!c) return setMsg({ text: "A criterion needs a name and maximum points above 0.", kind: "error" });
    const body = r.locked ? { description: c.description } : c;
    run(() => apiFetch(`/rubrics/${r.id}/criteria/${editing.criterionId}`, { method: "PUT", json: body }), "Criterion updated.");
  }

  function saveNewCriterion() {
    if (!adding) return;
    const c = toCriterion(adding);
    if (!c) return setMsg({ text: "A criterion needs a name and maximum points above 0.", kind: "error" });
    run(() => apiFetch(`/rubrics/${r.id}/criteria`, { method: "POST", json: c }), `Criterion "${c.name}" added.`);
  }

  function confirmThen(request: Omit<ConfirmRequest, "onConfirm">, action: () => Promise<unknown>, success: string) {
    setConfirm({
      ...request,
      onConfirm: async () => {
        setConfirmBusy(true);
        await run(action, success);
        setConfirmBusy(false);
        setConfirm(null);
      },
    });
  }

  function askDeleteRubric() {
    if (r.locked) {
      return setMsg({
        text: `This rubric can't be deleted: ${r.graded_count} submission(s) have been graded with it.`,
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
          onDeleted(`Rubric "${r.name}" deleted.`);
        } catch (err) {
          setMsg({ text: errText(err), kind: "error" });
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  return (
    <div data-testid="rubric-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        {renaming !== null ? (
          <div className="flex min-w-0 flex-1 flex-wrap gap-2">
            <input
              aria-label="Rubric name"
              value={renaming}
              maxLength={200}
              onChange={(e) => setRenaming(e.target.value)}
              className={`${input} flex-1`}
            />
            <button
              type="button"
              disabled={busy}
              className={blueBtn}
              onClick={() => run(() => apiFetch(`/rubrics/${r.id}`, { method: "PUT", json: { name: renaming } }), "Rubric renamed.")}
            >
              Save
            </button>
            <button type="button" className={grayBtn} onClick={() => setRenaming(null)}>
              Cancel
            </button>
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            <h2 className="break-words text-lg font-semibold">{r.name}</h2>
            <p className="text-sm text-gray-600">
              {r.criteria.length} criteria · Total maximum points: <strong>{r.max_total}</strong>
              {r.assignment_names.length > 0 && ` · Used by: ${r.assignment_names.join(", ")}`}
            </p>
            {r.locked && (
              <p className="mt-1 rounded bg-yellow-50 px-2 py-1 text-xs text-yellow-800">
                Used to grade {r.graded_count} submission(s): criteria names and points are locked so existing marks
                keep their meaning. Descriptions can still be edited.
              </p>
            )}
          </div>
        )}
        {renaming === null && (
          <div className="flex shrink-0 flex-wrap gap-2">
            <button
              type="button"
              className={grayBtn}
              disabled={r.locked}
              title={r.locked ? "Locked: this rubric has grades" : undefined}
              onClick={() => setRenaming(r.name)}
            >
              Rename
            </button>
            <button type="button" className={redBtn} onClick={askDeleteRubric}>
              Delete
            </button>
          </div>
        )}
      </div>

      <ul className="mt-3 space-y-2">
        {r.criteria.map((c) => (
          <li key={c.id} className="rounded border border-gray-100 bg-gray-50 p-3" data-testid="rubric-criterion">
            {editing?.criterionId === c.id ? (
              <>
                <CriterionFields
                  idPrefix={`edit-${r.id}-${c.id}`}
                  row={editing.row}
                  lockStructure={r.locked}
                  onChange={(patch) => setEditing({ ...editing, row: { ...editing.row, ...patch } })}
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button type="button" disabled={busy} className={blueBtn} onClick={saveCriterionEdit}>
                    Save
                  </button>
                  <button type="button" className={grayBtn} onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1 basis-48">
                  <p className="font-semibold">{c.name}</p>
                  {c.description && <p className="whitespace-pre-line break-words text-sm text-gray-600">{c.description}</p>}
                  <p className="text-sm">Maximum points: {c.max_points}</p>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  <button
                    type="button"
                    className={grayBtn}
                    onClick={() =>
                      setEditing({
                        criterionId: c.id!,
                        row: { name: c.name, description: c.description, maxPoints: String(c.max_points) },
                      })
                    }
                  >
                    Edit
                  </button>
                  {!r.locked && (
                    <button
                      type="button"
                      className={redBtn}
                      onClick={() =>
                        confirmThen(
                          {
                            title: `Delete criterion "${c.name}"?`,
                            message: `Are you sure you want to delete this criterion from "${r.name}"? The rubric's total will drop by ${c.max_points} points.`,
                          },
                          () => apiFetch(`/rubrics/${r.id}/criteria/${c.id}`, { method: "DELETE" }),
                          "Criterion deleted.",
                        )
                      }
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      {!r.locked &&
        (adding ? (
          <div className="mt-3 rounded border border-blue-100 p-3">
            <p className="mb-1 text-sm font-semibold">New criterion for {r.name}</p>
            <CriterionFields
              idPrefix={`add-${r.id}`}
              row={adding}
              onChange={(patch) => setAdding({ ...adding, ...patch })}
            />
            <div className="mt-2 flex gap-2">
              <button type="button" disabled={busy} className={blueBtn} onClick={saveNewCriterion}>
                Add to rubric
              </button>
              <button type="button" className={grayBtn} onClick={() => setAdding(null)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className={`mt-3 ${grayBtn}`} onClick={() => setAdding(emptyRow())}>
            + Add criterion
          </button>
        ))}

      <Message state={msg} />
      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </div>
  );
}
