"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch, Subject, UserInfo } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import Message, { MessageState } from "@/components/Message";

function SubjectCheckboxes({
  id,
  subjects,
  checked,
  onToggle,
}: {
  id: string;
  subjects: Subject[];
  checked: Set<number>;
  onToggle: (id: number) => void;
}) {
  if (subjects.length === 0) {
    return <p className="text-sm text-gray-500">Add a subject above first.</p>;
  }
  return (
    <div id={id} className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-300 px-3 py-2">
      {subjects.map((s) => (
        <label key={s.id} className="flex items-center gap-2 text-sm font-normal">
          <input
            type="checkbox"
            checked={checked.has(s.id)}
            onChange={() => onToggle(s.id)}
            className="h-4 w-4"
          />
          {s.name} ({s.code})
        </label>
      ))}
    </div>
  );
}

function subjectNames(subjects: Subject[]): string {
  return subjects.length ? subjects.map((s) => s.name).join(", ") : "(none)";
}

export default function AdminPage() {
  const { user, ready } = useRequireRole("admin");

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [instructors, setInstructors] = useState<UserInfo[]>([]);
  const [students, setStudents] = useState<UserInfo[]>([]);

  const [subjectName, setSubjectName] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [subjectMsg, setSubjectMsg] = useState<MessageState>(null);

  const [instructorName, setInstructorName] = useState("");
  const [instructorEmail, setInstructorEmail] = useState("");
  const [instructorPassword, setInstructorPassword] = useState("");
  const [instructorSubjects, setInstructorSubjects] = useState<Set<number>>(new Set());
  const [instructorMsg, setInstructorMsg] = useState<MessageState>(null);

  const [studentName, setStudentName] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [studentPassword, setStudentPassword] = useState("");
  const [studentSubjects, setStudentSubjects] = useState<Set<number>>(new Set());
  const [studentMsg, setStudentMsg] = useState<MessageState>(null);

  const loadSubjects = useCallback(async () => {
    setSubjects(await apiFetch<Subject[]>("/admin/subjects"));
  }, []);
  const loadInstructors = useCallback(async () => {
    setInstructors(await apiFetch<UserInfo[]>("/admin/instructors"));
  }, []);
  const loadStudents = useCallback(async () => {
    setStudents(await apiFetch<UserInfo[]>("/admin/students"));
  }, []);

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
      await apiFetch("/admin/subjects", { method: "POST", json: { name: subjectName, code: subjectCode } });
      setSubjectMsg({ text: "Subject added.", kind: "success" });
      setSubjectName("");
      setSubjectCode("");
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

  async function handleCreateStudent(e: FormEvent) {
    e.preventDefault();
    setStudentMsg(null);
    try {
      await apiFetch("/admin/students", {
        method: "POST",
        json: {
          full_name: studentName,
          email: studentEmail,
          password: studentPassword,
          subject_ids: Array.from(studentSubjects),
        },
      });
      setStudentMsg({ text: "Student created.", kind: "success" });
      setStudentName("");
      setStudentEmail("");
      setStudentPassword("");
      setStudentSubjects(new Set());
      await loadStudents();
    } catch (err) {
      setStudentMsg({ text: `Failed to create student: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }

  function toggleSet(set: Set<number>, id: number, setter: (s: Set<number>) => void) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
  }

  if (!ready || !user) return null;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Admin dashboard</h1>
      <p className="mt-1 text-sm text-gray-600">
        Create subjects, then create instructor and student accounts and assign them to subjects. Everyone logs
        in with the credentials you set here -- there&apos;s no self-signup.
      </p>

      {/* Subjects */}
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
          <button className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
            Add subject
          </button>
          <Message state={subjectMsg} />
        </form>

        <h3 className="mt-5 text-sm font-bold uppercase tracking-wide text-gray-500">Existing subjects</h3>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className="border border-gray-200 px-3 py-1.5">Name</th>
              <th className="border border-gray-200 px-3 py-1.5">Code</th>
            </tr>
          </thead>
          <tbody>
            {subjects.map((s) => (
              <tr key={s.id}>
                <td className="border border-gray-200 px-3 py-1.5">{s.name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{s.code}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Instructors */}
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
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className="border border-gray-200 px-3 py-1.5">Name</th>
              <th className="border border-gray-200 px-3 py-1.5">Email</th>
              <th className="border border-gray-200 px-3 py-1.5">Subjects</th>
            </tr>
          </thead>
          <tbody>
            {instructors.map((i) => (
              <tr key={i.id}>
                <td className="border border-gray-200 px-3 py-1.5">{i.full_name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{i.email}</td>
                <td className="border border-gray-200 px-3 py-1.5">{subjectNames(i.subjects)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Students */}
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold">Students</h2>
        <form onSubmit={handleCreateStudent} className="mt-3">
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
          <label className="block text-sm font-semibold" htmlFor="student_password">
            Initial password
          </label>
          <input
            id="student_password"
            required
            value={studentPassword}
            onChange={(e) => setStudentPassword(e.target.value)}
            placeholder="Shown once -- share it with them directly"
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
          <button className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
            Create student
          </button>
          <Message state={studentMsg} />
        </form>

        <h3 className="mt-5 text-sm font-bold uppercase tracking-wide text-gray-500">Existing students</h3>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className="border border-gray-200 px-3 py-1.5">Name</th>
              <th className="border border-gray-200 px-3 py-1.5">Email</th>
              <th className="border border-gray-200 px-3 py-1.5">Subjects</th>
            </tr>
          </thead>
          <tbody>
            {students.map((s) => (
              <tr key={s.id}>
                <td className="border border-gray-200 px-3 py-1.5">{s.full_name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{s.email}</td>
                <td className="border border-gray-200 px-3 py-1.5">{subjectNames(s.subjects)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
