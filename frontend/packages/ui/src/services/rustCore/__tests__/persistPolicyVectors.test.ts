// TS-generated parity vectors for the shared Rust IndexedDB row policy.
// The committed JSON (packages/openmates-rust/src/web_persist/ts_vectors.json) holds
// inputs plus the outcomes of the flag-off TypeScript (db/messageRowPolicy.ts). This
// test fails if the TypeScript behaviour drifts from the vectors; web_persist/tests.rs
// replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	hasNewEncryptedFields, isContentDuplicate, isSafeToEvictMessage, shouldUpdateMessage,
} from '../../db/messageRowPolicy';
import type { Message } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_persist/ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

type Pair = { existing: Message; incoming: Message; out: boolean };

describe('message row policy parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('shouldUpdateMessage matches the committed vectors', () => {
		expect(vectors.shouldUpdate.length).toBeGreaterThan(600);
		for (const c of vectors.shouldUpdate as Pair[]) expect(shouldUpdateMessage(c.existing, c.incoming), JSON.stringify(c)).toBe(c.out);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('hasNewEncryptedFields matches the committed vectors', () => {
		for (const c of vectors.hasNewEncryptedFields as Pair[]) expect(hasNewEncryptedFields(c.existing, c.incoming), JSON.stringify(c)).toBe(c.out);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('isContentDuplicate matches the committed vectors', () => {
		for (const c of vectors.contentDuplicate as Pair[]) expect(isContentDuplicate(c.existing, c.incoming), JSON.stringify(c)).toBe(c.out);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('isSafeToEvictMessage matches the committed vectors', () => {
		for (const c of vectors.safeToEvict as Array<{ message: Message | null; out: boolean }>) {
			expect(isSafeToEvictMessage(c.message ?? undefined), JSON.stringify(c)).toBe(c.out);
		}
	});
});
