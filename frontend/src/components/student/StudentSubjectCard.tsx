import Link from "next/link";
import { StudentSubject } from "@/lib/api";

/** One subject as a box. It opens the subject's page: its assignments if the student joined it, the password box if not. */
export default function StudentSubjectCard({ subject: s }: { subject: StudentSubject }) {
  return (
    <Link
      href={`/student/subjects/${s.id}`}
      className={`block h-full rounded-lg border p-4 shadow-sm hover:border-blue-500 hover:bg-blue-50 sm:p-5 ${
        s.joined ? "border-gray-200 bg-white" : "border-gray-200 bg-gray-50"
      }`}
      data-testid={s.joined ? "subject-card" : "locked-subject"}
    >
      <span className="block break-words text-lg font-bold">{s.name}</span>
      <span className="block break-words text-xs text-gray-500">
        {s.code}
        {s.batch ? ` · Batch ${s.batch}` : ""}
      </span>
      {s.teachers.length > 0 && (
        <span className="mt-1 block text-xs text-gray-500">{s.teachers.map((t) => t.name).join(", ")}</span>
      )}
      {s.joined ? (
        <span className="mt-2 inline-block rounded bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-800">
          Joined · open
        </span>
      ) : (
        <span className="mt-2 inline-block rounded bg-gray-200 px-2 py-0.5 text-xs font-semibold text-gray-700">
          {s.registration_open ? "Not joined · enter the password" : "Not joined · registration not open yet"}
        </span>
      )}
    </Link>
  );
}
