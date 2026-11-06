// `sync` unit of the shared Rust core Worker: the real router and installer over
// a binding that answers the committed Rust outcomes (web_sync/ts_vectors.json;
// the Rust decisions themselves are proven by web_sync/tests.rs), and the
// flag-on page adapter (rustChatSyncPolicy.ts) producing records strictly equal
// (values and key order) to the TypeScript services, with no TS fallback.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ samples: [] as string[], effects: [] as unknown[][] }));
vi.mock('../../encryption/MetadataEncryptor', () => ({
	decryptChatKeyWithMasterKey: async (s: string) => (typeof s !== 'string' || s.startsWith('bad') ? null : new TextEncoder().encode(s.split(':')[0])),
}));
vi.mock('../../directChatService', () => ({
	unwrapDirectTeamChatKey: async (_t: string, _c: string, s: string) => {
		if (s.includes('throw')) throw new Error('unwrap');
		return new TextEncoder().encode(s.split(':')[0]);
	},
}));
vi.mock('../../db', () => ({ chatDB: { getChat: async () => null } }));
vi.mock('../../encryption/ChatKeyManager', () => ({
	chatKeyManager: { receiveKeyFromServer: async () => new Uint8Array(32), getKeySync: () => null, getKey: async () => null },
}));
vi.mock('../../encryption/MessageEncryptor', () => ({ decryptWithChatKey: async (s: string) => (mocks.samples.push(s), 'plain') }));

import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installSyncUnit } from '../sync/syncUnit';
import { rustSyncStats } from '../sync/syncUnitClient';
import type { SyncBinding } from '../sync/syncProtocol';
import * as rust from '../sync/rustChatSyncPolicy';
import { mergeServerChatWithLocal } from '../../chatSyncMerge';
import { filterPersistableSyncedMessagesWithSkipped } from '../../chatSyncMessageKeyGuard';
import type { ChatSynchronizationService } from '../../chatSyncService';
import type { Chat, Message } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_sync/ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const key = (value: unknown) => JSON.stringify(value ?? null);

function serverChat(name: string): Partial<Chat> & { id: string } {
	const { chat, undefinedKeys } = vectors.mergeServers[name];
	const out = { ...chat };
	for (const k of undefinedKeys) out[k] = undefined;
	return out;
}

const mergeOutcomes = new Map<string, { keyMismatch: boolean | null; out: unknown }>();
for (const c of vectors.merge) {
	mergeOutcomes.set(key([vectors.mergeServers[c.server].chat, vectors.mergeLocals[c.local], c.hasUser ? c.currentUserId : '<none>']), c);
}
const retrySteps: unknown[] = [];
const ops: string[] = [];
const binding: SyncBinding = {
	sync_merge_chat: (input) => {
		const i = JSON.parse(input);
		ops.push('merge');
		const c = mergeOutcomes.get(key([i.server, i.local, 'currentUserId' in i ? i.currentUserId : '<none>']));
		if (!c) throw new Error('protocol');
		if (i.local && i.keyMismatch === null) return JSON.stringify({ kind: 'compareKeys', plan: { kind: 'decided', mismatch: c.keyMismatch } });
		return JSON.stringify({ kind: 'merged', chat: c.out });
	},
	sync_key_mismatch: () => JSON.stringify({ kind: 'master' }),
	sync_retry_step: (input) => (ops.push(`retry ${input}`), JSON.stringify(retrySteps.shift())),
	sync_chat_admission: (input) => JSON.stringify({ skip: !JSON.parse(input).server.encrypted_chat_key }),
	sync_metadata_chat: () => { throw new Error('protocol'); },
	sync_deletion_plan: () => '[]',
	sync_message_key_plan: (input) => {
		const messages = JSON.parse(input).messages;
		const c = vectors.messageKeys.find((v: { messages: unknown[] }) => v.messages.length === messages.length
			&& v.messages.every((m: Record<string, unknown>, i: number) => m.chat_id === messages[i].chat_id));
		return JSON.stringify(c.out);
	},
};

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { sync: installSyncUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {},
	};
	return endpoint;
}

let unregister: (() => void) | null = null;
beforeEach(() => {
	ops.length = 0;
	mocks.samples.length = 0;
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => {
	unregister?.();
	vi.useRealTimers();
});

describe('shared sync unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a binding without the sync exports', () => {
		const channel = new MessageChannel();
		expect(() => installSyncUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('merges every vector chat into a record strictly equal to the TypeScript merge, key order included', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(vectors.now * 1000);
		for (const c of vectors.merge) {
			const local = vectors.mergeLocals[c.local] as Chat | null;
			const user = c.hasUser ? c.currentUserId : undefined;
			const expected = await mergeServerChatWithLocal(serverChat(c.server), local, user);
			const got = await rust.mergeServerChatWithLocal(serverChat(c.server), local, user);
			expect(got, `${c.local}/${c.server}`).toStrictEqual(expected);
			expect(Object.keys(got)).toEqual(Object.keys(expected));
		}
		expect(ops.length).toBeGreaterThan(vectors.merge.length);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('settles a master-key plan by unwrapping both wrappers on the page', async () => {
		const local = vectors.mergeLocals.basic as Chat;
		await expect(rust.hasEncryptedChatKeyMismatch({ id: 'c1', encrypted_chat_key: 'k1:other' }, local)).resolves.toBe(false);
		await expect(rust.hasEncryptedChatKeyMismatch({ id: 'c1', encrypted_chat_key: 'k2:other' }, local)).resolves.toBe(true);
		await expect(rust.hasEncryptedChatKeyMismatch({ id: 'c1', encrypted_chat_key: 'bad:x' }, local)).resolves.toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('filters synced messages exactly like the TypeScript key guard', async () => {
		for (const c of vectors.messageKeys) {
			const messages = c.messages as Message[];
			const keys = new Map(c.out.map((g: { chatId: string }) => [g.chatId, 'wrapped']));
			const expected = await filterPersistableSyncedMessagesWithSkipped(messages, keys as Map<string, string>, 'ts');
			const tsSamples = [...mocks.samples];
			mocks.samples.length = 0;
			const got = await rust.filterPersistableSyncedMessagesWithSkipped(messages, keys as Map<string, string>, 'rust');
			expect(got).toStrictEqual(expected);
			expect(mocks.samples).toEqual(tsSamples);
			mocks.samples.length = 0;
		}
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('applies the Rust retry steps: schedule, pending, then exhausted completion', async () => {
		vi.useFakeTimers();
		const effects: unknown[][] = [];
		const service = {
			clearPhasedSyncTimeout: () => effects.push(['clear']),
			startPhasedSync: async () => { effects.push(['start']); },
			dispatchEvent: (event: CustomEvent) => effects.push(['complete', event.detail]),
			webSocketConnected_FOR_SENDERS_ONLY: true,
		} as unknown as ChatSynchronizationService;
		const state = { attempt: 0, timer: null as ReturnType<typeof setTimeout> | null, generation: 0 };
		const sink = { markSyncCompleted: () => effects.push(['markSyncCompleted']), notifyDegraded: () => effects.push(['notify']) };
		retrySteps.push({ kind: 'schedule', attempt: 1, delayMs: 3000, maxAttempts: 5 }, { kind: 'pending' }, { kind: 'ignore' },
			{ kind: 'exhausted', maxAttempts: 5 });
		await rust.handlePhasedSyncRetryableError(service, { retryable: true }, state, sink);
		expect(state.attempt).toBe(1);
		await rust.handlePhasedSyncRetryableError(service, { retryable: true, retry_after_ms: 10 }, state, sink);
		await rust.handlePhasedSyncRetryableError(service, {}, state, sink);
		expect(ops.slice(-1)[0]).toBe('retry {"timerPending":true,"attempt":1}');
		await vi.advanceTimersByTimeAsync(3000);
		expect(state.timer).toBeNull();
		await rust.handlePhasedSyncRetryableError(service, { retryable: true }, state, sink);
		expect(effects).toEqual([
			['clear'], ['clear'], ['start'], ['clear'], ['markSyncCompleted'],
			['complete', { status: 'completed_via_error', synthetic: true, reason: 'error' }], ['notify'],
		]);
		expect(state.attempt).toBe(0);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('rejects with the fixed protocol code instead of falling back to TypeScript', async () => {
		const before = rustSyncStats.failures;
		await expect(rust.metadataOnlyChat('Load more', { id: 'c1' }, null)).rejects.toMatchObject({ code: 'protocol' });
		expect(rustSyncStats.failures).toBe(before + 1);
	});
});
