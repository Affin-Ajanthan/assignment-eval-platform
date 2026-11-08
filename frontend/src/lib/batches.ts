/** Helpers for the batch pages: /student/batches/<batch> and /instructor/batches/<batch>. */

/** The address part for subjects that have no batch. */
export const NO_BATCH_SEGMENT = "no-batch";

/** The address part of a batch ("01" -> "01", "" -> "no-batch"). */
export function batchSegment(batch?: string): string {
  const b = (batch ?? "").trim();
  return b ? encodeURIComponent(b) : NO_BATCH_SEGMENT;
}

/** The batch an address part stands for ("" for the no-batch page). */
export function batchFromSegment(segment: string): string {
  if (segment === NO_BATCH_SEGMENT) return "";
  try {
    return decodeURIComponent(segment).trim();
  } catch {
    return segment.trim();
  }
}

/** "Batch 01", or "No batch". */
export const batchTitle = (batch: string) => (batch ? `Batch ${batch}` : "No batch");

export type BatchGroup<T> = { batch: string; segment: string; label: string; items: T[] };

/** Items grouped by their batch, the batches in order and the ones without a batch last. */
export function groupByBatch<T extends { batch?: string }>(items: T[]): BatchGroup<T>[] {
  const byBatch = new Map<string, T[]>();
  for (const item of items) {
    const batch = (item.batch ?? "").trim();
    byBatch.set(batch, [...(byBatch.get(batch) ?? []), item]);
  }
  return Array.from(byBatch, ([batch, list]) => ({
    batch,
    segment: batchSegment(batch),
    label: batchTitle(batch),
    items: list,
  })).sort((a, b) =>
    a.batch === "" ? 1 : b.batch === "" ? -1 : a.batch.localeCompare(b.batch, undefined, { numeric: true }),
  );
}
