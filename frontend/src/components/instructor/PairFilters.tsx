"use client";

import { useState } from "react";

/** What a similarity table shows: flagged pairs only (the default), pairs with a student whose name matches, sorted by one column. */
export function usePairFilters<S extends string>(defaultSort: S) {
  const [flaggedOnly, setFlaggedOnly] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<S>(defaultSort);
  return { flaggedOnly, setFlaggedOnly, search, setSearch, sort, setSort };
}

/** True when either student of the pair matches the search (case-insensitive); an empty search matches every pair. */
export function pairMatches(search: string, ...students: string[]): boolean {
  const q = search.trim().toLowerCase();
  return !q || students.some((s) => s.toLowerCase().includes(q));
}

/** The controls above a similarity table, and how many of its pairs are shown. */
export default function PairFilters<S extends string>({
  idPrefix,
  filters,
  sortOptions,
  shown,
  total,
  flaggedTotal,
}: {
  idPrefix: string;
  filters: ReturnType<typeof usePairFilters<S>>;
  sortOptions: { value: S; label: string }[];
  shown: number;
  total: number;
  flaggedTotal: number;
}) {
  const { flaggedOnly, setFlaggedOnly, search, setSearch, sort, setSort } = filters;
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="flex items-center gap-1.5 pb-1.5">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
          Flagged only ({flaggedTotal})
        </label>
        <div>
          <label className="block text-xs font-semibold" htmlFor={`${idPrefix}-search`}>
            Student
          </label>
          <input
            id={`${idPrefix}-search`}
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name"
            className="mt-0.5 w-48 rounded-md border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold" htmlFor={`${idPrefix}-sort`}>
            Sort by
          </label>
          <select
            id={`${idPrefix}-sort`}
            value={sort}
            onChange={(e) => setSort(e.target.value as S)}
            className="mt-0.5 rounded-md border border-gray-300 px-2 py-1 text-sm"
          >
            {sortOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="mt-1 text-xs text-gray-500" role="status">
        Showing {shown} of {total} pair(s).
        {shown === 0 && flaggedOnly && !search.trim() && " No pair is flagged: untick Flagged only to see them all."}
      </p>
    </div>
  );
}
