// contract-test-file: tooling
// spec: specifications/features/auth#auth.keys.client-wrapped
// Keys lane K3: the TS bulk chat-key load plan (flag-off reference) must equal the
// vectors the Rust web_key_bulk module replays; the key ops reach the Worker exports.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	BULK_BATCH_SIZE, BULK_MAX_RETRIES, BULK_RETRY_DELAY_MS, bulkBatchRanges, bulkRetryStep
} from '../../db/chatKeyBulkPlan';
import { keyBulkBatches, keyBulkRetryStep } from '../crypto/keyOps';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_key_bulk_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

describe('bulk chat-key load plan vectors', () => {
	it('constants match', () => {
		expect([BULK_BATCH_SIZE, BULK_RETRY_DELAY_MS, BULK_MAX_RETRIES]).toEqual([vectors.batchSize, vectors.retryDelayMs, vectors.maxRetries]);
	});
	it('batch ranges match', () => {
		for (const c of vectors.batches) expect(bulkBatchRanges(c.count), String(c.count)).toEqual(c.ranges);
	});
	it('retry steps match', () => {
		for (const c of vectors.retries) expect(bulkRetryStep(c.retryCount, c.masterKeyAvailable), JSON.stringify(c)).toBe(c.step);
	});
	it('key ops call the Worker exports with plain arguments', async () => {
		const calls: unknown[][] = [];
		const client = { call: async (op: string, ...args: unknown[]) => { calls.push([op, ...args]); return op === 'keysBulkBatches' ? [[0, 3]] : 'retry'; } };
		expect(await keyBulkBatches(client as never, 3)).toEqual([[0, 3]]);
		expect(await keyBulkRetryStep(client as never, 2, false)).toBe('retry');
		expect(calls).toEqual([['keysBulkBatches', 3], ['keysBulkRetryStep', 2, false]]);
	});
});
