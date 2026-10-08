// Date/time helpers. The API stores and returns UTC; everything shown to
// people is in the browser's local time zone.

/** "07 Oct 2026, 9:00 am" (12-hour clock) in local time. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Split a UTC ISO time into local "YYYY-MM-DD" / "HH:MM" for date and time inputs. */
export function splitLocal(iso: string): { date: string; time: string } {
  const d = new Date(iso);
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  };
}

/** Combine local date and time inputs into a Date, or null if either is missing/invalid. */
export function combineLocal(date: string, time: string): Date | null {
  if (!date || !time) return null;
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const result = new Date(y, m - 1, d, hh, mm);
  return Number.isNaN(result.getTime()) ? null : result;
}

/** "Marks: 34 / 40" style text; null mark means not graded yet. */
export function formatMark(mark: number | null, max: number | null): string {
  if (mark === null) return "Not yet graded";
  const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""));
  return max === null ? fmt(mark) : `${fmt(mark)} / ${fmt(max)}`;
}
