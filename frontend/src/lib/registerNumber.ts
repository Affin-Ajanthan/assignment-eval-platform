/** Every register number is TST/<batch>/<own number>, e.g. TST/01/001 (REGISTER_PREFIX in app/main.py). */
export const REGISTER_PREFIX = "TST";

/** The register number for a batch and the student's own number; "" when no own number is given. */
export function registerNumberFor(batch: string, own: string): string {
  const last = own.trim();
  return last ? `${REGISTER_PREFIX}/${batch.trim()}/${last}` : "";
}

/**
 * The student's own number: what follows TST/<batch>/. A number in any other form is returned whole, so the admin
 * sees it and fixes it instead of it being lost on the next save.
 */
export function ownNumberOf(registerNumber: string, batch: string): string {
  const prefix = `${REGISTER_PREFIX}/${batch.trim()}/`;
  return registerNumber.startsWith(prefix) ? registerNumber.slice(prefix.length) : registerNumber;
}

/** The batches the students and subjects are in, each once, in order: the choices of the Batch box. */
export function batchList(items: { batch?: string }[]): string[] {
  const batches = new Set(items.map((s) => (s.batch ?? "").trim()).filter(Boolean));
  return Array.from(batches).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}
