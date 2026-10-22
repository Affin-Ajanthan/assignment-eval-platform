"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, Assignment, SelfCheckHistoryRow, SelfCheckKind } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import Message, { MessageState } from "@/components/Message";

const KIND_LABEL: Record<SelfCheckKind, string> = {
  code_similarity: "Code similarity",
  report_similarity: "Report similarity",
  ai_content: "AI content",
};

const STATUS_STYLE: Record<string, string> = {
  done: "bg-green-50 text-green-800",
  running: "bg-blue-50 text-blue-800",
  failed: "bg-red-50 text-red-700",
};

/** How often each student ran each self-check, for monitoring and troubleshooting. */
export default function SelfCheckHistoryPanel({ assignments }: { assignments: Assignment[] }) {
  const [assignmentId, setAssignmentId] = useState<number | null>(assignments[0]?.id ?? null);
  const [rows, setRows] = useState<SelfCheckHistoryRow[] | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (assignmentId === null || !assignments.some((a) => a.id === assignmentId)) {
      setAssignmentId(assignments[0]?.id ?? null);
    }
  }, [assignments, assignmentId]);

  const load = useCallback(async () => {
    if (assignmentId === null) return;
    setMsg(null);
    setLoading(true);
    try {
      setRows(await apiFetch<SelfCheckHistoryRow[]>(`/assignments/${assignmentId}/self-checks`));
    } catch (err) {
      setRows(null);
      setMsg({ text: `Could not load the history: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setLoading(false);
    }
  }, [assignmentId]);

  useEffect(() => {
    load();
  }, [load]);

  const selected = assignments.find((a) => a.id === assignmentId);

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Student Self-Check History</h2>
      <p className="mt-1 text-sm text-gray-600">
        How often each student checked their own submission before the deadline. For monitoring and troubleshooting
        only: repeated checks usually mean a student is improving their work, not misconduct.
      </p>
      {assignments.length === 0 ? (
        <p className="mt-2 text-sm text-gray-600">No assignments yet.</p>
      ) : (
        <>
          <label className="mt-3 block text-sm font-semibold" htmlFor="self-check-assignment">
            Assignment
          </label>
          <div className="mt-1 flex gap-2">
            <select
              id="self-check-assignment"
              value={assignmentId ?? ""}
              onChange={(e) => setAssignmentId(parseInt(e.target.value, 10))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              {assignments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="rounded-md bg-gray-600 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:opacity-60"
            >
              {loading ? "Loading..." : "Refresh"}
            </button>
          </div>
          {selected && (
            <p className="mt-2 text-xs text-gray-600">
              Student self-checks for this assignment: similarity{" "}
              <strong>{selected.student_similarity_check ? "on" : "off"}</strong> · AI content{" "}
              <strong>{selected.student_ai_check ? "on" : "off"}</strong> (change them under Assignments → Edit).
            </p>
          )}
          <Message state={msg} />
          {rows && rows.length === 0 && <p className="mt-3 text-sm text-gray-600">No submissions yet.</p>}
          {rows && rows.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-left">
                    <th className="border border-gray-200 px-3 py-1.5">Student</th>
                    <th className="border border-gray-200 px-3 py-1.5 text-right">Code similarity</th>
                    <th className="border border-gray-200 px-3 py-1.5 text-right">Report similarity</th>
                    <th className="border border-gray-200 px-3 py-1.5 text-right">AI detection</th>
                    <th className="border border-gray-200 px-3 py-1.5">Most recent check</th>
                    <th className="border border-gray-200 px-3 py-1.5">Latest status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.submission_id}>
                      <td className="border border-gray-200 px-3 py-1.5">
                        {r.student_name}
                        <br />
                        <small className="text-gray-500">{r.student_email}</small>
                      </td>
                      <td className="border border-gray-200 px-3 py-1.5 text-right">{r.code_similarity_checks}</td>
                      <td className="border border-gray-200 px-3 py-1.5 text-right">{r.report_similarity_checks}</td>
                      <td className="border border-gray-200 px-3 py-1.5 text-right">{r.ai_checks}</td>
                      <td className="border border-gray-200 px-3 py-1.5">
                        {r.last_check_at ? (
                          <>
                            {formatDateTime(r.last_check_at)}
                            <br />
                            <small className="text-gray-500">{r.latest_kind ? KIND_LABEL[r.latest_kind] : ""}</small>
                          </>
                        ) : (
                          <span className="text-gray-400">never</span>
                        )}
                      </td>
                      <td className="border border-gray-200 px-3 py-1.5">
                        {r.latest_status ? (
                          <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[r.latest_status] ?? ""}`}>
                            {r.latest_status}
                          </span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
