/** Pure receipt decision for an offline sync batch (ported to shared Rust: web_send_prep/outbox_receipt.rs). */
export interface OfflineBatchReceiptCounts { processed: number; errors: number; conflicts: number }

export function decideOfflineBatchReceipt(
  changeIds: readonly string[], terminalConflictDeleteIds: readonly string[],
  successfulIds: readonly string[], counts?: OfflineBatchReceiptCounts,
): { accepted: string[]; retiredConflictIds: string[] } {
  const batchIds = new Set(changeIds);
  const terminal = new Set(terminalConflictDeleteIds);
  const accepted = successfulIds.filter((changeId) => batchIds.has(changeId));
  if (!counts) return { accepted, retiredConflictIds: [] };
  const uniqueSuccesses = new Set(successfulIds);
  const missingIds = [...batchIds].filter((changeId) => !uniqueSuccesses.has(changeId));
  const exactSingleConflict = counts.errors === 0 && counts.conflicts === 1 &&
    Number.isInteger(counts.processed) && counts.processed === batchIds.size - 1 &&
    successfulIds.length === uniqueSuccesses.size &&
    uniqueSuccesses.size === batchIds.size - 1 &&
    [...uniqueSuccesses].every((changeId) => batchIds.has(changeId)) &&
    missingIds.length === 1 && terminal.has(missingIds[0]);
  return { accepted, retiredConflictIds: exactSingleConflict ? missingIds : [] };
}
