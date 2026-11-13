"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, Submission } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { lateText, markWithPenalty } from "@/lib/late";
import Badge from "@/components/Badge";
import Message, { MessageState } from "@/components/Message";

/** "Graded" only when there is a mark to show; a submission without one is still just "Submitted". */
const isGraded = (s: Submission) => s.status === "graded" && s.final_mark != null;

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
    <section className="mt-8 card" data-testid="submission-history">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <h2 className="text-xl font-semibold">My submission history</h2>
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
            <p className="empty-state mt-2">You haven&apos;t submitted anything yet.</p>
          )}
          {submissions !== null && submissions.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-left">
                    <th className="border-b border-gray-200 px-3 py-2">Subject</th>
                    <th className="border-b border-gray-200 px-3 py-2">Assignment</th>
                    <th className="border-b border-gray-200 px-3 py-2">Submitted</th>
                    <th className="border-b border-gray-200 px-3 py-2">Status</th>
                    <th className="border-b border-gray-200 px-3 py-2">Marks</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((s) => (
                    <tr key={s.id}>
                      <td className="border-b border-gray-200 px-3 py-2">{s.subject_name}</td>
                      <td className="border-b border-gray-200 px-3 py-2">{s.assignment_name}</td>
                      <td className="border-b border-gray-200 px-3 py-2">
                        {formatDateTime(s.submitted_at)}
                        {s.late_seconds != null && (
                          <div className="text-xs font-semibold text-red-800" data-testid="late-note">
                            Late · {lateText(s.late_seconds)} after the deadline
                          </div>
                        )}
                      </td>
                      <td className="border-b border-gray-200 px-3 py-2">
                        <Badge bold={false} tone={isGraded(s) ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"}>
                          {isGraded(s) ? "Graded" : "Submitted"}
                        </Badge>
                      </td>
                      <td className="border-b border-gray-200 px-3 py-2">
                        {s.final_mark == null ? (
                          <span className="text-gray-500">
                            -<span className="sr-only"> not graded yet</span>
                          </span>
                        ) : (
                          markWithPenalty(s.raw_mark, s.final_mark, s.max_mark, s.late_penalty_percent, s.late_penalty_marks)
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
