"use client";

import { TestCase, TestMatch } from "@/lib/api";

/** One test case as edited in the form (points kept as typed). */
export type TestCaseRow = {
  name: string;
  input: string;
  expected_output: string;
  match: TestMatch;
  visible: boolean;
  points: string;
};

export const emptyTestRow = (): TestCaseRow => ({
  name: "",
  input: "",
  expected_output: "",
  match: "exact",
  visible: false,
  points: "1",
});

export function toTestRows(tests: TestCase[]): TestCaseRow[] {
  return tests.map((t) => ({
    name: t.name,
    input: t.input,
    expected_output: t.expected_output,
    match: t.match,
    visible: t.visible,
    points: String(t.points),
  }));
}

/** A test as sent to the API: the question it belongs to is added by whoever knows the question's place. */
export type TestCasePayload = Omit<TestCase, "id" | "question">;

/** The rows as the API expects them, or the first problem to show the instructor. */
export function testRowsPayload(
  rows: TestCaseRow[],
): { tests: TestCasePayload[]; error: null } | { tests: null; error: string } {
  const tests: TestCasePayload[] = [];
  for (const [i, row] of rows.entries()) {
    const label = row.name.trim() || `Test ${i + 1}`;
    const points = Number(row.points);
    if (!row.expected_output.trim()) return { tests: null, error: `${label} needs an expected output.` };
    if (!Number.isFinite(points) || points <= 0 || points > 1000) {
      return { tests: null, error: `${label}: points must be a number above 0 (at most 1000).` };
    }
    tests.push({ name: row.name.trim(), input: row.input, expected_output: row.expected_output, match: row.match, visible: row.visible, points });
  }
  return { tests, error: null };
}

const field = "mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm";
/** The most test cases an assignment can have in all, whatever the number of questions: must match the backend's _TEST_CASES_MAX. */
export const MAX_TESTS = 50;

/** The test cases of one question: input fed to the program, expected output, match mode, visibility, points. */
export default function TestCasesEditor({
  rows,
  onChange,
  idPrefix = "",
  canAdd = true,
}: {
  rows: TestCaseRow[];
  onChange: (rows: TestCaseRow[]) => void;
  /** Keeps the field ids apart when several editors are on the page (one per question). */
  idPrefix?: string;
  /** False when the assignment already has as many test cases as it can have. */
  canAdd?: boolean;
}) {
  const update = (i: number, patch: Partial<TestCaseRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const total = rows.reduce((sum, r) => sum + (Number(r.points) || 0), 0);
  const visible = rows.filter((r) => r.visible).length;

  return (
    <fieldset className="mt-3" data-testid="test-cases-editor">
      <legend className="text-sm font-semibold">
        Test cases <span className="font-normal text-gray-500">(at least one)</span>
      </legend>

      <div className="mt-2 space-y-3">
        {rows.map((row, i) => (
          <div key={i} className="rounded-md border border-gray-200 p-3" data-testid="test-case-row">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{row.name.trim() || `Test ${i + 1}`}</span>
              <button
                type="button"
                onClick={() => onChange(rows.filter((_, j) => j !== i))}
                className="rounded-md bg-gray-600 px-2 py-1 text-xs font-semibold text-white hover:bg-gray-700"
              >
                Remove
              </button>
            </div>
            <label className="mt-2 block text-xs font-semibold" htmlFor={`${idPrefix}test-${i}-name`}>
              Name
            </label>
            <input
              id={`${idPrefix}test-${i}-name`}
              value={row.name}
              maxLength={200}
              placeholder={`Test ${i + 1}`}
              onChange={(e) => update(i, { name: e.target.value })}
              className={field}
            />
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <label className="block text-xs font-semibold" htmlFor={`${idPrefix}test-${i}-input`}>
                  Input
                </label>
                <textarea
                  id={`${idPrefix}test-${i}-input`}
                  value={row.input}
                  rows={4}
                  maxLength={10000}
                  placeholder={"1\nS001\nAli\n80"}
                  onChange={(e) => update(i, { input: e.target.value })}
                  className={`${field} font-mono`}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold" htmlFor={`${idPrefix}test-${i}-expected`}>
                  Expected output
                </label>
                <textarea
                  id={`${idPrefix}test-${i}-expected`}
                  value={row.expected_output}
                  rows={4}
                  maxLength={10000}
                  placeholder="Average: 75.00"
                  onChange={(e) => update(i, { expected_output: e.target.value })}
                  className={`${field} font-mono`}
                />
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-end gap-4">
              <div>
                <label className="block text-xs font-semibold" htmlFor={`${idPrefix}test-${i}-match`}>
                  Match
                </label>
                <select
                  id={`${idPrefix}test-${i}-match`}
                  value={row.match}
                  onChange={(e) => update(i, { match: e.target.value as TestMatch })}
                  className={field}
                >
                  <option value="exact">Exact output</option>
                  <option value="contains">Output contains</option>
                </select>
              </div>
              <div className="w-24">
                <label className="block text-xs font-semibold" htmlFor={`${idPrefix}test-${i}-points`}>
                  Points
                </label>
                <input
                  id={`${idPrefix}test-${i}-points`}
                  type="text"
                  inputMode="decimal"
                  value={row.points}
                  onChange={(e) => update(i, { points: e.target.value })}
                  className={field}
                />
              </div>
              <label className="flex items-center gap-2 pb-2 text-sm">
                <input type="checkbox" checked={row.visible} onChange={(e) => update(i, { visible: e.target.checked })} />
                Visible to students
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onChange([...rows, emptyTestRow()])}
          disabled={!canAdd}
          className="rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
        >
          + Add test case
        </button>
        {rows.length > 0 && (
          <span className="text-xs text-gray-600">
            {rows.length} test{rows.length === 1 ? "" : "s"} · {total} points · {visible} visible, {rows.length - visible}{" "}
            hidden
          </span>
        )}
      </div>
    </fieldset>
  );
}
