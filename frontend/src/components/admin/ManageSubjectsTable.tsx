"use client";

import { useState } from "react";
import { Subject } from "@/lib/api";
import ListFilters, { batchKeyOf, batchOptionsFrom } from "@/components/admin/ListFilters";
import Pagination, { clampPage, DEFAULT_PAGE_SIZE } from "@/components/admin/Pagination";

/**
 * Existing subjects, each with Edit. Edit does not open a form in the row: `onEdit` hands the subject to the
 * page, which fills its own form with it (and saves with PUT /admin/subjects/{id}). `highlightId` is the
 * subject that form is editing: its row is marked. Subjects can be searched by name or code and filtered by batch.
 * Only the chosen number of rows (10, 20 or 50) is shown; the rest are on the next pages.
 */
export default function ManageSubjectsTable({
  subjects,
  onEdit,
  highlightId = null,
}: {
  subjects: Subject[];
  onEdit: (s: Subject) => void;
  highlightId?: number | null;
}) {
  const cell = "border border-gray-200 px-3 py-1.5";
  const [pageNo, setPageNo] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const [batchFilter, setBatchFilter] = useState("all"); // "all" or a batch key (see batchKeyOf)
  const query = search.trim().toLowerCase();
  // A chosen batch that no subject has any more counts as "all".
  const batchOptions = batchOptionsFrom(subjects.map((s) => [batchKeyOf(s.batch)]));
  const activeBatch = batchOptions.some((o) => o.key === batchFilter) ? batchFilter : "all";
  const matching = subjects.filter(
    (s) =>
      (activeBatch === "all" || batchKeyOf(s.batch) === activeBatch) &&
      (!query || s.name.toLowerCase().includes(query) || s.code.toLowerCase().includes(query)),
  );
  const page = clampPage(pageNo, matching.length, pageSize);
  const shown = matching.slice((page - 1) * pageSize, page * pageSize);

  return (
    <>
    {subjects.length > 0 && (
      <ListFilters
        name="subject"
        placeholder="Name or code"
        search={search}
        onSearch={(v) => {
          setSearch(v);
          setPageNo(1);
        }}
        batchOptions={batchOptions}
        batch={activeBatch}
        onBatch={(k) => {
          setBatchFilter(k);
          setPageNo(1);
        }}
        total={subjects.length}
        shown={matching.length}
      />
    )}
    <table className="mt-2 w-full text-sm">
      <thead>
        <tr className="bg-gray-50 text-left">
          <th className={cell}>Name</th>
          <th className={cell}>Code</th>
          <th className={cell}>Batch</th>
          <th className={cell}>Actions</th>
        </tr>
      </thead>
      <tbody>
        {matching.length === 0 && (
          <tr>
            <td colSpan={4} className={`${cell} text-gray-500`}>
              {subjects.length === 0
                ? "No subjects yet."
                : query
                  ? `No subjects match "${search.trim()}".`
                  : "No subjects in this batch."}
            </td>
          </tr>
        )}
        {shown.map((s) => (
          <tr key={s.id} className={highlightId === s.id ? "bg-blue-50" : undefined}>
            <td className={cell}>{s.name}</td>
            <td className={cell}>{s.code}</td>
            <td className={cell}>{s.batch || <span className="text-gray-400">-</span>}</td>
            <td className={`${cell} whitespace-nowrap`}>
              <button
                type="button"
                onClick={() => onEdit(s)}
                className="rounded-md border border-blue-600 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50"
              >
                Edit
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    <Pagination
      page={page}
      total={matching.length}
      pageSize={pageSize}
      onPage={setPageNo}
      onPageSize={(n) => {
        setPageSize(n);
        setPageNo(1);
      }}
    />
    </>
  );
}
