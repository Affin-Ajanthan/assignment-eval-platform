"use client";

/** The row counts an admin list can show per page, and the one it starts with. */
export const PAGE_SIZES = [10, 20, 50];
export const DEFAULT_PAGE_SIZE = 20;

/** How many pages `total` rows make at `size` rows a page (at least 1). */
export const pageCount = (total: number, size: number) => Math.max(1, Math.ceil(total / size));

/** `page` kept inside 1..pageCount, so a list that got shorter (a delete, a search) never shows an empty page. */
export const clampPage = (page: number, total: number, size: number) =>
  Math.min(Math.max(page, 1), pageCount(total, size));

/**
 * Under an admin list: "Rows per page" (10, 20 or 50), "Showing 1-20 of 45" and Previous / Next. Shown whenever the
 * list has rows; Previous / Next are greyed out when there is only one page.
 */
export default function Pagination({
  page,
  total,
  pageSize,
  onPage,
  onPageSize,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}) {
  if (total === 0) return null;
  const pages = pageCount(total, pageSize);
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const button = "rounded-md border border-gray-300 px-3 py-1 text-xs font-semibold hover:bg-gray-50 disabled:opacity-50";

  return (
    <nav aria-label="Pages" className="mt-2 flex flex-wrap items-center justify-between gap-3 text-sm" data-testid="pagination">
      <label className="flex items-center gap-2 text-gray-600">
        Rows per page
        <select
          value={pageSize}
          onChange={(e) => onPageSize(Number(e.target.value))}
          className="rounded-md border border-gray-300 px-2 py-1 text-sm"
          data-testid="page-size"
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <span className="text-gray-600">
        Showing {from}-{to} of {total}
      </span>
      <span className="flex items-center gap-2">
        <button type="button" className={button} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button type="button" className={button} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </span>
    </nav>
  );
}
