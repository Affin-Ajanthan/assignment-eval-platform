"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, Submission } from "@/lib/api";
import { formatDateTime, formatMark } from "@/lib/datetime";
import Badge from "@/components/Badge";
import Message, { MessageState } from "@/components/Message";

/**
 * Every submission the student has made, across subjects -- including ones to
 * assignments that were since deleted, which have no card above. Collapsed by
 * default and loaded only when opened. `version` changes whenever the student
 * submits, edits or deletes, so an open history refreshes itself.
 */
export default function SubmissionHistory({ version }: { version: number }) {
  const [open, setOpen] = useState(false);
  const [submissions, setSubmissions] = useState<Submission[] | null>(null);
  const [msg, setMsg] = useState<MessageState>(null);

  const load = useCallback(async () => {
    try {
      setSubmissions(await apiFetch<Submission[]>("/submissions"));
      setMsg(null);
    } catch (err) {
      setMsg({ text: `Could not load your submissions: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, version, load]);

  return (
    <section className="mt-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm" data-testid="submission-history">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <h2 className="text-lg font-bold">My submission history</h2>
        <span className="text-xs font-semibold text-blue-700">{open ? "Close ▴" : "Open ▾"}</span>
      </button>
      {!open && (
        <p className="mt-1 text-sm text-gray-600">
          Every submission you have made, in all subjects, including assignments that are no longer listed.
        </p>
      )}
      {open && (
        <>
          <Message state={msg} />
          {submissions === null && !msg && <p className="mt-2 text-sm text-gray-500">Loading...</p>}
          {submissions !== null && submissions.length === 0 && (
            <p className="mt-2 text-sm text-gray-600">You haven&apos;t submitted anything yet.</p>
          )}
          {submissions !== null && submissions.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-left">
                    <th className="border border-gray-200 px-3 py-1.5">Subject</th>
                    <th className="border border-gray-200 px-3 py-1.5">Assignment</th>
                    <th className="border border-gray-200 px-3 py-1.5">Submitted</th>
                    <th className="border border-gray-200 px-3 py-1.5">Status</th>
                    <th className="border border-gray-200 px-3 py-1.5">Marks</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((s) => (
                    <tr key={s.id}>
                      <td className="border border-gray-200 px-3 py-1.5">{s.subject_name}</td>
                      <td className="border border-gray-200 px-3 py-1.5">{s.assignment_name}</td>
                      <td className="border border-gray-200 px-3 py-1.5">{formatDateTime(s.submitted_at)}</td>
                      <td className="border border-gray-200 px-3 py-1.5">
                        <Badge bold={false} tone={s.status === "graded" ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"}>
                          {s.status === "graded" ? "Graded" : "Submitted"}
                        </Badge>
                      </td>
                      <td className="border border-gray-200 px-3 py-1.5">{formatMark(s.final_mark, s.max_mark)}</td>
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
