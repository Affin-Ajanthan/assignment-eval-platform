/**
 * The subjects a person opened last, newest first, kept in this browser (localStorage) per role and user. The home
 * pages show the first few of them as "Recently viewed". Nothing is sent to the server, and a browser that blocks
 * storage just has no recent subjects.
 */
const KEEP = 12; // more than the home pages show, so subjects that were deleted since do not leave gaps

const keyFor = (role: string, userId: number) => `recent-subjects:${role}:${userId}`;

export function readRecentSubjects(role: string, userId: number): number[] {
  try {
    const list: unknown = JSON.parse(localStorage.getItem(keyFor(role, userId)) ?? "[]");
    return Array.isArray(list) ? list.filter((id): id is number => typeof id === "number").slice(0, KEEP) : [];
  } catch {
    return [];
  }
}

/** Puts `subjectId` first in the list (once). */
export function recordRecentSubject(role: string, userId: number, subjectId: number): void {
  try {
    const next = [subjectId, ...readRecentSubjects(role, userId).filter((id) => id !== subjectId)].slice(0, KEEP);
    localStorage.setItem(keyFor(role, userId), JSON.stringify(next));
  } catch {
    /* storage blocked: nothing to remember */
  }
}
