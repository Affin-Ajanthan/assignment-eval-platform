import Link from "next/link";
import { Assignment } from "@/lib/api";
import { KIND_OPTIONS } from "@/components/instructor/AssignmentForm";

/**
 * The Assignments tab of the subject page: choose the kind, Submission or Code challenge. A card opens the list of
 * that kind's existing assignments (/instructor/subjects/<id>/assignments?kind=...), where + New creates another.
 */
export default function AssignmentKindChooser({
  subjectId,
  assignments,
}: {
  subjectId: number;
  assignments: Assignment[];
}) {
  const count = (kind: string) =>
    assignments.filter((a) => (a.assignment_type === "code_challenge" ? "code_challenge" : "submission") === kind)
      .length;

  return (
    <section className="mt-6 card" data-testid="assignment-type-chooser">
      <h2 className="text-xl font-semibold">Assignments and code challenges</h2>
      <p className="mt-1 text-sm text-gray-600">
        Choose the kind. Its existing assignments are listed on the next page, where + New creates another and a box
        opens its details to edit. Rubrics are in the Rubrics tab.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {KIND_OPTIONS.map((o) => {
          const n = count(o.value);
          return (
            <Link
              key={o.value}
              href={`/instructor/subjects/${subjectId}/assignments?kind=${o.value}`}
              className="rounded-md border border-gray-300 p-4 text-left hover:border-blue-500 hover:bg-blue-50"
              data-testid={`kind-${o.value}`}
            >
              <span className="block font-semibold">{o.title}</span>
              <span className="mt-1 block text-sm text-gray-600">{o.text}</span>
              <span className="mt-2 block text-xs font-semibold text-gray-700">
                {n === 0 ? "None yet" : `${n} existing`}
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
