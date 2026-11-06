// contract-test-file: tooling
// Rust web embeds on the shared Rust core Worker: the pre-bind `embedData`
// unit (field decryption next to the realm's single binding, per-row codes,
// key zeroing, close frame) and its coalescing page client, and the bound
// `embedWrite` unit (init, Worker-side persistence without local wrappers,
// unbind disposal). The real router and installers run in-process with
// synthetic bindings.
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EMBED_UNIT_CLOSE, isEmbedUnitClose, type EmbedWriteProtocol } from '../embedDataProtocol';
import { createEmbedDataHandlers, installEmbedDataUnit, type EmbedDataBinding } from '../embedDataUnit';
import { EmbedDataClient, openedEmbedField, openStoredEmbedContent, RustEmbedDataError } from '../embedDataClient';
import { createEmbedWriteHandlers, createEmbedWriteUnitInstaller, type EmbedWriteBinding } from '../embedWriteUnit';
import { openEmbedWriteClient } from '../embedWriteClient';
import type { EmbedWriterPort, PreparedEmbedWrite, StreamCompletionInput } from '../../embedWriteAdapter';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../../host/sharedCoreRegistry';
import { createSharedWorkerRouter, type UnitInstaller } from '../../host/sharedWorkerProtocol';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';
const fixture = JSON.parse(readFileSync(new URL(
	'../../../../../../../../packages/openmates-rust/tests/crypto_fixtures/ts_embed_writes.json', import.meta.url), 'utf8')) as {
	finalized: Array<{ input: StreamCompletionInput; expected: PreparedEmbedWrite }>;
};

function dataBinding(): EmbedDataBinding & { keys: Uint8Array[] } {
	const keys: Uint8Array[] = [];
	return {
		keys,
		async embed_open_row_fields(key, content, type, preview) {
			keys.push(key);
			if (content === 'bad-key') throw 'invalid';
			if (content === 'internal') throw new Error('Internal: something long and private');
			return { content: content ? `plain:${content}` : null, content_failed: false, type: type ?? null, text_preview: preview ?? null };
		}
	};
}

function sharedCore(installers: Record<string, UnitInstaller>, binding: unknown) {
	const workers: { posted: Record<string, unknown>[] }[] = [];
	const core = createSharedCoreClient(() => {
		const listeners: ((event: Event) => void)[] = [];
		const router = createSharedWorkerRouter({
			installers,
			loadBinding: async () => binding,
			reply: (reply) => queueMicrotask(() => { for (const listener of listeners) listener({ data: reply } as MessageEvent); })
		});
		const state = { posted: [] as Record<string, unknown>[] };
		workers.push(state);
		const endpoint: SharedWorkerEndpoint = {
			postMessage(message, transfer) { state.posted.push(message as Record<string, unknown>); void router.handle(message, transfer as MessagePort[]); },
			addEventListener(type, listener) { if (type === 'message') listeners.push(listener); },
			terminate() { /* in-process */ }
		};
		return endpoint;
	});
	return { core, workers, unregister: registerSharedRustCore(core) };
}

let cleanup: (() => void) | null = null;
afterEach(() => { cleanup?.(); cleanup = null; });

const SIGNAL = new AbortController().signal;
const key = () => new Uint8Array(32).fill(7);
const item = (content: string | null) => ({ key: key(), encrypted_content: content, encrypted_type: 't', encrypted_text_preview: null });

describe('embedStore read hooks', () => {
	it('run the TS decrypt when the Rust crypto arm is inactive (measurement opt-out)', async () => {
		const row = { encrypted_content: 'c', encrypted_type: 't' };
		await expect(openStoredEmbedContent(key(), row, async () => 'ts-content')).resolves.toBe('ts-content');
		await expect(openedEmbedField(row, 'type', 't', async (data) => `ts:${data}`)).resolves.toBe('ts:t');
	});
});

describe('embedData unit', () => {
	it('accepts only the exact close frame', () => {
		expect(isEmbedUnitClose(EMBED_UNIT_CLOSE)).toBe(true);
		expect(isEmbedUnitClose({ embedUnitClose: 1, id: 1 })).toBe(false);
		expect(isEmbedUnitClose({ v: 1, id: 1, type: 'request', op: 'openFields' })).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('opens each row, answers per-row codes and zeroes every key', async () => {
		const binding = dataBinding();
		const handlers = createEmbedDataHandlers(binding);
		const results = await handlers.openFields({ items: [item('a'), item('bad-key'), item('internal'), item(null)] }, SIGNAL);
		expect(results).toEqual([
			{ ok: true, fields: { content: 'plain:a', content_failed: false, type: 't', text_preview: null } },
			{ ok: false, code: 'invalid' },
			{ ok: false, code: 'embed_data_failed' },
			{ ok: true, fields: { content: null, content_failed: false, type: 't', text_preview: null } }
		]);
		expect(binding.keys.every((bytes) => bytes.every((byte) => byte === 0))).toBe(true);
	});

	it('refuses malformed or oversized requests and malformed Rust results', async () => {
		const handlers = createEmbedDataHandlers(dataBinding());
		await expect(handlers.openFields({ items: [{ key: 'k' }] } as never, SIGNAL)).rejects.toMatchObject({ code: 'embed_data_bad_request' });
		await expect(handlers.openFields({ items: Array.from({ length: 257 }, () => item('a')) }, SIGNAL)).rejects.toMatchObject({ code: 'embed_data_bad_request' });
		const broken = createEmbedDataHandlers({ embed_open_row_fields: async () => ({ content: 1 }) });
		await expect(broken.openFields({ items: [item('a')] }, SIGNAL)).rejects.toMatchObject({ code: 'embed_data_protocol' });
	});

	it('refuses to install without the Rust export or with extra ports', () => {
		const { port1, port2 } = new MessageChannel();
		const context = { ports: [port1], generation: null, principal: null, signal: new AbortController().signal };
		expect(() => installEmbedDataUnit({ ...context, binding: {} })).toThrow('unavailable');
		expect(() => installEmbedDataUnit({ ...context, ports: [port1, port2], binding: dataBinding() })).toThrow('unavailable');
		port1.close();
		port2.close();
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('page client opens pre-bind, coalesces a task into one request and rejects failed rows', async () => {
		const binding = dataBinding();
		const shared = sharedCore({ embedData: installEmbedDataUnit }, binding);
		cleanup = shared.unregister;
		const client = new EmbedDataClient(shared.core);
		const pageKey = key();
		const [first, second, third] = await Promise.allSettled([
			client.openFields(pageKey, { encrypted_content: 'x', encrypted_type: 't' }),
			client.openFields(pageKey, { encrypted_content: 'bad-key' }),
			client.openFields(pageKey, { encrypted_content: 'y', encrypted_text_preview: 'p' })
		]);
		expect(first).toEqual({ status: 'fulfilled', value: { content: 'plain:x', content_failed: false, type: 't', text_preview: null } });
		expect(second.status === 'rejected' && second.reason).toBeInstanceOf(RustEmbedDataError);
		expect(second.status === 'rejected' && (second.reason as RustEmbedDataError).code).toBe('invalid');
		expect(third).toMatchObject({ status: 'fulfilled', value: { content: 'plain:y', text_preview: 'p' } });
		expect(client.stats).toEqual({ requests: 1, rows: 3, failures: 0 });
		expect(pageKey.every((byte) => byte === 7)).toBe(true);
		expect(shared.workers).toHaveLength(1);
		expect(shared.workers[0].posted.find((message) => message.type === 'open')).toMatchObject({ ns: 'embedData', generation: null });
		expect(shared.core.busy).toBe(false);
		client.close();
	});
});

function fakeDb() {
	const stores: Record<string, Map<string, Record<string, unknown>>> = { embeds: new Map(), embed_keys: new Map(), embed_diffs: new Map() };
	const keyPaths: Record<string, string> = { embeds: 'contentRef', embed_keys: 'id', embed_diffs: 'id' };
	const db = {
		transaction(names: string | string[]) {
			const tx: Record<string, unknown> & { oncomplete?: () => void } = {
				objectStore(name: string) {
					if (!([] as string[]).concat(names).includes(name)) throw new Error(`store ${name} not in scope`);
					return { put(value: Record<string, unknown>) { stores[name].set(String(value[keyPaths[name]]), structuredClone(value)); } };
				}
			};
			queueMicrotask(() => tx.oncomplete?.());
			return tx;
		}
	};
	return { db: db as unknown as IDBDatabase, stores };
}

function writer(prepared: PreparedEmbedWrite, freed: { count: number }): EmbedWriteBinding {
	const unused = () => { throw new Error('unused'); };
	class Writer implements EmbedWriterPort {
		adopt_chat_key = unused; adopt_embed_key_wrapper = unused; adopt_child_embed_key = unused;
		has_chat_key = () => true; has_embed_key = () => false;
		prepare_stream_completion = async () => JSON.stringify(prepared);
		prepare_processing_update = unused; encrypt_history_row = unused; reconcile_sealed_history = unused;
		adopt_canonical_row = unused; verify_canonical_head = unused; prepare_restore = unused; reconstruct_versions = unused;
		forget_chat = unused; clear = () => undefined; free = () => { freed.count++; };
	}
	return { BrowserEmbedWriter: Writer as unknown as EmbedWriteBinding['BrowserEmbedWriter'] };
}

async function masterKey(extractable = false): Promise<CryptoKey> {
	return webcrypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, extractable, ['wrapKey', 'unwrapKey']) as unknown as Promise<CryptoKey>;
}

describe('embedWrite unit', () => {
	const sample = fixture.finalized[0];

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('persists the Rust-prepared entry and wrappers in the Worker and never returns local wrappers', async () => {
		const { db, stores } = fakeDb();
		const { handlers } = createEmbedWriteHandlers(writer(sample.expected, { count: 0 }), async () => db);
		await handlers.init({ masterKey: await masterKey() }, SIGNAL);
		const persisted = await handlers.prepareStreamCompletion({ payload: sample.input, normalizedType: `normalized:${sample.input.type}` }, SIGNAL);
		expect(persisted).not.toHaveProperty('local_key_wrappers');
		expect(persisted.local_entry).toEqual(sample.expected.local_entry);
		expect(stores.embeds.get(sample.expected.local_entry.contentRef)?.type).toBe(`normalized:${sample.input.type}`);
		expect(stores.embed_keys.size).toBe(sample.expected.local_key_wrappers.length);
		expect(handlers.hasKeys({ chatId: 'c', embedId: 'e' }, SIGNAL)).toEqual({ chat: true, embed: false });
	});

	it('refuses extractable or repeated init, calls before init, and a type mismatch', async () => {
		const { db } = fakeDb();
		const { handlers, dispose } = createEmbedWriteHandlers(writer(sample.expected, { count: 0 }), async () => db);
		expect(() => handlers.hasKeys({ chatId: 'c', embedId: null }, SIGNAL)).toThrow(expect.objectContaining({ code: 'embed_write_not_initialized' }));
		await expect(handlers.init({ masterKey: await masterKey(true) }, SIGNAL)).rejects.toMatchObject({ code: 'embed_write_bad_master_key' });
		await handlers.init({ masterKey: await masterKey() }, SIGNAL);
		await expect(handlers.init({ masterKey: await masterKey() }, SIGNAL)).rejects.toMatchObject({ code: 'embed_write_already_initialized' });
		await expect(handlers.prepareStreamCompletion({ payload: { ...sample.input, type: 'other' }, normalizedType: 'other' }, SIGNAL))
			.rejects.toMatchObject({ code: 'embed_write_type_mismatch' });
		dispose();
		expect(() => handlers.hasKeys({ chatId: 'c', embedId: null }, SIGNAL)).toThrow(expect.objectContaining({ code: 'embed_write_not_initialized' }));
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('opens only in a bound generation and frees the Rust session on unbind', async () => {
		const freed = { count: 0 };
		const { db } = fakeDb();
		const closed = vi.fn();
		const install = createEmbedWriteUnitInstaller(() => ({ open: async () => db, close: closed }));
		const shared = sharedCore({ embedWrite: install }, writer(sample.expected, freed));
		cleanup = shared.unregister;
		await expect(openEmbedWriteClient(shared.core, await masterKey())).rejects.toThrow('not_bound');
		await shared.core.bind(PRINCIPAL);
		const client = await openEmbedWriteClient(shared.core, await masterKey());
		const persisted = await client.unit.request('prepareStreamCompletion', { payload: sample.input, normalizedType: sample.input.type });
		expect(persisted).not.toHaveProperty('local_key_wrappers');
		await shared.core.unbind();
		await vi.waitFor(() => expect(freed.count).toBe(1));
		expect(closed).toHaveBeenCalledTimes(1);
		const after: EmbedWriteProtocol['hasKeys']['request'] = { chatId: 'c', embedId: null };
		expect(client.unit.closed).toBe(true);
		await expect(client.unit.request('hasKeys', after)).rejects.toMatchObject({ code: 'unit_unbound' });
		client.close();
		await expect(client.unit.request('hasKeys', after)).rejects.toMatchObject({ code: 'unit_unbound' });
	});
});
