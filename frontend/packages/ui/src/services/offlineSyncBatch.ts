import { get } from "svelte/store";
import { activeTeamContext } from "../stores/teamStore";
import { userProfile } from "../stores/userProfile";
import { websocketStatus } from "../stores/websocketStatusStore";
import { getWorkspaceCacheEpoch } from "./workspaceCacheLifecycle";

export interface OfflineSyncContext {
  accountId: string | null;
  teamId: string | null;
  epoch: number;
  cacheEpoch: number;
  connectionGeneration: number;
}

let connectionGeneration = 0;

export function captureOfflineSyncContext(): OfflineSyncContext {
  const context = get(activeTeamContext);
  return { accountId: get(userProfile).user_id, teamId: context.teamId,
    epoch: context.epoch, cacheEpoch: getWorkspaceCacheEpoch(), connectionGeneration };
}

export function isOfflineSyncWorkspaceCurrent(captured: OfflineSyncContext): boolean {
  const current = captureOfflineSyncContext();
  return captured.accountId === current.accountId && captured.teamId === current.teamId &&
    captured.epoch === current.epoch && captured.cacheEpoch === current.cacheEpoch;
}

export function isOfflineSyncContextCurrent(captured: OfflineSyncContext): boolean {
  return isOfflineSyncWorkspaceCurrent(captured) && captured.connectionGeneration === connectionGeneration;
}

interface PendingBatch extends OfflineSyncContext {
  id: string;
  changeIds: Set<string>;
  receiptConsumed?: boolean;
  replayRequested?: boolean;
  terminalConflictDeleteIds: Set<string>;
  submittedOrders?: ReadonlyMap<string, { queueOrder: number | undefined; queueToken?: string }>;
}

export interface OfflineSyncBatchReceiptCounts {
  processed: number;
  errors: number;
  conflicts: number;
}

export interface OfflineSyncBatchResult {
  successfulIds: string[];
  retiredConflictIds: string[];
  submittedOrders?: ReadonlyMap<string, { queueOrder: number | undefined; queueToken?: string }>;
}

let pendingBatch: PendingBatch | null = null;
let batchSequence = 0;
websocketStatus.subscribe((state) => {
  if (state.status !== "connected") {
    connectionGeneration++;
    pendingBatch = null;
  }
});

export function beginOfflineSyncBatch(
  changeIds: string[], terminalConflictDeleteIds: string[] = [],
  submittedOrders?: ReadonlyMap<string, { queueOrder: number | undefined; queueToken?: string }>,
): string | null {
  // A slow receipt still owns its rows. Replacing it after ten seconds both
  // loses its ACK and resubmits already accepted edits. Disconnect invalidates
  // this reservation; a healthy connection waits for its matching receipt.
  if (pendingBatch && isOfflineSyncContextCurrent(pendingBatch)) {
    if (changeIds.some((id) => !pendingBatch!.changeIds.has(id) ||
      submittedOrders?.get(id)?.queueToken !== pendingBatch!.submittedOrders?.get(id)?.queueToken)) {
      pendingBatch.replayRequested = true;
    }
    return null;
  }
  const id = `${crypto.randomUUID()}:${++batchSequence}`;
  const submitted = new Set(changeIds);
  pendingBatch = { id, ...captureOfflineSyncContext(),
    changeIds: submitted,
    ...(submittedOrders ? { submittedOrders: new Map([...submittedOrders].map(([key, value]) => [key, { ...value }])) } : {}),
    terminalConflictDeleteIds: new Set(terminalConflictDeleteIds.filter((candidate) => submitted.has(candidate))) };
  return id;
}

export function cancelOfflineSyncBatch(id: string): void {
  if (pendingBatch?.id === id) pendingBatch = null;
}

/** Release only after acknowledged rows have committed their local cleanup. */
export function finishOfflineSyncBatch(id: string | undefined): boolean {
  if (!id || pendingBatch?.id !== id) return false;
  const retry = !!pendingBatch.replayRequested && isOfflineSyncContextCurrent(pendingBatch);
  pendingBatch = null;
  return retry;
}

export function consumeOfflineSyncBatch(id: string | undefined, successfulIds: string[]): string[] | null;
export function consumeOfflineSyncBatch(
  id: string | undefined, successfulIds: string[], counts: OfflineSyncBatchReceiptCounts, holdForCleanup?: boolean,
): OfflineSyncBatchResult | null;
export function consumeOfflineSyncBatch(
  id: string | undefined, successfulIds: string[], counts?: OfflineSyncBatchReceiptCounts, holdForCleanup = false,
): string[] | OfflineSyncBatchResult | null {
  const batch = pendingBatch;
  if (!id || !batch || batch.id !== id || batch.receiptConsumed) return null;
  if (!isOfflineSyncContextCurrent(batch)) { pendingBatch = null; return null; }
  if (holdForCleanup && counts) batch.receiptConsumed = true;
  else pendingBatch = null;
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
    retiredConflictIds: exactSingleConflict ? missingIds : [],
    ...(batch.submittedOrders ? { submittedOrders: batch.submittedOrders } : {}) };
}
