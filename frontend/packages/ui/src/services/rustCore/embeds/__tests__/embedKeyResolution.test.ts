// Worker-side embed key resolution (embedKeyResolution.ts): the IndexedDB
// adapter feeds `embed_keys` rows and legacy `parent_embed_id` to the Rust
// session, returns only opened fields or typed per-row codes, and zeroes the
// page-validated chat key it installs.
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createEmbedKeyHandlers, type EmbedKeyResolverPort } from '../embedKeyResolution';
import { UnitRefusal } from '../../host/unitPort';

const SIGNAL = new AbortController().signal;

// The shared test setup stubs `crypto.subtle.digest`; the real SHA-256 keeps the hashed embed ids distinct.
beforeEach(() => {
	vi.mocked(crypto.subtle.digest).mockImplementation(async (_algorithm, data) => {
		const bytes = createHash('sha256').update(new Uint8Array(data as ArrayBuffer)).digest();
		return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
	});
});
afterEach(() => vi.mocked(crypto.subtle.digest).mockReset());

async function sha256Hex(value: string): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
	return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function request<T>(result: T) {
	const req: { result: T; onsuccess?: () => void; onerror?: () => void; error: null } = { result, error: null };
	queueMicrotask(() => req.onsuccess?.());
	return req;
}

function fakeDb(keyRows: Record<string, unknown>[], entries: Record<string, Record<string, unknown>>) {
	return {
		transaction() {
			return {
				objectStore(name: string) {
					return {
						index: () => ({ getAll: (hash: string) => request(name === 'embed_keys' ? keyRows.filter((row) => row.hashed_embed_id === hash) : []) }),
						get: (ref: string) => request(entries[ref])
					};
				}
			};
		}
	} as unknown as IDBDatabase;
}

const rust = async <T>(call: () => T | Promise<T>): Promise<T> => {
	try {
		return await call();
	} catch (error) {
		throw new UnitRefusal(typeof error === 'string' ? error : 'embed_write_failed');
	}
};

function session(states: Record<string, unknown>) {
	const calls: string[] = [];
	const installed: Uint8Array[] = [];
	const loaded = new Set<string>();
	const port: EmbedKeyResolverPort = {
		install_chat_key(chatId, key) { calls.push(`install:${chatId}`); installed.push(new Uint8Array(key)); },
		async resolve_embed_key(embedId, _hash, rowsJson) {
			calls.push(`resolve:${embedId}:${(JSON.parse(rowsJson) as unknown[]).length}`);
			const state = states[embedId] ?? { state: 'no_wrappers' };
			if ((state as { state: string }).state === 'loaded') loaded.add(embedId);
			return JSON.stringify(state);
		},
		inherit_parent_embed_key(child, parent) { calls.push(`inherit:${child}<-${parent}`); return loaded.has(parent) && Boolean(loaded.add(child)); },
		derive_early_parent_key(embedId, chatId) { calls.push(`derive:${embedId}:${chatId}`); return true; },
		async open_embed_fields(embedId, content) {
			if (!loaded.has(embedId)) throw 'embed_key_unavailable';
			return { content: `plain:${content}`, content_failed: false, type: null, text_preview: null };
		}
	};
	return { port, calls, installed };
}

const row = (embedId: string) => ({ embedId, hashedChatId: 'hc', encrypted_content: 'c', encrypted_type: null, encrypted_text_preview: null });

describe('embed key resolution in the Worker', () => {
	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('opens rows with Worker-resolved keys, inherits legacy parents and reports pending chats', async () => {
		const keyRows = [{ hashed_embed_id: await sha256Hex('wrapped'), key_type: 'master' }, { hashed_embed_id: await sha256Hex('parent'), key_type: 'chat' }];
		const db = fakeDb(keyRows, { 'embed:child': { parent_embed_id: 'parent' }, 'embed:orphan': {} });
		const fake = session({ wrapped: { state: 'loaded' }, parent: { state: 'loaded' }, locked: { state: 'unavailable', pending_chat_hashes: ['h1'] } });
		const handlers = createEmbedKeyHandlers(() => fake.port, async () => db, rust);
		const results = await handlers.openStoredRows({ rows: [row('wrapped'), row('child'), row('locked'), row('orphan')] }, SIGNAL);
		expect(results).toEqual([
			{ ok: true, fields: { content: 'plain:c', content_failed: false, type: null, text_preview: null } },
			{ ok: true, fields: { content: 'plain:c', content_failed: false, type: null, text_preview: null } },
			{ ok: false, code: 'embed_key_unavailable', pendingChatHashes: ['h1'] },
			{ ok: false, code: 'embed_key_unavailable', pendingChatHashes: [] }
		]);
		expect(fake.calls).toContain('resolve:wrapped:1');
		expect(fake.calls).toContain('inherit:child<-parent');
		expect(JSON.stringify(results)).not.toMatch(/key_type|encrypted_embed_key/);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('installs and zeroes the validated chat key and refuses malformed requests', async () => {
		const fake = session({});
		const handlers = createEmbedKeyHandlers(() => fake.port, async () => fakeDb([], {}), rust);
		const key = new Uint8Array(32).fill(9);
		await handlers.adoptPageChatKey({ chatId: 'chat-1', key }, SIGNAL);
		expect(fake.installed[0].every((byte) => byte === 9)).toBe(true);
		expect(key.every((byte) => byte === 0)).toBe(true);
		const missing = new Uint8Array(32).fill(9);
		await expect(handlers.adoptPageChatKey({ chatId: '', key: missing }, SIGNAL)).rejects.toMatchObject({ code: 'embed_write_bad_chat_id' });
		expect(missing.every((byte) => byte === 0)).toBe(true);
		await expect(handlers.deriveEarlyKey({ embedId: 'e', chatId: 'chat-1' }, SIGNAL)).resolves.toBe(true);
		await expect(handlers.openStoredRows({ rows: [{ embedId: '' }] } as never, SIGNAL)).rejects.toMatchObject({ code: 'embed_write_bad_embed_id' });
	});
});
