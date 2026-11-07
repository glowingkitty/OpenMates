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
