"use client";

import { useState } from "react";
import { apiFetch, CodeSubmit, MySubmission, StudentAssignment } from "@/lib/api";
import Message, { MessageState } from "@/components/Message";
import { CodeRunResults, MarkBox } from "@/components/student/CodeEditorForm";

/**
 * A submitted code challenge that has no mark yet: the test cases could not be run when the code was
 * handed in (Docker was off, the server was busy), or it was submitted before code was marked at once.
 * The student asks for the mark here. The server runs the tests on the saved code, which cannot have
 * changed, so it is the mark Submit would have given. The result stays on screen after the card is
 * refreshed, which is why this is shown for every challenge submission and not only while unmarked.
 */
export default function MarkMyCode({
  assignment,
  submission,
  onMarked,
}: {
  assignment: StudentAssignment;
  submission: MySubmission;
  /** Reloads the card, so its Status and Marks rows show the new mark. */
  onMarked: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);
  const [result, setResult] = useState<CodeSubmit | null>(null);

  async function getMarks() {
    setBusy(true);
    setMsg(null);
    try {
      const marked = await apiFetch<CodeSubmit>(`/assignments/${assignment.id}/mark-my-code`, { method: "POST" });
      if (marked.marked) {
        setResult(marked);
        onMarked().catch(() => {});
      } else {
        setMsg({ text: "The test cases could not be run just now. Please try again in a moment.", kind: "error" });
      }
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <div className="mt-3" data-testid="mark-my-code-result">
        {result.run && <CodeRunResults run={result.run} submitted />}
        <MarkBox result={result} releaseAt={assignment.marks_release_at} />
      </div>
    );
  }
  if (submission.final_mark !== null) return null; // already marked

  return (
    <div className="mt-3 rounded-md border border-yellow-200 bg-yellow-50 p-3" data-testid="mark-my-code">
      <p className="text-sm text-yellow-900">Your code is submitted, but it has no mark yet.</p>
      <button
        type="button"
        onClick={getMarks}
        disabled={busy}
        className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {busy ? "Getting your marks…" : "Get my marks"}
      </button>
      {busy && (
        <p className="mt-2 text-xs text-gray-600">Running every test case in a safe sandbox: a few seconds each.</p>
      )}
      <Message state={msg} />
    </div>
  );
}
