"use client";

import { Criterion } from "@/lib/api";
import AutoGrowTextarea from "@/components/AutoGrowTextarea";

/** Pieces shared by the rubric list (RubricsSection), the create form and the editor of one rubric. */

export type Row = { name: string; description: string; maxPoints: string };
export const emptyRow = (): Row => ({ name: "", description: "", maxPoints: "" });

export const input = "w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm";
export const grayBtn = "btn-secondary rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-60";
export const redBtn = "btn-danger rounded-md px-3 py-1.5 text-xs font-semibold";
export const blueBtn = "btn-primary rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-60";

export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function toCriterion(row: Row): Criterion | null {
  const max = parseFloat(row.maxPoints);
  if (!row.name.trim() || Number.isNaN(max) || max <= 0) return null;
  return { name: row.name.trim(), description: row.description.trim(), max_points: max };
}

/** Name / description / max-points inputs for one criterion. */
export function CriterionFields({
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
        {/* At least two lines; a longer text wraps onto more lines and the box grows, with no sideways scrolling. */}
        <AutoGrowTextarea
          id={`${idPrefix}-desc`}
          value={row.description}
          rows={2}
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
