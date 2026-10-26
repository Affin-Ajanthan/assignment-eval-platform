import { Submission } from "@/lib/api";
import { formatDateTime, formatMark } from "@/lib/datetime";
import Badge from "@/components/Badge";

/** Every submission the student has made, across subjects. */
export default function SubmissionHistory({ submissions }: { submissions: Submission[] }) {
  return (
    <section className="mt-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold">My submissions</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left">
              <th className="border border-gray-200 px-3 py-1.5">Subject</th>
              <th className="border border-gray-200 px-3 py-1.5">Assignment</th>
              <th className="border border-gray-200 px-3 py-1.5">Submitted</th>
              <th className="border border-gray-200 px-3 py-1.5">Status</th>
              <th className="border border-gray-200 px-3 py-1.5">Marks</th>
            </tr>
          </thead>
          <tbody>
            {submissions.map((s) => (
              <tr key={s.id}>
                <td className="border border-gray-200 px-3 py-1.5">{s.subject_name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{s.assignment_name}</td>
                <td className="border border-gray-200 px-3 py-1.5">{formatDateTime(s.submitted_at)}</td>
                <td className="border border-gray-200 px-3 py-1.5">
                  <Badge bold={false} tone={s.status === "graded" ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"}>
                    {s.status === "graded" ? "Graded" : "Submitted"}
                  </Badge>
                </td>
                <td className="border border-gray-200 px-3 py-1.5">{formatMark(s.final_mark, s.max_mark)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
