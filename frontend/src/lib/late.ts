import { formatMark } from "@/lib/datetime";

// Late work: handed in after the deadline and its grace period (see Assignment.lateness_at in the backend).

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""));

/** How late work was, from the seconds after the deadline: "45 min", "5 h 10 min", "2 days 3 h". */
export function lateText(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return hours > 0 ? `${days} day${days === 1 ? "" : "s"} ${hours} h` : `${days} day${days === 1 ? "" : "s"}`;
  if (hours > 0) return mins > 0 ? `${hours} h ${mins} min` : `${hours} h`;
  return `${mins} min`;
}

/** The percent of the mark a penalty takes, as shown: "10", "12.5". */
export const percentText = (percent: number) => fmt(percent);

/** A penalty as shown: "20%" when it is in percent, "10 marks" (or "1 mark") when it is in marks. */
export const penaltyText = (percent: number | null | undefined, marks: number | null | undefined) =>
  marks ? `${fmt(marks)} mark${marks === 1 ? "" : "s"}` : `${percentText(percent ?? 0)}%`;

/**
 * A mark with its late penalty beside it: "34 / 40 → 30.6 / 40 (late −10%)", or "34 / 40 → 24 / 40 (late −10 marks)"
 * when the penalty is in marks. Without a penalty it is just the mark. `raw` is the mark before the penalty and
 * `final` the one after (what counts).
 */
export function markWithPenalty(
  raw: number | null | undefined,
  final: number | null,
  max: number | null,
  percent: number | null | undefined,
  marks?: number | null,
): string {
  if (final === null || raw === null || raw === undefined || !(percent || marks)) return formatMark(final, max);
  return `${formatMark(raw, max)} → ${formatMark(final, max)} (late −${penaltyText(percent, marks)})`;
}
