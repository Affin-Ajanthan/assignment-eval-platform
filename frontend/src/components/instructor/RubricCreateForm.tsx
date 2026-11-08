"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import { CriterionFields, emptyRow, errText, grayBtn, Row, toCriterion } from "@/components/instructor/RubricParts";

/** The form for a new rubric: its name and as many criteria rows as needed (POST /rubrics). */
export default function RubricCreateForm({
  subjectId,
  onSaved,
  onCancel,
}: {
  subjectId: number;
  onSaved: (message: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [msg, setMsg] = useState<MessageState>(null);
  const [saving, setSaving] = useState(false);

  const total = rows.reduce((sum, r) => sum + (parseFloat(r.maxPoints) || 0), 0);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (!name.trim()) return setMsg({ text: "Rubric name is required.", kind: "error" });
    const filled = rows.filter((r) => r.name.trim() || r.description.trim() || r.maxPoints);
    const criteria = filled.map(toCriterion);
    if (criteria.length === 0) {
      return setMsg({ text: "Add at least one criterion with a name and maximum points.", kind: "error" });
    }
    if (criteria.some((c) => c === null)) {
      return setMsg({ text: "Every criterion needs a name and maximum points above 0.", kind: "error" });
    }
    setSaving(true);
    try {
      await apiFetch("/rubrics", { method: "POST", json: { name: name.trim(), subject_id: subjectId, criteria } });
      onSaved(`Rubric "${name.trim()}" saved with ${criteria.length} criteria.`);
    } catch (err) {
      setMsg({ text: `Failed to save rubric: ${errText(err)}`, kind: "error" });
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleCreate}>
      <label className="block text-sm font-semibold" htmlFor="rubric_name">
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
        Total maximum points: <strong>{total}</strong>
      </p>
      <div className="mt-2 flex gap-2">
        <button disabled={saving} className="btn-primary rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-60">
          {saving ? "Saving..." : "Save rubric"}
        </button>
        <button type="button" onClick={onCancel} className="btn-secondary rounded-md px-4 py-2 text-sm font-semibold">
          Cancel
        </button>
      </div>
      <Message state={msg} />
    </form>
  );
}
