"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, Submission } from "@/lib/api";
import { useRequireRole } from "@/lib/useRequireRole";
import AccountBar from "@/components/AccountBar";
import Message, { MessageState } from "@/components/Message";

export default function StudentPage() {
  const { user, ready } = useRequireRole("student");

  const [subjectId, setSubjectId] = useState<string>("");
  const [assignmentName, setAssignmentName] = useState("");
  const codeRef = useRef<HTMLInputElement>(null);
  const reportRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLInputElement>(null);

  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [message, setMessage] = useState<MessageState>(null);
  const [submitting, setSubmitting] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const loadSubmissions = useCallback(async () => {
    setSubmissions(await apiFetch<Submission[]>("/submissions"));
  }, []);

  useEffect(() => {
    if (!ready || !user) return;
    if (user.subjects.length && !subjectId) setSubjectId(String(user.subjects[0].id));
    loadSubmissions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, user, loadSubmissions]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    setSubmitting(true);

    const formData = new FormData();
    formData.append("subject_id", subjectId);
    formData.append("assignment_name", assignmentName);
    if (codeRef.current?.files?.[0]) formData.append("code", codeRef.current.files[0]);
    if (reportRef.current?.files?.[0]) formData.append("report", reportRef.current.files[0]);
    if (videoRef.current?.files?.[0]) formData.append("video", videoRef.current.files[0]);

    try {
      const submission = await apiFetch<Submission>("/submissions", { method: "POST", body: formData });
      setMessage({ text: `Submitted! Your submission id is ${submission.id}.`, kind: "success" });
      setAssignmentName("");
      formRef.current?.reset();
      await loadSubmissions();
    } catch (err) {
      setMessage({ text: `Submission failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  if (!ready || !user) return null;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <AccountBar user={user} />

      <h1 className="text-2xl font-bold">Student portal</h1>
      <p className="mt-1 text-sm text-gray-600">
        Upload your code, report, and presentation video for one of your subjects. Any of the three can be added
        later by re-submitting.
      </p>

      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <form ref={formRef} onSubmit={handleSubmit}>
          <label className="block text-sm font-semibold" htmlFor="subject_id">
            Subject
          </label>
          {user.subjects.length === 0 ? (
            <p className="mt-1 mb-3 text-sm text-red-700">No subjects assigned yet -- ask your admin</p>
          ) : (
            <select
              id="subject_id"
              required
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
              className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              {user.subjects.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.code})
                </option>
              ))}
            </select>
          )}

          <label className="block text-sm font-semibold" htmlFor="assignment_name">
            Assignment name
          </label>
          <input
            id="assignment_name"
            required
            value={assignmentName}
            onChange={(e) => setAssignmentName(e.target.value)}
            placeholder="e.g. Assignment 2 - Sorting Algorithms"
            className="mt-1 mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />

          <label className="block text-sm font-semibold" htmlFor="code">
            Code (zip or single file)
          </label>
          <input id="code" type="file" ref={codeRef} className="mt-1 mb-3 block w-full text-sm" />

          <label className="block text-sm font-semibold" htmlFor="report">
            Report (PDF or DOCX)
          </label>
          <input id="report" type="file" ref={reportRef} className="mt-1 mb-3 block w-full text-sm" />

          <label className="block text-sm font-semibold" htmlFor="video">
            Presentation video
          </label>
          <input id="video" type="file" ref={videoRef} className="mt-1 mb-3 block w-full text-sm" />

          <button
            type="submit"
            disabled={submitting || user.subjects.length === 0}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {submitting ? "Submitting..." : "Submit assignment"}
          </button>
          <Message state={message} />
        </form>
      </section>

      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold">My submissions</h2>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className="border border-gray-200 px-3 py-1.5">Subject</th>
              <th className="border border-gray-200 px-3 py-1.5">Assignment</th>
              <th className="border border-gray-200 px-3 py-1.5">Submitted</th>
              <th className="border border-gray-200 px-3 py-1.5">Status</th>
            </tr>
          </thead>
          <tbody>
            {submissions.map((s) => (
              <tr key={s.id}>
                <td className="border border-gray-200 px-3 py-1.5">{s.subject_name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{s.assignment_name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{new Date(s.submitted_at).toLocaleString()}</td>
                <td className="border border-gray-200 px-3 py-1.5">
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      s.status === "graded" ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"
                    }`}
                  >
                    {s.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
