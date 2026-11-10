"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, Assignment, Rubric, subjectLabel } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import { recordRecentSubject } from "@/lib/recentSubjects";
import AccountBar from "@/components/AccountBar";
import AssignmentKindChooser from "@/components/instructor/AssignmentKindChooser";
import PageTabs, { tabPanelProps } from "@/components/instructor/PageTabs";
import RubricsSection from "@/components/instructor/RubricsSection";
import PageHeader from "@/components/PageHeader";
import PageLoading from "@/components/PageLoading";

type SubjectTab = "assignments" | "rubrics";
const SUBJECT_TABS: SubjectTab[] = ["assignments", "rubrics"];

/**
 * One subject of the instructor: /instructor/subjects/<id>, opened from the subject boxes on /instructor. Two
 * sections: the assignments (create, edit, delete, and Open to work on one) and the rubrics. The Student access
 * button next to the subject name opens the page where the password and registration are set.
 */
export default function InstructorSubjectPage() {
  const { user, ready } = useRequireRole("instructor");
  const router = useRouter();

  // The subject comes from the address, and only one the instructor teaches counts.
  const routeSubject = Number(useParams<{ subjectId: string }>().subjectId);
  const subjectId: number | null = user?.subjects.some((s) => s.id === routeSubject) ? routeSubject : null;
  useEffect(() => {
    if (ready && user && subjectId === null) router.replace("/instructor");
  }, [ready, user, subjectId, router]);
  // For "Recently viewed" on the home page.
  useEffect(() => {
    if (user && subjectId !== null) recordRecentSubject("instructor", user.id, subjectId);
  }, [user, subjectId]);

  // Which section is shown; ?tab= in the address, so a reload or a link back from an assignment page opens the same one.
  const [tab, setTab] = useState<SubjectTab>("assignments");
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (SUBJECT_TABS.includes(wanted as SubjectTab)) setTab(wanted as SubjectTab);
  }, []);
  function changeTab(next: SubjectTab) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url);
  }

  const [rubrics, setRubrics] = useState<Rubric[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);

  const reload = useCallback(async () => {
    if (subjectId === null) return;
    const [r, a] = await Promise.all([
      apiFetch<Rubric[]>(`/rubrics?subject_id=${subjectId}`),
      apiFetch<Assignment[]>(`/assignments?subject_id=${subjectId}`),
    ]);
    setRubrics(r);
    setAssignments(a);
  }, [subjectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (!ready || !user) return <PageLoading />;
  const currentSubject = user.subjects.find((s) => s.id === subjectId);

  return (
    <>
      <AccountBar user={user} width="max-w-6xl" />
      <main className="mx-auto max-w-6xl px-4 py-8">

      <PageHeader
        divider={false}
        back={{ href: "/instructor", label: "All subjects" }}
        title={currentSubject ? subjectLabel(currentSubject) : "Subject"}
        description="Create and edit the assignments and rubrics of this subject. Open an assignment to grade its submissions, check them for copying or run the automated evaluator."
      >
        {subjectId !== null && (
          <Link
            href={`/instructor/subjects/${subjectId}/access`}
            className="btn-secondary rounded-md px-4 py-2 text-sm font-semibold"
            data-testid="student-access-button"
          >
            Student access
          </Link>
        )}
      </PageHeader>

      {subjectId !== null && (
        <>
          <PageTabs
            label="Subject sections"
            tab={tab}
            onChange={changeTab}
            tabs={[
              { id: "assignments", label: "Assignments" },
              { id: "rubrics", label: "Rubrics" },
            ]}
          />

          <div {...tabPanelProps("assignments", tab)}>
            <AssignmentKindChooser subjectId={subjectId} assignments={assignments} />
          </div>

          <div {...tabPanelProps("rubrics", tab)}>
            <RubricsSection subjectId={subjectId} rubrics={rubrics} onChanged={reload} />
          </div>
        </>
      )}
      </main>
    </>
  );
}
