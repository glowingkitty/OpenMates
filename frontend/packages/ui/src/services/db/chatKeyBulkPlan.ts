// frontend/packages/ui/src/services/db/chatKeyBulkPlan.ts
// spec: specifications/features/auth#auth.keys.client-wrapped
// Pure planning for the bulk chat-key load of chatKeyManagement.ts (keys lane K3):
// decrypt batch boundaries and the master-key retry step. This is the flag-off
// reference and the source of the TS-generated vectors in
// packages/openmates-rust/src/web_key_bulk_ts_vectors.json; with the Rust core
// flag on the same decisions come from `web_key_bulk` in the Worker.

export const BULK_BATCH_SIZE = 20;
export const BULK_RETRY_DELAY_MS = 500;
export const BULK_MAX_RETRIES = 6;

export type BulkRetryStep = 'decrypt' | 'retry' | 'give_up';

/** Half-open `[start, end)` index ranges of the decrypt batches for `count` keys. */
export function bulkBatchRanges(count: number): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  for (let i = 0; i < count; i += BULK_BATCH_SIZE) {
    ranges.push([i, Math.min(i + BULK_BATCH_SIZE, count)]);
  }
  return ranges;
}

/** What the retry timer does after `retryCount` attempts (already incremented). */
export function bulkRetryStep(retryCount: number, masterKeyAvailable: boolean): BulkRetryStep {
  if (masterKeyAvailable) return 'decrypt';
  return retryCount < BULK_MAX_RETRIES ? 'retry' : 'give_up';
}
