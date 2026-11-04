"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, StudentAssignment, UpcomingAssignment } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { formatDateTime } from "@/lib/datetime";
import AccountBar from "@/components/AccountBar";
import { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import AssignmentCard from "@/components/student/AssignmentCard";
import SubmissionHistory from "@/components/student/SubmissionHistory";
import { OpenForm } from "@/components/student/labels";
import PageLoading from "@/components/PageLoading";

export default function StudentPage() {
  const { user, ready } = useRequireRole("student");

  // null until the first load: "no assignments" is shown only once the list has arrived.
  const [assignments, setAssignments] = useState<StudentAssignment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Which subject's assignments are listed, for a student in more than one.
  const [subjectFilter, setSubjectFilter] = useState<number | "all">("all");
  // Not open yet: name and dates only. A failure here just leaves the list out.
  const [upcoming, setUpcoming] = useState<UpcomingAssignment[]>([]);
  // Bumped after every submit / edit / delete, so an open history refreshes.
  const [historyVersion, setHistoryVersion] = useState(0);
  const [openForm, setOpenForm] = useState<OpenForm>(null);
  const [notice, setNotice] = useState<{ assignmentId: number; state: MessageState } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // The submission history loads itself when opened (SubmissionHistory).
  const load = useCallback(async () => {
    try {
      setAssignments(await apiFetch<StudentAssignment[]>("/assignments"));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (!ready || !user) return;
    load();
    apiFetch<UpcomingAssignment[]>("/upcoming-assignments")
      .then(setUpcoming)
      .catch(() => setUpcoming([]));
  }, [ready, user, load]);

  async function changed(assignmentId: number, text: string) {
    setNotice({ assignmentId, state: { text, kind: "success" } });
    setHistoryVersion((v) => v + 1);
    await load();
  }

  function askDelete(a: StudentAssignment) {
    setConfirm({
      title: "Delete your submission?",
      message: a.assignment_type === "code_challenge"
        ? `Are you sure you want to delete your submission for "${a.name}"? Your answers and marks for every task will be removed, and you will have to hand the tasks in again before the deadline (${formatDateTime(a.deadline)}).`
        : `Are you sure you want to delete your submission for "${a.name}"? Your uploaded files will be removed. You can submit again before the deadline (${formatDateTime(a.deadline)}).`,
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

  if (!ready || !user) return <PageLoading />;

  const subjects = Array.from(
    new Map((assignments ?? []).map((a) => [a.subject_id, a.subject_name] as const)).entries(),
  ).sort((x, y) => x[1].localeCompare(y[1]));
  const listed = (assignments ?? []).filter((a) => subjectFilter === "all" || a.subject_id === subjectFilter);
  const deadline = (a: StudentAssignment) => new Date(a.deadline).getTime();
  const chosenSubject = subjects.find(([id]) => id === subjectFilter)?.[1];
  const comingSoon = upcoming.filter((u) => subjectFilter === "all" || u.subject_name === chosenSubject);
  // Open ones by the deadline that comes first; past ones with the most recent first.
  const open = listed.filter((a) => a.status === "open").sort((x, y) => deadline(x) - deadline(y));
  const past = listed.filter((a) => a.status === "closed").sort((x, y) => deadline(y) - deadline(x));
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
    <>
      <AccountBar user={user} width="max-w-4xl" />
      <main className="mx-auto max-w-4xl px-4 py-8">

      <h1 className="text-2xl font-bold">Student portal</h1>
      <p className="mt-1 text-sm text-gray-600">
        Submit your work before the deadline. You can edit or delete a submission until the deadline or until it is
        graded; each assignment below says what it accepts.
      </p>

      {user.subjects.length === 0 && (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">No subjects assigned yet -- ask your admin</p>
      )}

      {subjects.length > 1 && (
        <div className="mt-4">
          <label className="block text-sm font-semibold" htmlFor="subject-filter">
            Subject
          </label>
          <select
            id="subject-filter"
            value={subjectFilter}
            onChange={(e) => setSubjectFilter(e.target.value === "all" ? "all" : Number(e.target.value))}
            className="mt-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="all">All subjects</option>
            {subjects.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </div>
      )}

      <section className="mt-6">
        <h2 className="text-lg font-bold">Available assignments</h2>
        {loadError && (
          <div role="alert" className="mt-2 flex flex-wrap items-center gap-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            <span>Could not load your assignments: {loadError}</span>
            <button
              type="button"
              onClick={load}
              className="btn-danger rounded-md px-3 py-1 text-xs font-semibold"
            >
              Try again
            </button>
          </div>
        )}
        {assignments === null ? (
          !loadError && <p className="mt-2 text-sm text-gray-500">Loading your assignments...</p>
        ) : open.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">There are no assignments open for submission right now.</p>
        ) : (
          <ul className="mt-3 space-y-4">{open.map(card)}</ul>
        )}
      </section>

      {comingSoon.length > 0 && (
        <section className="mt-8" data-testid="coming-soon">
          <h2 className="text-lg font-bold">Coming soon</h2>
          <p className="mt-1 text-sm text-gray-600">
            Not open yet. The details appear here when each one opens.
          </p>
          <ul className="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white text-sm shadow-sm">
            {comingSoon.map((u) => (
              <li key={`${u.subject_name}-${u.name}`} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3">
                <span>
                  <span className="font-semibold">{u.name}</span>
                  {u.assignment_type === "code_challenge" && <span className="ml-2 text-xs text-gray-500">Code challenge</span>}
                  <span className="block text-xs text-gray-500">{u.subject_name}</span>
                </span>
                <span className="text-xs text-gray-700">
                  Opens {formatDateTime(u.available_from)} · Deadline {formatDateTime(u.deadline)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {past.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-bold">Past assignments</h2>
          <ul className="mt-3 space-y-4">{past.map(card)}</ul>
        </section>
      )}

      <SubmissionHistory version={historyVersion} />

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
      </main>
    </>
  );
}
