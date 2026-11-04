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

/** "9:05 am" in local time (for a time later today). */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true });
}

/** How long until a deadline, e.g. "Due in 3 days"; `urgent` under 24 hours. Null once it has passed. */
export function timeLeft(iso: string, now: number = Date.now()): { text: string; urgent: boolean } | null {
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms) || ms <= 0) return null;
  const minutes = Math.floor(ms / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const text =
    minutes < 60
      ? `Due in ${Math.max(1, minutes)} minute${minutes === 1 ? "" : "s"}`
      : hours < 24
        ? `Due in ${hours} hour${hours === 1 ? "" : "s"}`
        : `Due in ${days} day${days === 1 ? "" : "s"}`;
  return { text, urgent: hours < 24 };
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
