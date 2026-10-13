import { get } from "svelte/store";
import { activeTeamContext } from "../stores/teamStore";
import { userProfile } from "../stores/userProfile";
import { websocketStatus } from "../stores/websocketStatusStore";

interface PendingBatch {
  id: string;
  accountId: string | null;
  teamId: string | null;
  epoch: number;
  startedAt: number;
  changeIds: Set<string>;
  terminalConflictDeleteIds: Set<string>;
}

export interface OfflineSyncBatchReceiptCounts {
  processed: number;
  errors: number;
  conflicts: number;
}

export interface OfflineSyncBatchResult {
  successfulIds: string[];
  retiredConflictIds: string[];
}

let pendingBatch: PendingBatch | null = null;
let batchSequence = 0;
websocketStatus.subscribe((state) => {
  if (state.status !== "connected") pendingBatch = null;
});

export function beginOfflineSyncBatch(
  changeIds: string[], terminalConflictDeleteIds: string[] = [],
): string | null {
  const context = get(activeTeamContext);
  const accountId = get(userProfile).user_id;
  if (
    pendingBatch && pendingBatch.accountId === accountId &&
    pendingBatch.teamId === context.teamId && pendingBatch.epoch === context.epoch &&
    Date.now() - pendingBatch.startedAt < 10_000
  ) return null;
  const id = `${crypto.randomUUID()}:${++batchSequence}`;
  const submitted = new Set(changeIds);
  pendingBatch = { id, accountId, teamId: context.teamId, epoch: context.epoch,
    startedAt: Date.now(), changeIds: submitted,
    terminalConflictDeleteIds: new Set(terminalConflictDeleteIds.filter((candidate) => submitted.has(candidate))) };
  return id;
}

export function cancelOfflineSyncBatch(id: string): void {
  if (pendingBatch?.id === id) pendingBatch = null;
}

export function consumeOfflineSyncBatch(id: string | undefined, successfulIds: string[]): string[] | null;
export function consumeOfflineSyncBatch(
  id: string | undefined, successfulIds: string[], counts: OfflineSyncBatchReceiptCounts,
): OfflineSyncBatchResult | null;
export function consumeOfflineSyncBatch(
  id: string | undefined, successfulIds: string[], counts?: OfflineSyncBatchReceiptCounts,
): string[] | OfflineSyncBatchResult | null {
  const batch = pendingBatch;
  if (!id || !batch || batch.id !== id) return null;
  pendingBatch = null;
  const context = get(activeTeamContext);
  if (
    batch.accountId !== get(userProfile).user_id ||
    batch.teamId !== context.teamId || batch.epoch !== context.epoch
  ) return null;
  const accepted = successfulIds.filter((changeId) => batch.changeIds.has(changeId));
  if (!counts) return accepted;
  const uniqueSuccesses = new Set(successfulIds);
  const missingIds = [...batch.changeIds].filter((changeId) => !uniqueSuccesses.has(changeId));
  const exactSingleConflict = counts.errors === 0 && counts.conflicts === 1 &&
    Number.isInteger(counts.processed) && counts.processed === batch.changeIds.size - 1 &&
    successfulIds.length === uniqueSuccesses.size &&
    uniqueSuccesses.size === batch.changeIds.size - 1 &&
    [...uniqueSuccesses].every((changeId) => batch.changeIds.has(changeId)) &&
    missingIds.length === 1 && batch.terminalConflictDeleteIds.has(missingIds[0]);
  return { successfulIds: accepted,
    retiredConflictIds: exactSingleConflict ? missingIds : [] };
}
