/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) page adapter for the offline outbox
 * decisions of the shared Rust core Worker `sendPrep` unit. Loaded only by the
 * guarded branches of sendersSync.ts and offlineSyncBatch.ts, so default builds
 * never bundle it. There is no TypeScript fallback: a refused call rejects.
 */
import type { OfflineChange } from '../../../types/chat';
import type { OfflineReceiptCounts } from './sendPrepProtocol';
import { claimOfflineSyncBatch, type OfflineSyncBatchReceiptCounts, type OfflineSyncBatchResult } from '../../offlineSyncBatch';
import { sendPrepCall } from './sendPrepUnitClient';

export async function rustOrderOfflineChanges(changes: OfflineChange[]): Promise<{ ready: OfflineChange[]; retainedCount: number }> {
	const rows = changes.map((change) => ({
		chat_id: change.chat_id, team_id: change.team_id, type: change.type, queue_order: change.queue_order,
	}));
	const answer = await sendPrepCall('orderOffline', { rows });
	return { ready: answer.ready.map((index) => changes[index]), retainedCount: answer.retained };
}

export function rustDecideOfflineBatchReceipt(
	changeIds: readonly string[], terminalConflictDeleteIds: readonly string[],
	successfulIds: readonly string[], counts: OfflineReceiptCounts | null,
): Promise<{ accepted: string[]; retiredConflictIds: string[] }> {
	return sendPrepCall('offlineReceipt', {
		changeIds: [...changeIds], terminalConflictDeleteIds: [...terminalConflictDeleteIds],
		successfulIds: [...successfulIds], counts,
	});
}

/** Rust-decided twin of `consumeOfflineSyncBatch(id, successfulIds, counts, true)`. */
export async function rustConsumeOfflineSyncBatch(
	id: string | undefined, successfulIds: string[], counts: OfflineSyncBatchReceiptCounts,
): Promise<OfflineSyncBatchResult | null> {
	const claim = claimOfflineSyncBatch(id, true);
	if (!claim) return null;
	const decision = await rustDecideOfflineBatchReceipt(claim.changeIds, claim.terminalConflictDeleteIds, successfulIds, counts);
	return { successfulIds: decision.accepted, retiredConflictIds: decision.retiredConflictIds,
		...(claim.submittedOrders ? { submittedOrders: claim.submittedOrders } : {}) };
}
