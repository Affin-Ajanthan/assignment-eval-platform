"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, Subject, subjectLabel, UserInfo } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import Message, { MessageState } from "@/components/Message";
import AdminTabs, { adminPanelProps, AdminTab, isAdminTab } from "@/components/admin/AdminTabs";
import ManageSubjectsTable from "@/components/admin/ManageSubjectsTable";
import StudentIdFields, { BatchCombobox } from "@/components/admin/StudentIdFields";
import { batchList, ownNumberOf, registerNumberFor } from "@/lib/registerNumber";
import ManageUsersTable from "@/components/admin/ManageUsersTable";
import MultiSelect from "@/components/admin/MultiSelect";
import PageLoading from "@/components/PageLoading";
import PageHeader, { StatTile } from "@/components/PageHeader";

export default function AdminPage() {
  const { user, ready } = useRequireRole("admin");

  // Which section is shown; ?tab= in the address, so a reload or a shared link opens the same one.
  const [tab, setTab] = useState<AdminTab>("subjects");
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (isAdminTab(wanted)) setTab(wanted);
  }, []);
  function changeTab(next: AdminTab) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url);
  }

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [instructors, setInstructors] = useState<UserInfo[]>([]);
  const [students, setStudents] = useState<UserInfo[]>([]);

  const [subjectName, setSubjectName] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [subjectBatch, setSubjectBatch] = useState("");
  const [subjectInstructors, setSubjectInstructors] = useState<Set<number>>(new Set()); // who teaches it
  const [subjectMsg, setSubjectMsg] = useState<MessageState>(null);
  // The subject whose details the form holds (Edit in the list fills the form), or null while it adds a new one.
  const [editingSubject, setEditingSubject] = useState<Subject | null>(null);
  const subjectFormRef = useRef<HTMLFormElement>(null);

  const [instructorName, setInstructorName] = useState("");
  const [instructorEmail, setInstructorEmail] = useState("");
  const [instructorPassword, setInstructorPassword] = useState("");
  const [instructorSubjects, setInstructorSubjects] = useState<Set<number>>(new Set());
  const [instructorMsg, setInstructorMsg] = useState<MessageState>(null);
  const [editingInstructor, setEditingInstructor] = useState<UserInfo | null>(null);
  const instructorFormRef = useRef<HTMLFormElement>(null);

  const [studentName, setStudentName] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [studentPassword, setStudentPassword] = useState("");
  const [studentBatch, setStudentBatch] = useState("");
  const [studentOwnNumber, setStudentOwnNumber] = useState(""); // the last part of TST/<batch>/<number>
  const [studentMsg, setStudentMsg] = useState<MessageState>(null);
  // The student whose details the form holds (Edit in the list fills the form), or null while it adds a new one.
  const [editingStudent, setEditingStudent] = useState<UserInfo | null>(null);
  const studentFormRef = useRef<HTMLFormElement>(null);

  const loadSubjects = useCallback(async () => {
    setSubjects(await apiFetch<Subject[]>("/admin/subjects"));
  }, []);
  const loadInstructors = useCallback(async () => {
    setInstructors(await apiFetch<UserInfo[]>("/admin/instructors"));
  }, []);
  const loadStudents = useCallback(async () => {
    setStudents(await apiFetch<UserInfo[]>("/admin/students"));
  }, []);

  // The batches there are (students' and subjects'), the choices of every Batch box.
  const batches = batchList([...students, ...subjects]);

  useEffect(() => {
    if (!ready) return;
    loadSubjects();
    loadInstructors();
    loadStudents();
  }, [ready, loadSubjects, loadInstructors, loadStudents]);

  /** Brings a form into view and puts the cursor in its first box (after Edit fills it). */
  function showForm(form: HTMLFormElement | null) {
    form?.scrollIntoView({ behavior: "smooth", block: "start" });
    form?.querySelector("input")?.focus({ preventScroll: true });
  }

  function clearSubjectForm() {
    setEditingSubject(null);
    setSubjectName("");
    setSubjectCode("");
    setSubjectBatch("");
    setSubjectInstructors(new Set());
  }

  /** Edit in the subjects list: the form takes the subject's details and comes into view. */
  function startEditSubject(s: Subject) {
    setEditingSubject(s);
    setSubjectName(s.name);
    setSubjectCode(s.code);
    setSubjectBatch(s.batch ?? "");
    setSubjectInstructors(new Set(s.instructor_ids ?? []));
    setSubjectMsg(null);
    showForm(subjectFormRef.current);
  }

  async function handleSaveSubject(e: FormEvent) {
    e.preventDefault();
    setSubjectMsg(null);
    const editing = editingSubject;
    try {
      const details = {
        name: subjectName,
        code: subjectCode,
        batch: subjectBatch,
        instructor_ids: Array.from(subjectInstructors),
      };
      if (editing) {
        await apiFetch(`/admin/subjects/${editing.id}`, { method: "PUT", json: details });
        setSubjectMsg({ text: "Saved.", kind: "success" });
      } else {
        await apiFetch("/admin/subjects", { method: "POST", json: details });
        setSubjectMsg({ text: "Subject added.", kind: "success" });
      }
      clearSubjectForm();
      // The instructors' own subject lists change with it.
      await Promise.all([loadSubjects(), loadInstructors()]);
    } catch (err) {
      setSubjectMsg({
        text: `Failed to ${editing ? "save" : "add"} subject: ${err instanceof Error ? err.message : err}`,
        kind: "error",
      });
    }
  }

  function clearInstructorForm() {
    setEditingInstructor(null);
    setInstructorName("");
    setInstructorEmail("");
    setInstructorPassword("");
    setInstructorSubjects(new Set());
  }

  /** Edit in the instructors list: the form takes the instructor's details and comes into view. */
  function startEditInstructor(u: UserInfo) {
    setEditingInstructor(u);
    setInstructorName(u.full_name);
    setInstructorEmail(u.email);
    setInstructorPassword("");
    setInstructorSubjects(new Set(u.subjects.map((x) => x.id)));
    setInstructorMsg(null);
    showForm(instructorFormRef.current);
  }

  // The instructor being edited was deleted from the list: the form goes back to adding a new one.
  useEffect(() => {
    if (editingInstructor && !instructors.some((u) => u.id === editingInstructor.id)) clearInstructorForm();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instructors, editingInstructor]);

  async function handleSaveInstructor(e: FormEvent) {
    e.preventDefault();
    setInstructorMsg(null);
    const editing = editingInstructor;
    try {
      const details = { full_name: instructorName, email: instructorEmail, subject_ids: Array.from(instructorSubjects) };
      if (editing) {
        // A blank password keeps the current one.
        await apiFetch(`/admin/instructors/${editing.id}`, {
          method: "PUT",
          json: { ...details, password: instructorPassword || null },
        });
        setInstructorMsg({
          text: instructorPassword
            ? `Saved. The new password is active and ${instructorName} has been logged out of open sessions.`
            : "Saved.",
          kind: "success",
        });
      } else {
        await apiFetch("/admin/instructors", { method: "POST", json: { ...details, password: instructorPassword } });
        setInstructorMsg({ text: "Instructor created.", kind: "success" });
      }
      clearInstructorForm();
      // The subjects the instructor was given or lost also change who teaches those subjects.
      await Promise.all([loadInstructors(), loadSubjects()]);
    } catch (err) {
      setInstructorMsg({
        text: `Failed to ${editing ? "save" : "create"} instructor: ${err instanceof Error ? err.message : err}`,
        kind: "error",
      });
    }
  }

  function clearStudentForm() {
    setEditingStudent(null);
    setStudentName("");
    setStudentEmail("");
    setStudentPassword("");
    setStudentBatch("");
    setStudentOwnNumber("");
  }

  /** Edit in the students list: the form takes the student's details and comes into view. */
  function startEditStudent(s: UserInfo) {
    setEditingStudent(s);
    setStudentName(s.full_name);
    setStudentEmail(s.email);
    setStudentPassword("");
    setStudentBatch(s.batch ?? "");
    setStudentOwnNumber(ownNumberOf(s.register_number ?? "", s.batch ?? ""));
    setStudentMsg(null);
    showForm(studentFormRef.current);
  }

  // The student being edited was deleted from the list: the form goes back to adding a new one.
  useEffect(() => {
    if (editingStudent && !students.some((s) => s.id === editingStudent.id)) clearStudentForm();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [students, editingStudent]);

  async function handleSaveStudent(e: FormEvent) {
    e.preventDefault();
    setStudentMsg(null);
    const editing = editingStudent;
    try {
      const details = {
        full_name: studentName,
        email: studentEmail,
        batch: studentBatch,
        register_number: registerNumberFor(studentBatch, studentOwnNumber),
      };
      if (editing) {
        // A blank password keeps the current one.
        await apiFetch(`/admin/students/${editing.id}`, {
          method: "PUT",
          json: { ...details, password: studentPassword || null },
        });
        setStudentMsg({
          text: studentPassword
            ? `Saved. The new password is active and ${studentName} has been logged out of open sessions.`
            : "Saved.",
          kind: "success",
        });
      } else {
        await apiFetch("/admin/students", { method: "POST", json: { ...details, password: studentPassword } });
        setStudentMsg({ text: "Student created.", kind: "success" });
      }
      clearStudentForm();
      await loadStudents();
    } catch (err) {
      setStudentMsg({
        text: `Failed to ${editing ? "save" : "create"} student: ${err instanceof Error ? err.message : err}`,
        kind: "error",
      });
    }
  }

  if (!ready || !user) return <PageLoading />;

  return (
    <>
      <AccountBar user={user} width="max-w-6xl" />
      <main className="mx-auto max-w-6xl px-4 py-8">

      <PageHeader
        title="Admin dashboard"
         description="Create subjects, then create instructor accounts and assign them to subjects. Students are not assigned here: every student sees each subject, and joins it with the password its instructor sets. You can edit subjects, instructors and students at any time. Everyone logs in with the credentials you set here -- there's no self-signup."
     />
      <div className="grid grid-cols-3 gap-3" data-testid="admin-overview">
        <StatTile label="Subjects" value={subjects.length} href="#subjects" />
        <StatTile label="Instructors" value={instructors.length} href="#instructors" />
        <StatTile label="Students" value={students.length} href="#students" />
      </div>

      <AdminTabs
        tab={tab}
        onChange={changeTab}
        counts={{ subjects: subjects.length, instructors: instructors.length, students: students.length }}
      />

      {/* Subjects */}
           <div {...adminPanelProps("subjects", tab)}>
      <section className="mt-6 card scroll-mt-4" id="subjects">
        <h2 className="text-xl font-semibold">Subjects</h2>
        {/* The form beside the list on wide screens, so nothing is a long scroll away. */}
        <div className="mt-4 grid items-start gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <form
          ref={subjectFormRef}
          onSubmit={handleSaveSubject}
          className={`scroll-mt-4 rounded-md border p-4 ${
            editingSubject ? "border-blue-200 bg-blue-50" : "border-gray-200 bg-gray-50"
          }`}
          data-testid="subject-form"
        >
          <h3 className="mb-3 text-base font-semibold">
            {editingSubject ? `Edit subject: ${editingSubject.name}` : "Add a subject"}
          </h3>

          <label className="block text-sm font-semibold" htmlFor="subject_name">
            Subject name
          </label>
          <input
            id="subject_name"
            required
            value={subjectName}
            onChange={(e) => setSubjectName(e.target.value)}
            placeholder="Data Structures"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold" htmlFor="subject_code">
            Subject code
          </label>
          <input
            id="subject_code"
            required
            value={subjectCode}
            onChange={(e) => setSubjectCode(e.target.value)}
            placeholder="CS201"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold" htmlFor="subject_batch">
            Batch <span className="font-normal text-gray-500">(pick one or type; the same code can be in every batch)</span>
          </label>
          <div className="mb-3">
            <BatchCombobox
              id="subject_batch"
              value={subjectBatch}
              onChange={setSubjectBatch}
              options={batches}
              testId="subject-batch"
            />
          </div>
          <label className="block text-sm font-semibold" htmlFor="subject_instructors">
            Instructors <span className="font-normal text-gray-500">(search and pick several)</span>
          </label>
          <div className="mb-3">
            <MultiSelect
              id="subject_instructors"
              options={instructors.map((u) => ({ id: u.id, label: u.full_name, detail: u.email }))}
              selected={subjectInstructors}
              onChange={setSubjectInstructors}
              placeholder="Search instructors..."
              emptyText="No instructors yet. Add one in the Instructors tab."
              testId="subject-instructors-input"
            />
          </div>
          <div className="flex gap-2">
            <button className="btn-primary rounded-md px-4 py-2 text-sm font-semibold">
              {editingSubject ? "Save changes" : "Add subject"}
            </button>
            {editingSubject && (
              <button
                type="button"
                onClick={clearSubjectForm}
                className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
              >
                Cancel
              </button>
            )}
          </div>
          <Message state={subjectMsg} />
        </form>

         <div className="min-w-0">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Existing subjects</h3>
        <ManageSubjectsTable
          subjects={subjects}
          onEdit={startEditSubject}
          highlightId={editingSubject?.id ?? null}
        />
        </div>
        </div>

      </section>
      </div>

      {/* Instructors */}
      <div {...adminPanelProps("instructors", tab)}>
      <section className="mt-6 card scroll-mt-4" id="instructors">
        <h2 className="text-xl font-semibold">Instructors</h2>
        {/* The form beside the list on wide screens, so nothing is a long scroll away. */}
        <div className="mt-4 grid items-start gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <form
          ref={instructorFormRef}
          onSubmit={handleSaveInstructor}
          className={`scroll-mt-4 rounded-md border p-4 ${
            editingInstructor ? "border-blue-200 bg-blue-50" : "border-gray-200 bg-gray-50"
          }`}
          data-testid="instructor-form"
        >
          <h3 className="mb-3 text-base font-semibold">
            {editingInstructor ? `Edit instructor: ${editingInstructor.full_name}` : "Add an instructor"}
          </h3>

          <label className="block text-sm font-semibold" htmlFor="instructor_name">
            Full name
          </label>
          <input
            id="instructor_name"
            required
            value={instructorName}
            onChange={(e) => setInstructorName(e.target.value)}
            placeholder="Dr. Smith"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold" htmlFor="instructor_email">
            Email
          </label>
          <input
            id="instructor_email"
            type="email"
            required
            value={instructorEmail}
            onChange={(e) => setInstructorEmail(e.target.value)}
            placeholder="dr.smith@example.com"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold" htmlFor="instructor_password">
            {editingInstructor ? "New password" : "Initial password"}
            {editingInstructor && (
              <span className="font-normal text-gray-500"> (leave blank to keep the current one)</span>
            )}
          </label>
          <input
            id="instructor_password"
            required={!editingInstructor}
            minLength={editingInstructor ? 4 : undefined}
            value={instructorPassword}
            autoComplete="new-password"
            onChange={(e) => setInstructorPassword(e.target.value)}
            placeholder={editingInstructor ? "" : "Shown once -- share it with them directly"}
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold" htmlFor="instructor-subjects">
            Subjects <span className="font-normal text-gray-500">(search and pick several)</span>
          </label>
          <div className="mb-3">
            <MultiSelect
              id="instructor-subjects"
              options={subjects.map((s) => ({ id: s.id, label: subjectLabel(s) }))}
              selected={instructorSubjects}
              onChange={setInstructorSubjects}
              placeholder="Search subjects..."
              emptyText="No subjects yet. Add one in the Subjects tab."
              testId="instructor-subjects-input"
            />
          </div>
          <div className="flex gap-2">
             <button className="btn-primary rounded-md px-4 py-2 text-sm font-semibold">

              {editingInstructor ? "Save changes" : "Create instructor"}
            </button>
            {editingInstructor && (
              <button
                type="button"
                onClick={clearInstructorForm}
                className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
              >
                Cancel
              </button>
            )}
          </div>
          <Message state={instructorMsg} />
        </form>

        <div className="min-w-0">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Existing instructors</h3>
        <ManageUsersTable
          role="instructor"
          users={instructors}
          onChanged={loadInstructors}
          onEdit={startEditInstructor}
          highlightId={editingInstructor?.id ?? null}
        />
        </div>
        </div>

      </section>
      </div>

      {/* Students */}
      <div {...adminPanelProps("students", tab)}>
            <section className="mt-6 card scroll-mt-4" id="students">
        <h2 className="text-xl font-semibold">Students</h2>
        {/* The form beside the list on wide screens, so nothing is a long scroll away. */}
        <div className="mt-4 grid items-start gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <form
          ref={studentFormRef}
          onSubmit={handleSaveStudent}
          className={`scroll-mt-4 rounded-md border p-4 ${
            editingStudent ? "border-blue-200 bg-blue-50" : "border-gray-200 bg-gray-50"
          }`}
          data-testid="student-form"
        >
          <h3 className="mb-3 text-base font-semibold">
            {editingStudent ? `Edit student: ${editingStudent.full_name}` : "Add a student"}
          </h3>

          <label className="block text-sm font-semibold" htmlFor="student_name">
            Full name
          </label>
          <input
            id="student_name"
            required
            value={studentName}
            onChange={(e) => setStudentName(e.target.value)}
            placeholder="Ada Lovelace"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold" htmlFor="student_email">
            Email
          </label>
          <input
            id="student_email"
            type="email"
            required
            value={studentEmail}
            onChange={(e) => setStudentEmail(e.target.value)}
            placeholder="ada@example.com"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <div className="mb-3">
            <StudentIdFields
              idPrefix="new-student"
              batch={studentBatch}
              onBatchChange={setStudentBatch}
              own={studentOwnNumber}
              onOwnChange={setStudentOwnNumber}
              batches={batches}
            />
          </div>
          <label className="block text-sm font-semibold" htmlFor="student_password">
            {editingStudent ? "New password" : "Initial password"}
            {editingStudent && <span className="font-normal text-gray-500"> (leave blank to keep the current one)</span>}
          </label>
          <input
            id="student_password"
            required={!editingStudent}
            minLength={editingStudent ? 4 : undefined}
            value={studentPassword}
            autoComplete="new-password"
            onChange={(e) => setStudentPassword(e.target.value)}
            placeholder={editingStudent ? "" : "Shown once -- share it with them directly"}
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <p className="mb-3 text-sm text-gray-600">
            No subjects here: the student joins a subject themselves, with the password its instructor sets.
          </p>
          <div className="flex gap-2">
          <button className="btn-primary rounded-md px-4 py-2 text-sm font-semibold">

              {editingStudent ? "Save changes" : "Create student"}
            </button>
            {editingStudent && (
              <button
                type="button"
                onClick={clearStudentForm}
                className="rounded-md bg-gray-600 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-700"
              >
                Cancel
              </button>
            )}
          </div>
          <Message state={studentMsg} />
        </form>

               <div className="min-w-0">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Existing students</h3>
        <ManageUsersTable
          role="student"
          users={students}
          onChanged={loadStudents}
          onEdit={startEditStudent}
          highlightId={editingStudent?.id ?? null}
        />
        </div>
        </div>

      </section>
      </div>
         </main>
    </>

  );
}
