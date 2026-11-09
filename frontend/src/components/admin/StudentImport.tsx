"use client";

import { ChangeEvent, useEffect, useState } from "react";
import { apiFetch, apiFetchBlob, StudentImportPreview, StudentImportResult, StudentImportRow, Subject, subjectLabel } from "@/lib/api";
import ConfirmDialog, { ConfirmRequest } from "@/components/ConfirmDialog";
import Message, { MessageState } from "@/components/Message";
import MultiSelect from "@/components/admin/MultiSelect";

function saveFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function RowsTable({ rows }: { rows: StudentImportRow[] }) {
  return (
    <div className="mt-3 max-h-96 overflow-auto rounded-md border border-gray-200">
      <table className="w-full min-w-[48rem] text-left text-sm">
        <thead className="sticky top-0 bg-gray-100 text-xs uppercase tracking-wide text-gray-600">
          <tr>
            <th scope="col" className="px-3 py-2">Row</th>
            {/* Beside the row number: on a phone the columns after it are off-screen until scrolled to. */}
            <th scope="col" className="px-3 py-2">Result</th>
            <th scope="col" className="px-3 py-2">Full name</th>
            <th scope="col" className="px-3 py-2">Email</th>
            <th scope="col" className="px-3 py-2">Batch</th>
            <th scope="col" className="px-3 py-2">Register number</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row} className={`border-t border-gray-200 ${r.problems.length ? "bg-red-50" : ""}`} data-testid="import-row">
              <td className="px-3 py-2 align-top">{r.row}</td>
              <td className="min-w-52 px-3 py-2 align-top [overflow-wrap:anywhere]">
                {r.problems.length ? (
                  <ul className="font-semibold text-red-700">
                    {r.problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-green-800">Ready</span>
                )}
              </td>
              <td className="break-words px-3 py-2 align-top">{r.full_name || "-"}</td>
              <td className="break-all px-3 py-2 align-top">{r.email || "-"}</td>
              <td className="px-3 py-2 align-top">{r.batch || "-"}</td>
              <td className="break-all px-3 py-2 align-top">{r.register_number || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Create many students from a spreadsheet: download the template, upload it, check the preview, confirm, download the
 * list of first passwords. The server keeps nothing between the steps, and the passwords exist only in this component's
 * memory until the admin finishes, so the page warns before they could be lost.
 */
export default function StudentImport({ subjects, onCreated }: { subjects: Subject[]; onCreated: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<StudentImportPreview | null>(null);
  const [subjectIds, setSubjectIds] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<StudentImportResult | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<MessageState>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const passwordsAtRisk = !!result?.passwords_file && !downloaded;

  useEffect(() => {
    if (!passwordsAtRisk) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    // beforeunload covers closing and reloading. Log out and the app's own links change page without unloading it, so
    // they are asked here, before their own click handlers run. (A download link is not leaving.)
    const guardLinks = (e: MouseEvent) => {
      const target = e.target instanceof Element ? e.target.closest("a[href]:not([download]), header button") : null;
      if (target && !window.confirm("The password list has not been downloaded and can't be shown again. Leave anyway?")) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", guardLinks, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", guardLinks, true);
    };
  }, [passwordsAtRisk]);

  function startOver() {
    setFile(null);
    setPreview(null);
    setSubjectIds(new Set());
    setResult(null); // the passwords are gone from here on
    setDownloaded(false);
    setMsg(null);
    setConfirm(null);
  }

  async function downloadTemplate() {
    setMsg(null);
    try {
      saveFile(await apiFetchBlob("/admin/students/import-template"), "student-import-template.xlsx");
    } catch (err) {
      setMsg({ text: `Could not download the template: ${err instanceof Error ? err.message : err}`, kind: "error" });
    }
  }

  async function chooseFile(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0];
    e.target.value = ""; // so the same file, corrected, can be chosen again
    if (!picked) return;
    setMsg(null);
    setPreview(null);
    setBusy(true);
    try {
      // A copy in memory: what is created is exactly what was checked, even if the file on disk changes meanwhile.
      const copy = new File([await picked.arrayBuffer()], picked.name, { type: picked.type });
      const form = new FormData();
      form.append("file", copy);
      setPreview(await apiFetch<StudentImportPreview>("/admin/students/import/preview", { method: "POST", body: form }));
      setFile(copy);
    } catch (err) {
      setFile(null);
      setMsg({ text: err instanceof Error ? err.message : String(err), kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function createStudents() {
    if (!file) return;
    setMsg(null);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("subject_ids", Array.from(subjectIds).join(","));
      const done = await apiFetch<StudentImportResult>("/admin/students/import", { method: "POST", body: form });
      setResult(done);
      setPreview(null);
      setFile(null);
      await onCreated();
    } catch (err) {
      setMsg({ text: `Import failed: ${err instanceof Error ? err.message : err}`, kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  function downloadPasswords() {
    if (!result?.passwords_file) return;
    const bytes = Uint8Array.from(atob(result.passwords_file), (c) => c.charCodeAt(0));
    const type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    saveFile(new Blob([bytes], { type }), `student-passwords_${new Date().toISOString().slice(0, 10)}.xlsx`);
    setDownloaded(true);
  }

  function finish() {
    if (!passwordsAtRisk) return startOver();
    setConfirm({
      title: "Leave without the password list?",
      message:
        "The passwords of the new students are not saved anywhere and can't be shown again. Without them you would have to set a new password for each student by hand.",
      confirmLabel: "Leave without it",
      onConfirm: startOver,
    });
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-expanded={false}
        className="btn-secondary mt-3 rounded-md px-4 py-2 text-sm font-semibold"
        data-testid="student-import-open"
      >
        Import students from a spreadsheet
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-4" data-testid="student-import">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold">Import students from a spreadsheet</h3>
        {!result && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              startOver();
              setOpen(false);
            }}
            className="text-sm font-semibold text-blue-700 hover:underline disabled:opacity-60"
          >
            Close
          </button>
        )}
      </div>

      {!result && (
        <>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-gray-700">
            <li>
              <button
                type="button"
                onClick={downloadTemplate}
                className="font-semibold text-blue-700 underline-offset-2 hover:underline"
                data-testid="student-import-template"
              >
                Download the template
              </button>{" "}
              and put one student on each row. An Excel (.xlsx) or CSV file from your records also works.
            </li>
            <li>Choose the file. Nothing is created until you have checked it here.</li>
            <li>Each student gets a random first password, and must choose their own at first login.</li>
          </ol>
          <label className="mt-3 block text-sm font-semibold" htmlFor="student-import-file">
            {preview ? "Choose a different file" : "Class list"}
          </label>
          <input
            id="student-import-file"
            type="file"
            accept=".xlsx,.csv"
            disabled={busy}
            onChange={chooseFile}
            className="mt-1 block w-full cursor-pointer rounded-md border border-gray-300 bg-white text-sm text-gray-700 file:mr-3 file:cursor-pointer file:border-0 file:border-r file:border-solid file:border-gray-300 file:bg-gray-100 file:px-4 file:py-2.5 file:text-sm file:font-semibold file:text-blue-700 hover:border-gray-400 hover:file:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-60"
            data-testid="student-import-file"
          />
        </>
      )}

      {preview && file && (
        <div className="mt-4" data-testid="student-import-preview">
          <p className="text-sm" data-testid="student-import-counts">
            <span className="font-semibold">{file.name}:</span>{" "}
            <span className="font-semibold text-green-800">{preview.ready} ready to create</span>
            {preview.with_problems > 0 && (
              <>
                {" · "}
                <span className="font-semibold text-red-700">
                  {preview.with_problems} with {preview.with_problems === 1 ? "a problem" : "problems"}
                </span>
              </>
            )}
          </p>
          {preview.with_problems > 0 && (
            <p className="mt-1 text-sm text-gray-700">
              Rows with a problem are left out. Correct them in your file and choose it again, or create the others now
              and import the rest later.
            </p>
          )}
          {/* Problems first: in a long list they are what the admin is looking for. */}
          <RowsTable rows={[...preview.rows].sort((a, b) => Number(b.problems.length > 0) - Number(a.problems.length > 0) || a.row - b.row)} />
          <label className="mt-4 block text-sm font-semibold" htmlFor="student-import-subjects">
            Subjects <span className="font-normal text-gray-500">(optional: every new student joins these)</span>
          </label>
          <MultiSelect
            id="student-import-subjects"
            options={subjects.map((s) => ({ id: s.id, label: subjectLabel(s) }))}
            selected={subjectIds}
            onChange={setSubjectIds}
            placeholder="Search subjects..."
            emptyText="No subjects yet. Add one in the Subjects tab."
            testId="student-import-subjects-input"
          />
          <button
            type="button"
            disabled={busy || preview.ready === 0}
            onClick={createStudents}
            className="btn-primary mt-3 rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-60"
            data-testid="student-import-create"
          >
            {busy ? "Creating, this can take a minute..." : `Create ${preview.ready} ${preview.ready === 1 ? "student" : "students"}`}
          </button>
        </div>
      )}

      {result && (
        <div className="mt-3" data-testid="student-import-result">
          <p className="text-sm font-semibold text-green-800" data-testid="student-import-created">
            {result.created.length} {result.created.length === 1 ? "student" : "students"} created.
          </p>
          {result.passwords_file ? (
            <div className="mt-2 rounded-md border border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-semibold">Download the password list now.</p>
              <p className="mt-1">
                It can&apos;t be shown again once you leave this page: the passwords are not saved anywhere. Give each
                student only their own line, in private, and delete the file once they have them.
              </p>
              <button
                type="button"
                onClick={downloadPasswords}
                className="btn-primary mt-2 rounded-md px-4 py-2 text-sm font-semibold"
                data-testid="student-import-passwords"
              >
                {downloaded ? "Download the password list again" : "Download the password list"}
              </button>
            </div>
          ) : (
            <p className="mt-2 text-sm text-gray-700">No students were created, so there is no password list.</p>
          )}
          {result.skipped.length > 0 && (
            <>
              <p className="mt-3 text-sm font-semibold text-red-700">
                {result.skipped.length} {result.skipped.length === 1 ? "row was" : "rows were"} left out:
              </p>
              <RowsTable rows={result.skipped} />
            </>
          )}
          <button
            type="button"
            onClick={finish}
            className="btn-secondary mt-3 rounded-md px-4 py-2 text-sm font-semibold"
            data-testid="student-import-finish"
          >
            Finish
          </button>
        </div>
      )}

      <Message state={msg} />
      <ConfirmDialog request={confirm} onCancel={() => setConfirm(null)} />
    </div>
  );
}
