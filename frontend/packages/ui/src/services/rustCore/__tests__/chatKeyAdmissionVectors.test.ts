// contract-test-file: tooling
// spec: specifications/features/auth#auth.keys.client-wrapped
// TS-generated parity vectors for the shared Rust chat-key admission policy.
// packages/openmates-rust/src/web_keys_ts_vectors.json holds inputs plus the
// outcomes of the existing ChatKeyManager.ts (flag off); this test fails if the
// TypeScript behaviour drifts from the vectors, and web_keys_tests.rs replays the
// same file against Rust. It also checks the crypto unit routes the key ops.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../cryptoService', () => ({
	_generateChatKeyInternal: () => new Uint8Array(32),
	encryptChatKeyWithMasterKey: async () => null,
	decryptChatKeyWithMasterKey: async () => null,
	clearCryptoKeyCache: () => undefined,
	computeKeyFingerprint4Bytes: () => new Uint8Array(4)
}));
vi.mock('../../anonymousChatKeyWrapping', () => ({ unwrapAnonymousChatKey: async () => null }));
vi.mock('../../db/decryptionFailureCache', () => ({ clearDecryptionFailureCache: () => undefined }));
vi.mock('../../recentChatWindowCache', () => ({ invalidateRecentChatWindow: () => undefined }));

import { ChatKeyManager, computeKeyFingerprint, type KeySource } from '../../encryption/ChatKeyManager';
import { createCryptoUnit } from '../crypto/cryptoUnitInstaller';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_keys_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const bytes = (value: number[]) => Uint8Array.from(value);

describe('ChatKeyManager parity vectors', () => {
	it('fingerprints match computeKeyFingerprint', () => {
		for (const c of vectors.fingerprints) expect(computeKeyFingerprint(bytes(c.key)), c.name).toBe(c.fingerprint);
	});

	it('injectKey outcomes match the admission decisions', () => {
		for (const c of vectors.injects) {
			const manager = new ChatKeyManager();
			const provenances = (manager as unknown as { provenances: Map<string, unknown> }).provenances;
			if (c.existing) {
				manager.injectKey('chat', bytes(c.existing), (c.currentSource ?? 'injected') as KeySource);
				// A loaded key without a recorded provenance is only reachable by clearing the private map.
				if (!c.currentSource) provenances.delete('chat');
			}
			const accepted = manager.injectKey('chat', bytes(c.key), c.source as KeySource, c.force);
			const after = manager.getKeySync('chat');
			const sourceAfter = manager.getProvenance('chat')?.source ?? null;
			let observed: string;
			if (!accepted) observed = 'reject';
			else if (!c.existing) observed = 'set';
			else if (after && Buffer.compare(Buffer.from(after), Buffer.from(c.key)) === 0 && Buffer.compare(Buffer.from(c.existing), Buffer.from(c.key)) !== 0) observed = 'replace';
			else observed = sourceAfter !== (c.currentSource ?? null) ? 'upgrade_source' : 'keep';
			expect(observed, c.name).toBe(c.decision);
		}
	});
});

describe('crypto unit key ops', () => {
	it('routes the key ops to the Rust exports unchanged', async () => {
		const calls: unknown[][] = [];
		const record = (name: string, value: unknown) => (...args: unknown[]) => { calls.push([name, ...args]); return value; };
		const binding: Record<string, unknown> = {
			webCryptoDecryptChatContent: () => null, webCryptoEncryptChatContent: () => null,
			webCryptoMasterDecrypt: () => null, webCryptoMasterEncrypt: () => null,
			webCryptoGenerateShareKeyBlob: () => null, webCryptoDecryptShareKeyBlob: () => null,
			webCryptoEncryptShareUrl: () => null, webCryptoDecryptShareUrl: () => null,
			webCryptoDecryptMedia: () => null, webCryptoChatKeyGuardBegin: () => null,
			webCryptoChatKeyGuardAfterAnonymous: () => null, webCryptoChatKeyGuardAfterPersisted: () => null,
			webCryptoBulkDecryptChat: () => [], webCryptoBulkEncryptChat: () => [], webCryptoBulkMasterDecrypt: () => [],
			webCryptoClearChatKeys: () => undefined, webCryptoChatKeyCacheSize: () => 0,
			keysFingerprint: record('fp', 'abc'), keysEqual: record('eq', true), keysInjectDecision: record('inj', 'reject'),
			...Object.fromEntries(['keysStateOffer', 'keysStateHandle', 'keysStateState', 'keysStateSetState', 'keysStateEnqueue', 'keysStateCancel', 'keysStatePending', 'keysStateMarkPersisted', 'keysStateReset', 'keysStateRemove', 'keysStateClear', 'keysStateStats', 'keysStateDecrypt', 'keysStateEncrypt'].map((n) => [n, () => undefined]))
		};
		const unit = createCryptoUnit(binding);
		const key = bytes([1, 2]);
		const replies = await unit.handle({ version: 1, requests: [
			{ id: 1, op: 'keysFingerprint', args: [key] },
			{ id: 2, op: 'keysEqual', args: [key, key] },
			{ id: 3, op: 'keysInjectDecision', args: [key, 'created', key, 'injected', false] }
		] });
		expect(replies?.responses.map((r) => ('error' in r ? r.error : r.value))).toEqual(['abc', true, 'reject']);
		expect(calls.map((c) => c[0])).toEqual(['fp', 'eq', 'inj']);
	});
});
