"use client";

import { FormEvent, useState } from "react";
import { apiFetch, Criterion, Rubric } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";

type Row = { name: string; description: string; maxPoints: string };
const emptyRow = (): Row => ({ name: "", description: "", maxPoints: "" });

const input = "w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm";
const grayBtn = "rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700 disabled:opacity-60";
const redBtn = "rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700";
const blueBtn = "rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60";

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function toCriterion(row: Row): Criterion | null {
  const max = parseFloat(row.maxPoints);
  if (!row.name.trim() || Number.isNaN(max) || max <= 0) return null;
  return { name: row.name.trim(), description: row.description.trim(), max_points: max };
}

/** Name / description / max-points inputs for one criterion. */
function CriterionFields({
  row,
  onChange,
  lockStructure = false,
  idPrefix,
}: {
  row: Row;
  onChange: (patch: Partial<Row>) => void;
  lockStructure?: boolean;
  idPrefix: string;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[1fr_2fr_7rem]">
      <div>
        <label className="text-xs font-semibold" htmlFor={`${idPrefix}-name`}>
          Criterion name
        </label>
        <input
          id={`${idPrefix}-name`}
          value={row.name}
          disabled={lockStructure}
          maxLength={200}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="Code Quality"
          className={input}
        />
      </div>
      <div>
        <label className="text-xs font-semibold" htmlFor={`${idPrefix}-desc`}>
          Description
        </label>
        <input
          id={`${idPrefix}-desc`}
          value={row.description}
          maxLength={2000}
          onChange={(e) => onChange({ description: e.target.value })}
          placeholder="Quality and structure of the submitted code"
          className={input}
        />
      </div>
      <div>
        <label className="text-xs font-semibold" htmlFor={`${idPrefix}-max`}>
          Maximum points
        </label>
        <input
          id={`${idPrefix}-max`}
          type="number"
          min={0.5}
          step={0.5}
          value={row.maxPoints}
          disabled={lockStructure}
          onChange={(e) => onChange({ maxPoints: e.target.value })}
          className={input}
        />
      </div>
    </div>
  );
}

export default function RubricsSection({
  subjectId,
  rubrics,
  onChanged,
}: {
  subjectId: number;
  rubrics: Rubric[];
  onChanged: () => Promise<void>;
}) {
  // Create form: one rubric with as many criteria rows as needed.
  const [name, setName] = useState("");
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [createMsg, setCreateMsg] = useState<MessageState>(null);

  // Per-rubric editing state (one thing at a time keeps it simple).
  const [renaming, setRenaming] = useState<{ rubricId: number; name: string } | null>(null);
  const [editing, setEditing] = useState<{ rubricId: number; criterionId: number; row: Row } | null>(null);
  const [adding, setAdding] = useState<{ rubricId: number; row: Row } | null>(null);
  const [cardMsg, setCardMsg] = useState<{ rubricId: number; state: MessageState } | null>(null);
  const [busy, setBusy] = useState(false);

  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const createTotal = rows.reduce((sum, r) => sum + (parseFloat(r.maxPoints) || 0), 0);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateMsg(null);
    if (!name.trim()) return setCreateMsg({ text: "Rubric name is required.", kind: "error" });
    const filled = rows.filter((r) => r.name.trim() || r.description.trim() || r.maxPoints);
    const criteria = filled.map(toCriterion);
    if (criteria.length === 0) {
      return setCreateMsg({ text: "Add at least one criterion with a name and maximum points.", kind: "error" });
    }
    if (criteria.some((c) => c === null)) {
      return setCreateMsg({ text: "Every criterion needs a name and maximum points above 0.", kind: "error" });
    }
    try {
      await apiFetch("/rubrics", { method: "POST", json: { name: name.trim(), subject_id: subjectId, criteria } });
      setCreateMsg({ text: `Rubric saved with ${criteria.length} criteria.`, kind: "success" });
      setName("");
      setRows([emptyRow()]);
      await onChanged();
    } catch (err) {
      setCreateMsg({ text: `Failed to save rubric: ${errText(err)}`, kind: "error" });
    }
  }

  async function run(rubricId: number, action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setCardMsg(null);
    try {
      await action();
      setCardMsg({ rubricId, state: { text: success, kind: "success" } });
      setRenaming(null);
      setEditing(null);
      setAdding(null);
      await onChanged();
    } catch (err) {
      setCardMsg({ rubricId, state: { text: errText(err), kind: "error" } });
    } finally {
      setBusy(false);
    }
  }

  function saveCriterionEdit(r: Rubric) {
    if (!editing) return;
    const c = toCriterion(editing.row);
    if (!c) {
      return setCardMsg({ rubricId: r.id, state: { text: "A criterion needs a name and maximum points above 0.", kind: "error" } });
    }
    const body = r.locked ? { description: c.description } : c;
    run(r.id, () => apiFetch(`/rubrics/${r.id}/criteria/${editing.criterionId}`, { method: "PUT", json: body }), "Criterion updated.");
  }

  function saveNewCriterion(r: Rubric) {
    if (!adding) return;
    const c = toCriterion(adding.row);
    if (!c) {
      return setCardMsg({ rubricId: r.id, state: { text: "A criterion needs a name and maximum points above 0.", kind: "error" } });
    }
    run(r.id, () => apiFetch(`/rubrics/${r.id}/criteria`, { method: "POST", json: c }), `Criterion "${c.name}" added.`);
  }

  function confirmThen(request: Omit<ConfirmRequest, "onConfirm">, rubricId: number, action: () => Promise<unknown>, success: string) {
    setConfirm({
      ...request,
      onConfirm: async () => {
        setConfirmBusy(true);
        await run(rubricId, action, success);
        setConfirmBusy(false);
        setConfirm(null);
      },
    });
  }

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Rubrics</h2>
      <p className="mt-1 text-sm text-gray-600">
        A rubric holds all of its criteria. Use <strong>+ Add criterion</strong> to add more to the same rubric.
      </p>

      <form onSubmit={handleCreate} className="mt-3">
        <h3 className="text-sm font-bold">Create rubric</h3>
        <label className="mt-2 block text-sm font-semibold" htmlFor="rubric_name">
          Rubric name
        </label>
        <input
          id="rubric_name"
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
          placeholder="Assignment 1 Rubric"
          className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />

        <p className="text-sm font-semibold">Criteria</p>
        <div className="mt-1 space-y-3">
          {rows.map((row, i) => (
            <div key={i} data-testid="criterion-row" className="rounded-md border border-gray-200 p-3">
              <CriterionFields
                idPrefix={`new-criterion-${i}`}
                row={row}
                onChange={(patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))}
              />
              {rows.length > 1 && (
                <button
                  type="button"
                  onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                  className={`mt-2 ${grayBtn}`}
                >
                  Remove this criterion
                </button>
              )}
            </div>
          ))}
        </div>
        <button type="button" onClick={() => setRows((rs) => [...rs, emptyRow()])} className={`mt-2 ${grayBtn}`}>
          + Add criterion
        </button>
        <p className="mt-2 text-sm">
          Total maximum points: <strong>{createTotal}</strong>
        </p>
        <button className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
          Save rubric
        </button>
        <Message state={createMsg} />
      </form>

      <h3 className="mt-6 text-sm font-bold uppercase tracking-wide text-gray-500">Rubrics in this subject</h3>
      {rubrics.length === 0 && <p className="mt-2 text-sm text-gray-600">No rubrics yet.</p>}
      <ul className="mt-2 space-y-3">
        {rubrics.map((r) => (
          <li key={r.id} className="rounded-md border border-gray-200 p-4" data-testid="rubric-card">
            <div className="flex flex-wrap items-start justify-between gap-2">
              {renaming?.rubricId === r.id ? (
                <div className="flex flex-1 flex-wrap gap-2">
                  <input
                    aria-label="Rubric name"
                    value={renaming.name}
                    maxLength={200}
                    onChange={(e) => setRenaming({ rubricId: r.id, name: e.target.value })}
                    className={`${input} flex-1`}
                  />
                  <button
                    type="button"
                    disabled={busy}
                    className={blueBtn}
                    onClick={() =>
                      run(r.id, () => apiFetch(`/rubrics/${r.id}`, { method: "PUT", json: { name: renaming.name } }), "Rubric renamed.")
                    }
                  >
                    Save
                  </button>
                  <button type="button" className={grayBtn} onClick={() => setRenaming(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div>
                  <h4 className="font-bold">{r.name}</h4>
                  <p className="text-sm text-gray-600">
                    {r.criteria.length} criteria · Total maximum points: <strong>{r.max_total}</strong>
                    {r.assignment_names.length > 0 && ` · Used by: ${r.assignment_names.join(", ")}`}
                  </p>
                  {r.locked && (
                    <p className="mt-1 rounded bg-yellow-50 px-2 py-1 text-xs text-yellow-800">
                      Used to grade {r.graded_count} submission(s): criteria names and points are locked so existing
                      marks keep their meaning. Descriptions can still be edited.
                    </p>
                  )}
                </div>
              )}
              {renaming?.rubricId !== r.id && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={grayBtn}
                    disabled={r.locked}
                    title={r.locked ? "Locked: this rubric has grades" : undefined}
                    onClick={() => setRenaming({ rubricId: r.id, name: r.name })}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className={redBtn}
                    onClick={() =>
                      r.locked
                        ? setCardMsg({
                            rubricId: r.id,
                            state: {
                              text: `This rubric can't be deleted: ${r.graded_count} submission(s) have been graded with it.`,
                              kind: "error",
                            },
                          })
                        : confirmThen(
                            {
                              title: `Delete rubric "${r.name}"?`,
                              message:
                                `Are you sure you want to delete this rubric and its ${r.criteria.length} criteria?` +
                                (r.assignment_names.length
                                  ? `\n\nAssignments using it (${r.assignment_names.join(", ")}) will be left without a rubric.`
                                  : "") +
                                "\n\nAny automated evaluations run with this rubric will also be removed.",
                            },
                            r.id,
                            () => apiFetch(`/rubrics/${r.id}`, { method: "DELETE" }),
                            "Rubric deleted.",
                          )
                    }
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>

            <ul className="mt-3 space-y-2">
              {r.criteria.map((c) => (
                <li key={c.id} className="rounded border border-gray-100 bg-gray-50 p-3" data-testid="rubric-criterion">
                  {editing?.rubricId === r.id && editing.criterionId === c.id ? (
                    <>
                      <CriterionFields
                        idPrefix={`edit-${r.id}-${c.id}`}
                        row={editing.row}
                        lockStructure={r.locked}
                        onChange={(patch) => setEditing({ ...editing, row: { ...editing.row, ...patch } })}
                      />
                      <div className="mt-2 flex gap-2">
                        <button type="button" disabled={busy} className={blueBtn} onClick={() => saveCriterionEdit(r)}>
                          Save
                        </button>
                        <button type="button" className={grayBtn} onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold">{c.name}</p>
                        {c.description && <p className="text-sm text-gray-600">{c.description}</p>}
                        <p className="text-sm">Maximum points: {c.max_points}</p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className={grayBtn}
                          onClick={() =>
                            setEditing({
                              rubricId: r.id,
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
                                r.id,
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
              (adding?.rubricId === r.id ? (
                <div className="mt-3 rounded border border-blue-100 p-3">
                  <p className="mb-1 text-sm font-semibold">New criterion for {r.name}</p>
                  <CriterionFields
                    idPrefix={`add-${r.id}`}
                    row={adding.row}
                    onChange={(patch) => setAdding({ rubricId: r.id, row: { ...adding.row, ...patch } })}
                  />
                  <div className="mt-2 flex gap-2">
                    <button type="button" disabled={busy} className={blueBtn} onClick={() => saveNewCriterion(r)}>
                      Add to rubric
                    </button>
                    <button type="button" className={grayBtn} onClick={() => setAdding(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className={`mt-3 ${grayBtn}`} onClick={() => setAdding({ rubricId: r.id, row: emptyRow() })}>
                  + Add criterion
                </button>
              ))}

            {cardMsg?.rubricId === r.id && <Message state={cardMsg.state} />}
          </li>
        ))}
      </ul>

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </section>
  );
}
