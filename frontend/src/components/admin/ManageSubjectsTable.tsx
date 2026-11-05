"use client";

import { useState } from "react";
import { Subject } from "@/lib/api";
import Pagination, { clampPage, DEFAULT_PAGE_SIZE } from "@/components/admin/Pagination";

/**
 * Existing subjects, each with Edit. Edit does not open a form in the row: `onEdit` hands the subject to the
 * page, which fills its own form with it (and saves with PUT /admin/subjects/{id}). `highlightId` is the
 * subject that form is editing: its row is marked. Only the chosen number of rows (10, 20 or 50) is shown; the rest
 * are on the next pages.
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
  const page = clampPage(pageNo, subjects.length, pageSize);
  const shown = subjects.slice((page - 1) * pageSize, page * pageSize);

  return (
    <>
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
        {subjects.length === 0 && (
          <tr>
            <td colSpan={4} className={`${cell} text-gray-500`}>
              No subjects yet.
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
      total={subjects.length}
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
