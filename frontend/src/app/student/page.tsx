"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, StudentAssignment } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { formatDateTime } from "@/lib/datetime";
import AccountBar from "@/components/AccountBar";
import { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import AssignmentCard from "@/components/student/AssignmentCard";
import SubmissionHistory from "@/components/student/SubmissionHistory";
import { OpenForm } from "@/components/student/labels";

export default function StudentPage() {
  const { user, ready } = useRequireRole("student");

  const [assignments, setAssignments] = useState<StudentAssignment[]>([]);
  // Bumped after every submit / edit / delete, so an open history refreshes.
  const [historyVersion, setHistoryVersion] = useState(0);
  const [openForm, setOpenForm] = useState<OpenForm>(null);
  const [notice, setNotice] = useState<{ assignmentId: number; state: MessageState } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // The submission history loads itself when opened (SubmissionHistory).
  const load = useCallback(async () => {
    setAssignments(await apiFetch<StudentAssignment[]>("/assignments"));
  }, []);

  useEffect(() => {
    if (!ready || !user) return;
    load();
  }, [ready, user, load]);

  async function changed(assignmentId: number, text: string) {
    setNotice({ assignmentId, state: { text, kind: "success" } });
    setHistoryVersion((v) => v + 1);
    await load();
  }

  function askDelete(a: StudentAssignment) {
    setConfirm({
      title: "Delete your submission?",
      message: `Are you sure you want to delete your submission for "${a.name}"? Your uploaded files will be removed. You can submit again before the deadline (${formatDateTime(a.deadline)}).`,
      onConfirm: async () => {
        setConfirmBusy(true);
        try {
          await apiFetch(`/submissions/${a.my_submission!.id}`, { method: "DELETE" });
          await changed(a.id, "Submission deleted.");
        } catch (err) {
          setNotice({ assignmentId: a.id, state: { text: `Could not delete: ${err instanceof Error ? err.message : err}`, kind: "error" } });
        } finally {
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  if (!ready || !user) return null;

  const open = assignments.filter((a) => a.status === "open");
  const past = assignments.filter((a) => a.status === "closed");
  const card = (a: StudentAssignment) => (
    <AssignmentCard
      key={a.id}
      a={a}
      openForm={openForm}
      setOpenForm={setOpenForm}
      onChanged={changed}
      askDelete={askDelete}
      notice={notice?.assignmentId === a.id ? notice.state : null}
    />
  );

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Student portal</h1>
      <p className="mt-1 text-sm text-gray-600">
        Open an assignment, upload your code, report and presentation video, and submit before the deadline. You can
        edit or delete your submission until the deadline or until it has been graded.
      </p>

      {user.subjects.length === 0 && (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">No subjects assigned yet -- ask your admin</p>
      )}

      <section className="mt-6">
        <h2 className="text-lg font-bold">Available assignments</h2>
        {open.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">There are no assignments open for submission right now.</p>
        ) : (
          <ul className="mt-3 space-y-4">{open.map(card)}</ul>
        )}
      </section>

      {past.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-bold">Past assignments</h2>
          <ul className="mt-3 space-y-4">{past.map(card)}</ul>
        </section>
      )}

      <SubmissionHistory version={historyVersion} />

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </div>
  );
}
