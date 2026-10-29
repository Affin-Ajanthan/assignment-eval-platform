"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, Assignment, AssignmentStatus, SubmissionType } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { takeFlash } from "@/lib/flash";
import Message, { MessageState } from "@/components/Message";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import ReportTemplateControl from "@/components/instructor/ReportTemplateControl";
import Badge from "@/components/Badge";
import RichText from "@/components/RichText";
import { KIND_OPTIONS } from "@/components/instructor/AssignmentForm";
import { languageNames } from "@/lib/codeLanguages";

const STATUS_STYLE: Record<AssignmentStatus, { text: string; cls: string }> = {
  upcoming: { text: "Not yet open", cls: "bg-gray-100 text-gray-700" },
  open: { text: "Open", cls: "bg-green-50 text-green-800" },
  closed: { text: "Closed", cls: "bg-yellow-50 text-yellow-800" },
};

const TYPE_LABEL: Record<SubmissionType, string> = { code: "Code", report: "Report", video: "Video" };
const typeLabel = (t: SubmissionType) => TYPE_LABEL[t] ?? t;

/**
 * The assignments of the subject: the two kinds to start a new one (each opens the page where its details are
 * entered), and the existing ones, with Edit (the same page) and Delete.
 */
export default function AssignmentsSection({
  subjectId,
  assignments,
  onChanged,
}: {
  subjectId: number;
  assignments: Assignment[];
  onChanged: () => Promise<void>;
}) {
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // The page that saved an assignment sends the instructor back here with a message to show.
  useEffect(() => {
    const flash = takeFlash();
    if (flash) setMsg({ text: flash, kind: "success" });
  }, []);

  function askDelete(a: Assignment) {
    setConfirm({
      title: `Delete "${a.name}"?`,
      message:
        "Are you sure you want to delete this assignment? Students will no longer see it or be able to submit to it." +
        (a.submission_count
          ? `\n\nIts ${a.submission_count} existing submission(s) and any grades are kept as records under the name "${a.name}".`
          : ""),
      onConfirm: async () => {
        setConfirmBusy(true);
        try {
          await apiFetch(`/assignments/${a.id}`, { method: "DELETE" });
          setMsg({ text: `Assignment "${a.name}" deleted.`, kind: "success" });
          await onChanged();
        } catch (err) {
          setMsg({ text: `Failed to delete assignment: ${err instanceof Error ? err.message : err}`, kind: "error" });
        } finally {
          setConfirmBusy(false);
          setConfirm(null);
        }
      },
    });
  }

  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">Assignments</h2>
      <p className="mt-1 text-sm text-gray-600">
        Choose the kind of assignment to create: its details (name, instructions, dates and, for a code challenge, the
        tasks and test cases) are entered on the next page. Create rubrics below.
      </p>

      <div className="mt-3" data-testid="assignment-type-chooser">
        <h3 className="text-sm font-bold">Create assignment</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          {KIND_OPTIONS.map((o) => (
            <Link
              key={o.value}
              href={`/instructor/assignments/new?subject=${subjectId}&kind=${o.value}`}
              className="rounded-md border border-gray-300 p-4 text-left hover:border-blue-500 hover:bg-blue-50"
              data-testid={`create-${o.value}`}
            >
              <span className="block font-bold">{o.title}</span>
              <span className="mt-1 block text-sm text-gray-600">{o.text}</span>
            </Link>
          ))}
        </div>
      </div>
      <Message state={msg} />

      <h3 className="mt-6 text-sm font-bold uppercase tracking-wide text-gray-500">Assignments in this subject</h3>
      {assignments.length === 0 ? (
        <p className="mt-2 text-sm text-gray-600">No assignments yet.</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {assignments.map((a) => (
            <li key={a.id} className="rounded-md border border-gray-200 p-4" data-testid="assignment-card">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h4 className="font-bold">{a.name}</h4>
                  {a.assignment_type === "code_challenge" && (
                    <Badge tone="bg-purple-50 text-purple-800">Code challenge</Badge>
                  )}
                  <Badge tone={STATUS_STYLE[a.status].cls}>{STATUS_STYLE[a.status].text}</Badge>
                  <p className="mt-1 text-xs text-gray-600">Accepts: {a.submission_types.map(typeLabel).join(", ")}</p>
                  {a.submission_types.includes("code") && a.code_languages?.length > 0 && (
                    <p className="text-xs text-gray-600">Language: {languageNames(a.code_languages)}</p>
                  )}
                  <p className="text-xs text-gray-600">
                    Student self-checks: similarity {a.student_similarity_check ? "on" : "off"} · AI{" "}
                    {a.student_ai_check ? "on" : "off"}
                  </p>
                  {a.test_cases?.length > 0 && (
                    <p className="text-xs text-gray-600" data-testid="test-cases-summary">
                      {a.questions?.length > 1 && `Tasks: ${a.questions.length} · `}
                      Test cases: {a.test_cases.length} ({a.test_cases.filter((t) => t.visible).length} visible) ·{" "}
                      {a.test_cases.reduce((sum, t) => sum + t.points, 0)} points
                    </p>
                  )}
                  {a.submission_types.includes("code") && (
                    <p className="text-xs text-gray-600">
                      Code similarity: {a.ignore_common_code ? "ignores code most of the class shares" : "compares all code"}
                    </p>
                  )}
                  <p className="text-xs text-gray-600" data-testid="marks-release">
                    Marks for students:{" "}
                    {a.marks_released ? (
                      "visible"
                    ) : (
                      <span className="font-semibold text-yellow-800">
                        hidden until {formatDateTime(a.marks_release_at!)}
                      </span>
                    )}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Link
                    href={`/instructor/assignments/${a.id}`}
                    className="rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700"
                  >
                    Edit
                  </Link>
                  <button
                    type="button"
                    onClick={() => askDelete(a)}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700"
                  >
                    Delete
                  </button>
                </div>
              </div>
              {a.description && <RichText text={a.description} className="mt-2 text-sm text-gray-700" />}
              <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
                <dt className="font-semibold">Available from</dt>
                <dd>{formatDateTime(a.available_from)}</dd>
                <dt className="font-semibold">Deadline</dt>
                <dd>{formatDateTime(a.deadline)}</dd>
                <dt className="font-semibold">Rubric</dt>
                <dd>{a.rubric_name ? `${a.rubric_name} (${a.max_points} pts)` : "None selected"}</dd>
                <dt className="font-semibold">Starter code</dt>
                <dd>
                  {a.starter_code
                    ? `${a.starter_code_filename} (${a.starter_code.split("\n").length} lines, excluded from similarity)`
                    : "None"}
                </dd>
                <dt className="font-semibold">Report template (PDF)</dt>
                <dd>
                  <ReportTemplateControl assignment={a} onChanged={onChanged} />
                </dd>
                <dt className="font-semibold">Submissions</dt>
                <dd>
                  {a.submission_count} ({a.graded_count} graded)
                </dd>
              </dl>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog request={confirm} busy={confirmBusy} onCancel={() => !confirmBusy && setConfirm(null)} />
    </section>
  );
}
