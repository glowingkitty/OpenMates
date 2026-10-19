import type { OfflineChange } from "../types/chat";

/** Component versions can reset on deletion; only durable insertion order is chronology. */
export function orderOfflineChanges(changes: OfflineChange[]): {
  ready: OfflineChange[]; retainedCount: number;
} {
  const groups = new Map<string, OfflineChange[]>();
  for (const change of changes) {
    const component = change.type === "title" ? "title" : "draft";
    const key = JSON.stringify([change.team_id ?? null, change.chat_id, component]);
    const group = groups.get(key) ?? [];
    group.push(change);
    groups.set(key, group);
  }
  const ready: OfflineChange[] = [];
  let retainedCount = 0;
  for (const group of groups.values()) {
    const legacy = group.filter((change) => change.queue_order === undefined);
    const ordered = group.filter((change) => change.queue_order !== undefined);
    const orders = ordered.map((change) => change.queue_order!);
    // Multiple old UUID-keyed rows have no recoverable chronology. In particular,
    // sorting draft_v would put a post-delete draft before its older deletion.
    if (legacy.length > 1 || (legacy.length > 0 && ordered.length > 0) ||
      orders.some((order) => !Number.isSafeInteger(order) || order < 1) ||
      new Set(orders).size !== orders.length) {
      retainedCount += group.length;
      continue;
    }
    // An older tab may append a legacy row after an ordered insertion. Mixed
    // groups cannot establish chronology, especially across draft deletion.
    ready.push(...legacy, ...ordered.sort((a, b) => a.queue_order! - b.queue_order!));
  }
  return { ready, retainedCount };
}
