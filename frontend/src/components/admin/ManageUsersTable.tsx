"use client";

import { Fragment, useState } from "react";
import { apiFetch, UserInfo } from "@/lib/api";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Message, { MessageState } from "@/components/Message";
import ListFilters, { batchKeyOf, batchOptionsFrom } from "@/components/admin/ListFilters";
import Pagination, { clampPage, DEFAULT_PAGE_SIZE } from "@/components/admin/Pagination";

type UserGroup = { key: string; label: string; users: UserInfo[] };

/** Text in natural order: numbers count by value, so "Student 2" comes before "Student 10". */
const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

/** Students by name in natural order (Student 1, 2, 3 ... 10, 11), then by register number. */
const byNameThenNumber = (a: UserInfo, b: UserInfo) =>
  natural(a.full_name, b.full_name) || natural(a.register_number ?? "", b.register_number ?? "") || a.id - b.id;

/** The group a student is listed under, and the value of that batch in the Batch box. */
const batchKey = (u: UserInfo) => batchKeyOf(u.batch);

/** Students grouped by batch, the batches in order and the students without one last. */
function groupByBatch(users: UserInfo[]): UserGroup[] {
  const byBatch = new Map<string, UserInfo[]>();
  for (const u of users) {
    const key = batchKey(u);
    byBatch.set(key, [...(byBatch.get(key) ?? []), u]);
  }
  return Array.from(byBatch, ([key, list]) => ({
    key,
    label: key === "no-batch" ? "No batch" : `Batch ${key.slice("batch:".length)}`,
    users: list,
  })).sort((a, b) =>
    a.key === "no-batch" ? 1 : b.key === "no-batch" ? -1 : a.label.localeCompare(b.label, undefined, { numeric: true }),
  );
}

/**
 * Existing instructors or students, each with Edit and Delete. Delete goes to DELETE
 * /admin/{instructors|students}/{id}, then `onChanged` reloads the list. Edit does not open a form in the row:
 * `onEdit` hands the user to the page, which fills its own form with it. `highlightId` is the user that form is
 * editing: its row is marked.
 * Students are listed as name, register number and email, grouped by batch, and can be searched by name or
 * register number. Instructors are searched by name or email. Both can be filtered by batch (an instructor's batches
 * are those of their subjects).
 */
export default function ManageUsersTable({
  role,
  users,
  onChanged,
  onEdit,
  highlightId = null,
}: {
  role: "instructor" | "student";
  users: UserInfo[];
  onChanged: () => Promise<void>;
  onEdit: (u: UserInfo) => void;
  highlightId?: number | null;
}) {
  const base = role === "instructor" ? "/admin/instructors" : "/admin/students";
  const label = role === "instructor" ? "instructor" : "student";

  const [search, setSearch] = useState("");
  const [batchFilter, setBatchFilter] = useState("all"); // "all" or a batch key (see batchKeyOf)
  const [pageNo, setPageNo] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE); // rows per page: 10, 20 or 50
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [deleting, setDeleting] = useState(false);

  function askDelete(u: UserInfo) {
    const count = u.submission_count ?? 0;
    const lines =
      role === "student"
        ? [
            `${u.full_name} (${u.email}) will no longer be able to log in.`,
            count
              ? `Their ${count} submission(s) will be deleted too, with all grades, automated evaluations, ` +
                "similarity results and uploaded files."
              : "They have no submissions.",
          ]
        : [
            `${u.full_name} (${u.email}) will no longer be able to log in and is removed from all subjects.`,
            "Grades they gave stay (with their name). Assignments and rubrics they created stay.",
          ];
    setConfirm({
      title: `Delete ${label}?`,
      message: `${lines.join("\n\n")}\n\nThis cannot be undone.`,
      confirmLabel: `Delete ${label}`,
      onConfirm: async () => {
        setDeleting(true);
        setMsg(null);
        try {
          await apiFetch(`${base}/${u.id}`, { method: "DELETE" });
          await onChanged();
          setMsg({ text: `${u.full_name} was deleted.`, kind: "success" });
        } catch (err) {
          setMsg({ text: `Could not delete: ${err instanceof Error ? err.message : err}`, kind: "error" });
        } finally {
          setDeleting(false);
          setConfirm(null);
        }
      },
    });
  }

  const cell = "border-b border-gray-200 px-3 py-2";
  const isStudent = role === "student";
  // An instructor's row has three cells: name, email and actions. A student's has four: name, register number,
  // email and actions.
  const columns = isStudent ? 4 : 3;
  const query = search.trim().toLowerCase();
  // The batches a row belongs to: a student's own, or those of an instructor's subjects ("No batch" when none).
  const keysOf = (u: UserInfo) =>
    isStudent ? [batchKey(u)] : u.subjects.length ? u.subjects.map((s) => batchKeyOf(s.batch)) : ["no-batch"];
  // The batches there are, for the Batch box. A chosen batch that nobody has any more counts as "all".
  const batchOptions = batchOptionsFrom(users.map(keysOf));
  const activeBatch = batchOptions.some((o) => o.key === batchFilter) ? batchFilter : "all";
  const matching = users.filter(
    (u) =>
      (activeBatch === "all" || keysOf(u).includes(activeBatch)) &&
      (!query ||
        u.full_name.toLowerCase().includes(query) ||
        (isStudent ? (u.register_number ?? "") : u.email).toLowerCase().includes(query)),
  );
  const shown = isStudent ? matching.sort(byNameThenNumber) : matching;
  // Only `pageSize` rows per page. Students are put in batch order first, so a batch is not scattered over pages.
  const ordered = isStudent ? groupByBatch(shown).flatMap((g) => g.users) : shown;
  const page = clampPage(pageNo, ordered.length, pageSize);
  const pageRows = ordered.slice((page - 1) * pageSize, page * pageSize);
  const groups: UserGroup[] = isStudent ? groupByBatch(pageRows) : [{ key: "all", label: "", users: pageRows }];

  return (
    <>
      <Message state={msg} />
      {users.length > 0 && (
        <ListFilters
          name={label}
          placeholder={isStudent ? "Name or register number" : "Name or email"}
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
          total={users.length}
          shown={shown.length}
        />
      )}
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className={cell}>Name</th>
              {isStudent && <th className={cell}>Register no.</th>}
              <th className={cell}>Email</th>
              <th className={cell}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr>
                <td colSpan={columns} className={`${cell} text-gray-500`}>
                  {users.length === 0
                    ? `No ${label}s yet.`
                    : query
                      ? `No ${label}s match "${search.trim()}".`
                      : `No ${label}s in this batch.`}
                </td>
              </tr>
            )}
            {groups.map((g) => (
            <Fragment key={g.key}>
            {g.label && (
              <tr data-testid="batch-group">
                <th colSpan={columns} scope="colgroup" className={`${cell} bg-gray-100 text-left`}>
                  {g.label} <span className="font-normal text-gray-500">({g.users.length})</span>
                </th>
              </tr>
            )}
            {g.users.map((u) => (
              <tr key={u.id} className={highlightId === u.id ? "bg-blue-50" : undefined}>
                <td className={cell}>{u.full_name}</td>
                {isStudent && <td className={cell}>{u.register_number || "—"}</td>}
                <td className={cell}>{u.email}</td>
                <td className={`${cell} whitespace-nowrap`}>
                  <button
                    type="button"
                    onClick={() => onEdit(u)}
                    className="rounded-md border border-blue-600 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => askDelete(u)}
                    className="ml-2 rounded-md border border-red-600 px-2.5 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-gray-500 sm:hidden">Swipe the table sideways to see every column.</p>
      <Pagination
        page={page}
        total={ordered.length}
        pageSize={pageSize}
        onPage={setPageNo}
        onPageSize={(n) => {
          setPageSize(n);
          setPageNo(1);
        }}
      />
      <ConfirmDialog request={confirm} busy={deleting} onCancel={() => !deleting && setConfirm(null)} />
    </>
  );
}
