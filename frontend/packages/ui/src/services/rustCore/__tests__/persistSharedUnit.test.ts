// `persist` unit of the shared Rust core Worker: the real router and installer over a
// binding that answers with the flag-off TypeScript policy (the Rust decisions
// themselves are proven by web_persist/tests.rs over the same TS-generated vectors),
// and the flag-on page adapter (rustMessageRowPolicy.ts) which projects rows to the
// fields the policy reads and follows the unit's answers with no TS fallback.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installPersistUnit } from '../persist/persistUnit';
import { rustPersistStats } from '../persist/persistUnitClient';
import type { PersistBinding } from '../persist/persistProtocol';
import * as rust from '../persist/rustMessageRowPolicy';
import { rustCacheDecisions } from '../persist/rustCachePolicy';
import { rustChatRowDecisions } from '../persist/rustChatRowPolicy';
import { PERSIST_OPS } from '../persist/persistProtocol';
import { referenceOps } from './persistPolicyReference';
import { hasNewEncryptedFields, isContentDuplicate, isSafeToEvictMessage, shouldUpdateMessage } from '../../db/messageRowPolicy';
import type { Message } from '../../../types/chat';

const seen: string[] = [];
const rows = (value: unknown) => value as Message[];
const binding: PersistBinding = {
	persist_message_should_update: (input) => {
		const { pairs } = JSON.parse(input);
		seen.push(input);
		return JSON.stringify({ results: pairs.map((p: { existing: Message; incoming: Message }) => shouldUpdateMessage(p.existing, p.incoming)) });
	},
	persist_message_save_decision: (input) => {
		const i = JSON.parse(input);
		seen.push(input);
		return JSON.stringify({ shouldUpdate: shouldUpdateMessage(i.existing, i.incoming), fillsEncrypted: hasNewEncryptedFields(i.existing, i.incomingEncrypted) });
	},
	persist_message_content_duplicate: (input) => {
		const i = JSON.parse(input);
		seen.push(input);
		const index = rows(i.candidates).findIndex((c) => c.message_id !== i.message.message_id && isContentDuplicate(c, i.message));
		return JSON.stringify({ index: index < 0 ? null : index });
	},
	persist_message_safe_to_evict: (input) => {
		seen.push(input);
		return JSON.stringify({ results: (JSON.parse(input).messages as Array<Message | null>).map((m) => isSafeToEvictMessage(m ?? undefined)) });
	},
};

// The cache and chat-row ops answer with the TypeScript reference of the same policy.
for (const [op, exportName] of Object.entries(PERSIST_OPS)) {
	if (!(op in referenceOps)) continue;
	(binding as unknown as Record<string, (input: string) => string>)[exportName] = (input) => {
		seen.push(input);
		return JSON.stringify(referenceOps[op](JSON.parse(input)));
	};
}

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { persist: installPersistUnit },
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

const message = (extra: Partial<Message> & Record<string, unknown>): Message =>
	({ message_id: 'm1', chat_id: 'c1', role: 'assistant', created_at: 100, content: 'hello', status: 'synced', ...extra }) as Message;

let unregister: (() => void) | null = null;
beforeEach(() => {
	seen.length = 0;
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => unregister?.());

describe('shared persist unit', () => {
	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('refuses a binding without the persist exports', () => {
		const channel = new MessageChannel();
		expect(() => installPersistUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('decides the update and the encrypted-field fill from the unit answer', async () => {
		const before = rustPersistStats.calls;
		const stored = message({ status: 'processing' });
		expect(await rust.rustShouldUpdateMessage(stored, message({ status: 'synced' }))).toBe(true);
		expect(await rust.rustShouldUpdateMessage(message({ status: 'synced' }), message({ status: 'processing' }))).toBe(false);
		expect(await rust.rustSaveDecision(stored, message({ status: 'processing' }), message({ encrypted_content: 'cipher' })))
			.toEqual({ shouldUpdate: false, fillsEncrypted: true });
		expect(await rust.rustShouldUpdateMessages([])).toEqual([]);
		expect(rustPersistStats.calls - before).toBe(3);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('sends only the fields the policy reads', async () => {
		const heavy = message({ status: 'synced', embed_ids: ['a'], encrypted_embed_bundle: 'x'.repeat(1000), unrelated: { deep: true } });
		await rust.rustShouldUpdateMessage(heavy, message({ status: 'delivered' }));
		const sent = JSON.parse(seen[0]).pairs[0];
		expect(Object.keys(sent.existing).sort()).toEqual(['content', 'status']);
		await rust.rustIsSafeToEvictMessage(heavy);
		expect(JSON.parse(seen[1]).messages[0]).toEqual({ status: 'synced' });
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('returns the stored duplicate row the unit selects', async () => {
		const stored = [message({ message_id: 'a', content: 'other' }), message({ message_id: 'b' }), message({ message_id: 'c' })];
		expect(await rust.rustFindContentDuplicate(stored, message({ message_id: 'new' }))).toBe(stored[1]);
		expect(await rust.rustFindContentDuplicate(stored, message({ message_id: 'new', content: 'unique' }))).toBeNull();
		expect(await rust.rustFindContentDuplicate([], message({}))).toBeNull();
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('evicts only confirmed rows and treats a missing row as unsafe', async () => {
		expect(await rust.rustIsSafeToEvictMessage(message({ status: 'synced' }))).toBe(true);
		expect(await rust.rustIsSafeToEvictMessage(message({ status: 'sending' }))).toBe(false);
		expect(await rust.rustIsSafeToEvictMessage(message({ pending_turn_preflight_v1: { a: 1 } }))).toBe(false);
		expect(await rust.rustIsSafeToEvictMessage(undefined)).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('rejects with the fixed protocol code when the binding throws', async () => {
		binding.persist_message_safe_to_evict = () => { throw new Error('boom'); };
		const failures = rustPersistStats.failures;
		await expect(rust.rustIsSafeToEvictMessage(message({}))).rejects.toBeDefined();
		expect(rustPersistStats.failures - failures).toBe(1);
	});
});

describe('shared persist unit: cache and chat-row decisions', () => {
	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('answers window, budget and quota decisions from the unit', async () => {
		const plan = await rustCacheDecisions.windowPlan({ chatId: 'c1', limit: 500, direction: 'before', beforeTimestamp: 90 });
		expect(plan).toMatchObject({ limit: 100, direction: 'before', timestamp: 90, empty: false });
		expect(await rustCacheDecisions.quotaStep({ stage: 'write', canRetry: true, errorName: 'QuotaExceededError' })).toBe('trim_retry');
		expect(await rustCacheDecisions.quotaStep({ stage: 'retry', canRetry: true, errorName: 'AbortError' })).toBe('rethrow');
		expect(await rustCacheDecisions.budgetTarget({ force: false, configuredBytes: 100, quota: 120, usage: 70 })).toEqual({ target: 60, trim: true });
		expect(await rustCacheDecisions.chatsPageSize(500)).toBe(50);
		expect(await rustCacheDecisions.pageConfirmed([message({ status: 'synced' }), undefined])).toBe(false);
		expect(await rustCacheDecisions.pageConfirmed([message({ status: 'synced' })])).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('sends only the page fields the eviction decisions read', async () => {
		await rustCacheDecisions.evictPlan({
			pages: [{ id: 'p1', chat_id: 'c1', page_kind: 'normal', last_accessed_at: 1, message_ids: ['a'], cache_generation: 1, direction: 'latest', cached_at: 9 } as never],
			maxPagesPerChat: 1,
		});
		expect(Object.keys(JSON.parse(seen[seen.length - 1]).pages[0]).sort())
			.toEqual(['cache_generation', 'chat_id', 'id', 'last_accessed_at', 'message_ids', 'page_kind']);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('merges draft fields as a patch and keeps explicitly undefined fields apart', async () => {
		const decision = await rustChatRowDecisions.draftMerge({
			chatId: 'c1',
			current: { chat_id: 'c1', draft_v: 2, cleared_draft_v: 0, team_id: null, heavy: 'x'.repeat(500) } as never,
			fields: { draft_v: 3, encrypted_draft_md: 'cipher', encrypted_draft_preview: undefined, cleared_draft_v: 1 },
			missingRow: null,
		});
		expect(decision).toEqual({
			action: 'put',
			patch: { draft_v: 3, encrypted_draft_md: 'cipher', cleared_draft_v: 1 },
			undefinedKeys: ['encrypted_draft_preview'],
		});
		const sent = JSON.parse(seen[seen.length - 1]);
		expect(sent.current).toEqual({ chat_id: 'c1', draft_v: 2, cleared_draft_v: 0, team_id: null });
		expect(sent.undefinedKeys).toEqual(['encrypted_draft_preview']);
	});

	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('decides chat defaults, candidate keys and the keyless draft shell from the unit', async () => {
		expect(await rustChatRowDecisions.chatDefaults({ updated_at: 7 }, 99)).toEqual({
			draft_v: 0, title_v: 0, messages_v: 0, last_edited_overall_timestamp: 7,
		});
		expect(await rustChatRowDecisions.candidateKeys(['a'], 'a')).toBeNull();
		expect(await rustChatRowDecisions.candidateKeys(['a'], 'b')).toEqual(['a', 'b']);
		expect(await rustChatRowDecisions.keylessDraftOnly({ messages_v: 0, draft_v: 1, encrypted_draft_md: 'c' }, null)).toBe(true);
	});
});
