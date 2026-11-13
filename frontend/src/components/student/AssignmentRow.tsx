"use client";

import { ReactNode, useEffect, useRef, useState } from "react";
import { StudentAssignment } from "@/lib/api";
import { formatDateTime, timeLeft } from "@/lib/datetime";
import Badge from "@/components/Badge";

/**
 * One line of "Available assignments": the name, when it is due (and how long is left) and whether the student has
 * handed it in. Pressing it opens the assignment's full details (`children`, the assignment card) right under it and
 * scrolls down to them; pressing it again closes them.
 */
export default function AssignmentRow({
  a,
  expanded,
  onToggle,
  children,
}: {
  a: StudentAssignment;
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLLIElement>(null);
  const detailsId = `assignment-details-${a.id}`;

  // The clock behind "Due in ...": it moves on every 30 seconds, so the minutes stay right while the page is open.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  // Opening it scrolls down to its details (the row stays in view at the top, below the fixed header).
  useEffect(() => {
    if (!expanded) return;
    const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    ref.current?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  }, [expanded]);

  const sub = a.my_submission;
  const taskCount = a.questions?.length ?? 0;
  const handedIn =
    a.assignment_type === "code_challenge" && taskCount > 1 && sub
      ? `${sub.questions_submitted} of ${taskCount} tasks submitted`
      : "Submitted";
  const left = timeLeft(a.deadline, now);

  return (
    <li ref={ref} data-testid="available-assignment">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={detailsId}
        className={`flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border bg-white px-4 py-3 text-left shadow-sm hover:border-blue-500 hover:bg-blue-50 ${
          expanded ? "border-blue-500" : "border-gray-200"
        }`}
        data-testid="open-available-assignment"
      >
        <span className="min-w-0">
          <span className="block break-words text-base font-semibold">
            {a.name}
            {a.assignment_type === "code_challenge" && (
              <span className="ml-2 text-xs font-normal text-gray-500">Code challenge</span>
            )}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-700">
            <span data-testid="row-deadline">
              {a.past_deadline ? "Deadline passed" : "Due"} {formatDateTime(a.deadline)}
            </span>
            {left && (
              <Badge tone={left.urgent ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-800"}>{left.text}</Badge>
            )}
            {a.past_deadline && a.accept_until && (
              <span className="text-xs text-gray-600">Late work accepted until {formatDateTime(a.accept_until)}</span>
            )}
          </span>
        </span>
        <span className="flex items-center gap-3">
          <Badge
            tone={
              sub
                ? "border border-green-700 bg-green-50 text-green-800"
                : "border border-amber-500 bg-amber-50 text-amber-900"
            }
          >
            {sub ? handedIn : "Not submitted"}
          </Badge>
          <span className="text-xs font-semibold text-blue-700">{expanded ? "Hide details ▴" : "Details ▾"}</span>
        </span>
      </button>
      {expanded && (
        <ul id={detailsId} className="mt-2">
          {children}
        </ul>
      )}
    </li>
  );
}
