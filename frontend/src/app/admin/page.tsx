"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, Subject, UserInfo } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import Message, { MessageState } from "@/components/Message";
import AdminTabs, { adminPanelProps, AdminTab, isAdminTab } from "@/components/admin/AdminTabs";
import ManageSubjectsTable from "@/components/admin/ManageSubjectsTable";
import StudentIdFields, { BatchCombobox } from "@/components/admin/StudentIdFields";
import { batchList, ownNumberOf, registerNumberFor } from "@/lib/registerNumber";
import ManageUsersTable, { SubjectCheckboxes } from "@/components/admin/ManageUsersTable";
import PageLoading from "@/components/PageLoading";

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
  const [subjectMsg, setSubjectMsg] = useState<MessageState>(null);

  const [instructorName, setInstructorName] = useState("");
  const [instructorEmail, setInstructorEmail] = useState("");
  const [instructorPassword, setInstructorPassword] = useState("");
  const [instructorSubjects, setInstructorSubjects] = useState<Set<number>>(new Set());
  const [instructorMsg, setInstructorMsg] = useState<MessageState>(null);

  const [studentName, setStudentName] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [studentPassword, setStudentPassword] = useState("");
  const [studentBatch, setStudentBatch] = useState("");
  const [studentOwnNumber, setStudentOwnNumber] = useState(""); // the last part of TST/<batch>/<number>
  const [studentSubjects, setStudentSubjects] = useState<Set<number>>(new Set());
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

  async function handleAddSubject(e: FormEvent) {
    e.preventDefault();
    setSubjectMsg(null);
    try {
      await apiFetch("/admin/subjects", {
        method: "POST",
        json: { name: subjectName, code: subjectCode, batch: subjectBatch },
      });
      setSubjectMsg({ text: "Subject added.", kind: "success" });
      setSubjectName("");
      setSubjectCode("");
      setSubjectBatch("");
      await loadSubjects();
    } catch (err) {
      setSubjectMsg({ text: `Failed to add subject: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }

  async function handleCreateInstructor(e: FormEvent) {
    e.preventDefault();
    setInstructorMsg(null);
    try {
      await apiFetch("/admin/instructors", {
        method: "POST",
        json: {
          full_name: instructorName,
          email: instructorEmail,
          password: instructorPassword,
          subject_ids: Array.from(instructorSubjects),
        },
      });
      setInstructorMsg({ text: "Instructor created.", kind: "success" });
      setInstructorName("");
      setInstructorEmail("");
      setInstructorPassword("");
      setInstructorSubjects(new Set());
      await loadInstructors();
    } catch (err) {
      setInstructorMsg({
        text: `Failed to create instructor: ${err instanceof Error ? err.message : err}`,
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
    setStudentSubjects(new Set());
  }

  /** Edit in the students list: the form takes the student's details and comes into view. */
  function startEditStudent(s: UserInfo) {
    setEditingStudent(s);
    setStudentName(s.full_name);
    setStudentEmail(s.email);
    setStudentPassword("");
    setStudentBatch(s.batch ?? "");
    setStudentOwnNumber(ownNumberOf(s.register_number ?? "", s.batch ?? ""));
    setStudentSubjects(new Set(s.subjects.map((x) => x.id)));
    setStudentMsg(null);
    studentFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    studentFormRef.current?.querySelector("input")?.focus({ preventScroll: true });
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
        subject_ids: Array.from(studentSubjects),
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

  function toggleSet(set: Set<number>, id: number, setter: (s: Set<number>) => void) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
  }

  if (!ready || !user) return <PageLoading />;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Admin dashboard</h1>
      <p className="mt-1 text-sm text-gray-600">
        Create subjects, then create instructor and student accounts and assign them to subjects. You can edit
        subjects, instructors and students at any time. Everyone logs in with the credentials you set here --
        there&apos;s no self-signup.
      </p>

      <AdminTabs
        tab={tab}
        onChange={changeTab}
        counts={{ subjects: subjects.length, instructors: instructors.length, students: students.length }}
      />

      {/* Subjects */}
      <div {...adminPanelProps("subjects", tab)}>
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold">Subjects</h2>
        <form onSubmit={handleAddSubject} className="mt-3">
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
          <button className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
            Add subject
          </button>
          <Message state={subjectMsg} />
        </form>

        <h3 className="mt-5 text-sm font-bold uppercase tracking-wide text-gray-500">Existing subjects</h3>
        <ManageSubjectsTable subjects={subjects} batches={batches} onChanged={loadSubjects} />
      </section>
      </div>

      {/* Instructors */}
      <div {...adminPanelProps("instructors", tab)}>
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold">Instructors</h2>
        <form onSubmit={handleCreateInstructor} className="mt-3">
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
            Initial password
          </label>
          <input
            id="instructor_password"
            required
            value={instructorPassword}
            onChange={(e) => setInstructorPassword(e.target.value)}
            placeholder="Shown once -- share it with them directly"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-semibold">Subjects</label>
          <div className="mt-1 mb-3">
            <SubjectCheckboxes
              id="instructor-subjects"
              subjects={subjects}
              checked={instructorSubjects}
              onToggle={(id) => toggleSet(instructorSubjects, id, setInstructorSubjects)}
            />
          </div>
          <button className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
            Create instructor
          </button>
          <Message state={instructorMsg} />
        </form>

        <h3 className="mt-5 text-sm font-bold uppercase tracking-wide text-gray-500">Existing instructors</h3>
        <ManageUsersTable role="instructor" users={instructors} subjects={subjects} onChanged={loadInstructors} />
      </section>
      </div>

      {/* Students */}
      <div {...adminPanelProps("students", tab)}>
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold">Students</h2>
        <form
          ref={studentFormRef}
          onSubmit={handleSaveStudent}
          className={`mt-3 scroll-mt-4 ${editingStudent ? "rounded-md border border-blue-200 bg-blue-50 p-4" : ""}`}
          data-testid="student-form"
        >
          <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-gray-500">
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
          <label className="block text-sm font-semibold">Subjects</label>
          <div className="mt-1 mb-3">
            <SubjectCheckboxes
              id="student-subjects"
              subjects={subjects}
              checked={studentSubjects}
              onToggle={(id) => toggleSet(studentSubjects, id, setStudentSubjects)}
            />
          </div>
          <div className="flex gap-2">
            <button className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
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

        <h3 className="mt-5 text-sm font-bold uppercase tracking-wide text-gray-500">Existing students</h3>
        <ManageUsersTable
          role="student"
          users={students}
          subjects={subjects}
          onChanged={loadStudents}
          onEdit={startEditStudent}
          highlightId={editingStudent?.id ?? null}
        />
      </section>
      </div>
    </div>
  );
}
