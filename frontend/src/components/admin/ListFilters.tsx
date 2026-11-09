"use client";

/** One choice in the Batch box: the batch's key (see batchKeyOf), its label and how many rows have it. */
export type BatchOption = { key: string; label: string; count: number };

/** The filter key of a batch: "batch:01", or "no-batch" for a row without one. */
export const batchKeyOf = (batch?: string) => ((batch ?? "").trim() ? `batch:${(batch ?? "").trim()}` : "no-batch");

/**
 * The Batch box choices for a list. `keysPerRow` has, for each row, the batch keys it belongs to (a student or a
 * subject has one, an instructor has the batches of their subjects). The batches come in order, "No batch" last.
 */
export function batchOptionsFrom(keysPerRow: string[][]): BatchOption[] {
  const counts = new Map<string, number>();
  for (const keys of keysPerRow) for (const key of new Set(keys)) counts.set(key, (counts.get(key) ?? 0) + 1);
  return Array.from(counts, ([key, count]) => ({
    key,
    label: key === "no-batch" ? "No batch" : `Batch ${key.slice("batch:".length)}`,
    count,
  })).sort((a, b) =>
    a.key === "no-batch" ? 1 : b.key === "no-batch" ? -1 : a.label.localeCompare(b.label, undefined, { numeric: true }),
  );
}

/**
 * The search box and the Batch box above an admin list (students, subjects, instructors). `name` ("student",
 * "subject", "instructor") makes the ids and test ids: <name>-search, <name>-batch-filter, <name>-search-count.
 */
export default function ListFilters({
  name,
  placeholder,
  search,
  onSearch,
  batchOptions,
  batch,
  onBatch,
  total,
  shown,
}: {
  name: string;
  placeholder: string;
  search: string;
  onSearch: (value: string) => void;
  batchOptions: BatchOption[];
  /** "all" or a BatchOption key. */
  batch: string;
  onBatch: (key: string) => void;
  total: number;
  shown: number;
}) {
  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-3">
        <div className="w-full min-w-0 sm:w-auto sm:flex-1 sm:max-w-sm">
          <label className="block text-sm font-semibold" htmlFor={`${name}-search`}>
            Search {name}s
          </label>
          <input
            id={`${name}-search`}
            type="search"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={placeholder}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            data-testid={`${name}-search`}
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-sm font-semibold" htmlFor={`${name}-batch-filter`}>
            Batch
          </label>
          <select
            id={`${name}-batch-filter`}
            value={batch}
            onChange={(e) => onBatch(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            data-testid={`${name}-batch-filter`}
          >
            <option value="all">All batches ({total})</option>
            {batchOptions.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label} ({o.count})
              </option>
            ))}
          </select>
        </div>
      </div>
      {(search.trim() || batch !== "all") && (
        <p className="mt-1 text-xs text-gray-500" data-testid={`${name}-search-count`}>
          {shown} of {total} {name}s
        </p>
      )}
    </div>
  );
}
