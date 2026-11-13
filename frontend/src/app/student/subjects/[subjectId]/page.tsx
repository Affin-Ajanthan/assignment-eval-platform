"use client";

import BackLink from "@/components/BackLink";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, StudentAssignment, StudentSubject, UpcomingAssignment } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { recordRecentSubject } from "@/lib/recentSubjects";
import { formatDateTime } from "@/lib/datetime";
import AccountBar from "@/components/AccountBar";
import { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import AssignmentCard from "@/components/student/AssignmentCard";
import AssignmentRow from "@/components/student/AssignmentRow";
import JoinForm from "@/components/student/JoinForm";
import { OpenForm } from "@/components/student/labels";
import PageLoading from "@/components/PageLoading";
import PageHeader from "@/components/PageHeader";

/** The filter on "Available assignments": all, still to hand in, already handed in. */
type AssignmentFilter = "all" | "need" | "submitted";
const FILTERS: { id: AssignmentFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "need", label: "Need to submit" },
  { id: "submitted", label: "Submitted" },
];

/** The subject's teachers: names for everyone, and e-mail addresses for a student who joined (the server only sends those to them). */
function TeacherList({ subject }: { subject: StudentSubject }) {
  return (
    <section className="mt-2" data-testid="teachers">
      <h2 className="text-xl font-semibold">{subject.teachers.length === 1 ? "Teacher" : "Teachers"}</h2>
      {subject.teachers.length === 0 ? (
        <p className="empty-state mt-2">No teacher is assigned to this subject yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white text-sm shadow-sm">
          {subject.teachers.map((t) => (
            <li key={`${t.name}-${t.email}`} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3">
              <span className="font-semibold">{t.name}</span>
              {t.email && (
                <a href={`mailto:${t.email}`} className="text-blue-700 hover:underline">
                  {t.email}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One subject of the student: /student/subjects/<id>, opened from the subject boxes on /student. A student who has
 * not joined it gets the password box (and the teachers' names); once they join, the page is reloaded and shows the
 * teachers and the assignments. The server refuses the assignments of a subject they have not joined anyway.
 */
export default function StudentSubjectPage() {
  const { user, ready } = useRequireRole("student");
  const router = useRouter();
  const subjectId = Number(useParams<{ subjectId: string }>().subjectId);

  // The subject as the student sees it. Its assignments are asked for only if they joined it.
  const [subject, setSubject] = useState<StudentSubject | null>(null);
  // null until the first load: "no assignments" is shown only once the list has arrived.
  const [assignments, setAssignments] = useState<StudentAssignment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Not open yet: name and dates only. A failure here just leaves the list out.
  const [upcoming, setUpcoming] = useState<UpcomingAssignment[]>([]);
  const [openForm, setOpenForm] = useState<OpenForm>(null);
  // The available assignment whose details are open (none at first).
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<AssignmentFilter>("all");
  const [notice, setNotice] = useState<{ assignmentId: number; state: MessageState } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAssignments(await apiFetch<StudentAssignment[]>(`/assignments?subject_id=${subjectId}`));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, [subjectId]);

  const loadUpcoming = useCallback(() => {
    apiFetch<UpcomingAssignment[]>("/upcoming-assignments")
      .then((all) => setUpcoming(all.filter((u) => u.subject_id === subjectId)))
      .catch(() => setUpcoming([]));
  }, [subjectId]);

  // A box on the home page's "Due in the next 7 days" links here with ?assignment=<id>: open that one's details
  // once the list has arrived (only the first time, so closing it again sticks).
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current || assignments === null) return;
    deepLinked.current = true;
    const wanted = Number(new URLSearchParams(window.location.search).get("assignment"));
    if (wanted && assignments.some((a) => a.id === wanted && a.status === "open")) setExpandedId(wanted);
  }, [assignments]);

  // First find out whether the student is in this subject; only then are its assignments asked for.
  useEffect(() => {
    if (!ready || !user) return;
    let cancelled = false;
    (async () => {
      try {
        const all = await apiFetch<StudentSubject[]>("/student/subjects");
        const found = all.find((s) => s.id === subjectId);
        if (cancelled) return;
        if (!found) {
          router.replace("/student");
          return;
        }
        setSubject(found);
        recordRecentSubject("student", user.id, subjectId); // for "Recently viewed" on the home page
        if (found.joined) {
          load();
          loadUpcoming();
        }
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, user, subjectId, router, load, loadUpcoming]);

  async function changed(assignmentId: number, text: string) {
    setNotice({ assignmentId, state: { text, kind: "success" } });
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

  const listed = assignments ?? [];
  const deadline = (a: StudentAssignment) => new Date(a.deadline).getTime();
  // Open ones by the deadline that comes first; past ones with the most recent first.
  const open = listed.filter((a) => a.status === "open").sort((x, y) => deadline(x) - deadline(y));
  // The filter above the list: how many there are of each, and the ones to show.
  const counts: Record<AssignmentFilter, number> = {
    all: open.length,
    need: open.filter((a) => !a.my_submission).length,
    submitted: open.filter((a) => a.my_submission).length,
  };
  // The one whose details are open stays in the list, so handing it in does not make it vanish under its own message.
  const shownOpen = open.filter(
    (a) => filter === "all" || a.id === expandedId || (filter === "need" ? !a.my_submission : !!a.my_submission),
  );
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
      <div className="mb-4">
        <BackLink href="/student" label="All subjects" testId="back-to-subjects" />
      </div>

      <PageHeader
        title={subject?.name ?? "Subject"}
        description={
          subject ? (
            <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span>{subject.code}</span>
              {subject.batch && <span>Batch {subject.batch}</span>}
              <span>{subject.joined ? "You joined this subject" : "You have not joined this subject"}</span>
            </span>
          ) : undefined
        }
      />

      {loadError && !subject && (
        <p role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load this subject: {loadError}
        </p>
      )}

      {/* Not joined: the teachers' names and the password box. The assignments are not shown. */}
      {subject && !subject.joined && (
        <>
          <TeacherList subject={subject} />
          <JoinForm subject={subject} />
        </>
      )}

      {subject?.joined && (
        <>
          <TeacherList subject={subject} />

          <section className="mt-6 scroll-mt-4" id="available">
            <h2 className="text-xl font-semibold">Available assignments</h2>
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
              !loadError && <p className="mt-2 text-sm text-gray-500">Loading the assignments...</p>
            ) : open.length === 0 ? (
              <p className="empty-state mt-2">There are no assignments open for submission right now.</p>
            ) : (
              <>
              {/* Which of them to show: all, the ones still to hand in, or the ones already handed in. */}
              <div role="group" aria-label="Filter assignments" className="mt-3 flex flex-wrap gap-2" data-testid="assignment-filter">
                {FILTERS.map((f) => {
                  const active = filter === f.id;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        setFilter(f.id);
                        setExpandedId(null);
                      }}
                      className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                        active ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                      }`}
                      data-testid={`filter-${f.id}`}
                    >
                      {f.label} ({counts[f.id]})
                    </button>
                  );
                })}
              </div>
              {shownOpen.length === 0 ? (
                <p className="empty-state mt-3" data-testid="filter-empty">
                  {filter === "need"
                    ? "Nothing left to submit -- you have handed in every open assignment."
                    : "You have not submitted any of the open assignments yet."}
                </p>
              ) : (
              // One line each, with the due date; pressing one opens its details under it (one at a time).
              <ul className="mt-3 space-y-3" data-testid="available-list">
                {shownOpen.map((a) => (
                  <AssignmentRow
                    key={a.id}
                    a={a}
                    expanded={expandedId === a.id}
                    onToggle={() => setExpandedId(expandedId === a.id ? null : a.id)}
                  >
                    {card(a)}
                  </AssignmentRow>
                ))}
              </ul>
              )}
              </>
            )}
          </section>

          {upcoming.length > 0 && (
            <section className="mt-8" data-testid="coming-soon">
              <h2 className="text-xl font-semibold">Coming soon</h2>
              <p className="mt-1 text-sm text-gray-600">
                Not open yet. The details appear here when each one opens.
              </p>
              <ul className="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white text-sm shadow-sm">
                {upcoming.map((u) => (
                  <li key={`${u.subject_id}-${u.name}`} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3">
                    <span>
                      <span className="font-semibold">{u.name}</span>
                      {u.assignment_type === "code_challenge" && <span className="ml-2 text-xs text-gray-500">Code challenge</span>}
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
              <h2 className="text-xl font-semibold">Past assignments</h2>
              <ul className="mt-3 space-y-4">{past.map(card)}</ul>
            </section>
          )}
        </>
      )}

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
      </main>
    </>
  );
}
