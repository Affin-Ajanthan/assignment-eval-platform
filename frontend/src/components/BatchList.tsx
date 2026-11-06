import Link from "next/link";
import { BatchGroup } from "@/lib/batches";

/** The batches as a list, one row each ("Batch 01 ... 3 subjects"). A row opens `<hrefBase>/<batch>`, the page of that batch's subjects. */
export default function BatchList({
  groups,
  hrefBase,
  testId,
}: {
  groups: Pick<BatchGroup<unknown>, "segment" | "label" | "items">[];
  hrefBase: string;
  testId: string;
}) {
  return (
    <ul
      className="mt-3 divide-y divide-gray-200 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm"
      data-testid={testId}
    >
      {groups.map((g) => (
        <li key={g.segment}>
          <Link
            href={`${hrefBase}/${g.segment}`}
            className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-blue-50"
            data-testid="batch-card"
          >
            <span className="text-base font-semibold">{g.label}</span>
            <span className="flex items-center gap-3 text-sm text-gray-500">
              {g.items.length} subject{g.items.length === 1 ? "" : "s"}
              <span aria-hidden="true" className="text-blue-700">
                →
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
