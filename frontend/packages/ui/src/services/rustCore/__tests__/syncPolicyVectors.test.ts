// TS-generated parity vectors for the shared Rust web chat-sync policy.
// The committed JSON (packages/openmates-rust/src/web_sync/ts_vectors.json) holds
// inputs plus the outcomes of the existing TypeScript services (flag off):
// chatSyncMerge.ts, chatSyncPhasedRetry.ts, chatSyncMessageKeyGuard.ts and the
// phased-sync helpers. This test fails if the TypeScript behaviour drifts from
// the vectors; web_sync/tests.rs replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
	effects: [] as unknown[][],
	samples: [] as string[],
	deletions: [] as { chatId: string; explicit: boolean }[],
}));

// Stub unwrappers shared with the generator: a wrapper's raw key is its prefix
// before ':'; 'bad…' fails master unwrapping, '…throw…' fails Team unwrapping.
vi.mock('../../encryption/MetadataEncryptor', () => ({
	decryptChatKeyWithMasterKey: async (s: string) => (typeof s !== 'string' || s.startsWith('bad') ? null : new TextEncoder().encode(s.split(':')[0])),
}));
vi.mock('../../directChatService', () => ({
	unwrapDirectTeamChatKey: async (_t: string, _c: string, s: string) => {
		if (s.includes('throw')) throw new Error('unwrap');
		return new TextEncoder().encode(s.split(':')[0]);
	},
}));
vi.mock('../../../stores/notificationStore', () => ({
	notificationStore: { info: (...a: unknown[]) => mocks.effects.push(['notify', a[0], a[1], a[2], a[3]]), error: () => undefined },
}));
vi.mock('../../../stores/phasedSyncStateStore', () => ({
	phasedSyncState: { markSyncCompleted: () => mocks.effects.push(['markSyncCompleted']) },
}));
vi.mock('../../db', () => ({
	chatDB: {
		getChat: async () => null,
		deleteChatIfNoPendingTurn: async (chatId: string) => (mocks.deletions.push({ chatId, explicit: false }), { deleted: true }),
		deleteChat: async (chatId: string) => { mocks.deletions.push({ chatId, explicit: true }); },
	},
}));
vi.mock('../../encryption/ChatKeyManager', () => ({
	chatKeyManager: { receiveKeyFromServer: async () => new Uint8Array(32), getKeySync: () => null, getKey: async () => null },
}));
vi.mock('../../encryption/MessageEncryptor', () => ({
	decryptWithChatKey: async (s: string) => (mocks.samples.push(s), 'plain'),
}));
vi.mock('../../chatListCache', () => ({ chatListCache: { removeChat: () => undefined } }));

import { hasEncryptedChatKeyMismatch, mergeServerChatWithLocal } from '../../chatSyncMerge';
import { computePhasedSyncRetryDelayMs, handlePhasedSyncRetryableErrorImpl, resetPhasedSyncRetry } from '../../chatSyncPhasedRetry';
import { filterPersistableSyncedMessagesWithSkipped } from '../../chatSyncMessageKeyGuard';
import type { ChatSynchronizationService } from '../../chatSyncService';
import type { Chat, Message } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_sync/ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));

/** The server record as the TS caller holds it: own keys may be `undefined`. */
function serverChat(name: string): Partial<Chat> & { id: string } {
	const { chat, undefinedKeys } = vectors.mergeServers[name];
	const out = { ...chat };
	for (const key of undefinedKeys) out[key] = undefined;
	return out;
}

beforeEach(() => {
	mocks.effects.length = 0;
	mocks.samples.length = 0;
	vi.useFakeTimers();
	vi.setSystemTime(vectors.now * 1000);
});
afterEach(() => {
	resetPhasedSyncRetry();
	vi.useRealTimers();
});

describe('chat sync parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('merge and key-mismatch outcomes match the committed vectors', async () => {
		for (const c of vectors.merge) {
			const server = serverChat(c.server);
			const local = vectors.mergeLocals[c.local] as Chat | null;
			const user = c.hasUser ? c.currentUserId : undefined;
			expect(json(await mergeServerChatWithLocal(server, local, user)), `${c.local}/${c.server}`).toEqual(c.out);
			if (local) expect(await hasEncryptedChatKeyMismatch(server, local)).toBe(c.keyMismatch);
		}
		for (const c of vectors.keyMismatch) {
			expect(await hasEncryptedChatKeyMismatch(serverChat(c.server), vectors.mergeLocals[c.local])).toBe(c.out);
		}
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('retry delay and retry state machine match the committed vectors', async () => {
		for (const c of vectors.retryDelay) {
			const hint = c.hasRetryAfter ? c.retryAfterMs : undefined;
			expect(computePhasedSyncRetryDelayMs(c.attempt, hint), JSON.stringify(c)).toBe(c.out);
		}
		for (const sequence of vectors.retry) {
			resetPhasedSyncRetry();
			let connected = true;
			const service = {
				clearPhasedSyncTimeout: () => mocks.effects.push(['clear']),
				startPhasedSync: async () => { mocks.effects.push(['start']); },
				dispatchEvent: (event: CustomEvent) => mocks.effects.push(['complete', event.detail]),
				get webSocketConnected_FOR_SENDERS_ONLY() { return connected; },
			} as unknown as ChatSynchronizationService;
			const timeout = vi.spyOn(globalThis, 'setTimeout');
			for (const step of sequence) {
				mocks.effects.length = 0;
				const event = step.event;
				if (event.reset) resetPhasedSyncRetry();
				else if (event.fire) {
					connected = event.connected ?? true;
					await vi.advanceTimersToNextTimerAsync();
				} else {
					timeout.mockClear();
					handlePhasedSyncRetryableErrorImpl(service, event.p);
					for (const call of timeout.mock.calls) mocks.effects.push(['schedule', call[1]]);
				}
				expect(json(mocks.effects), JSON.stringify(step.event)).toEqual(step.effects);
			}
			timeout.mockRestore();
		}
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('synced-message key admission matches the committed vectors', async () => {
		for (const c of vectors.messageKeys) {
			for (const group of c.out) {
				mocks.samples.length = 0;
				const messages = group.indices.map((i: number) => c.messages[i]) as Message[];
				const result = await filterPersistableSyncedMessagesWithSkipped(messages, new Map([[group.chatId, 'wrapped']]), 'vectors');
				expect(mocks.samples.length > 0 || result.skippedChatIds.size > 0).toBe(group.needsKey);
				expect(mocks.samples[0] ?? null).toBe(group.sample);
			}
		}
	});
});

