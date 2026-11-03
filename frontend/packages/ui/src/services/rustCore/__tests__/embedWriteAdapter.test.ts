// Rust embed write adapter: sequencing against a fake WASM port, the thin
// IndexedDB adapter against a minimal fake database, and drift checks that the
// TypeScript sources still produce the vectors the Rust engine is tested on.
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import {
	PARENT_KEY_PENDING,
	persistStreamedHistory,
	prepareStreamCompletion,
	type EmbedHistoryIO,
	type EmbedWriteFunctions,
	type EmbedWriterPort,
	type EncryptedDiffRow,
	type PreparedEmbedWrite,
	type StreamCompletionInput
} from '../embedWriteAdapter';
import { embedKeyStorageId, getEmbedDiffs, persistPreparedEmbedWrite } from '../embedWriteIdb';
import { buildUnifiedDiff } from '../../../utils/embedUnifiedDiff';
import { normalizeToUnixSeconds } from '../../timestampUtils';
import { isTerminalStatus, normalizeEmbedStatus, validateEmbedTransition } from '../../embedStateMachine';

type Fixture = {
	finalized: Array<{ input: StreamCompletionInput; expected: PreparedEmbedWrite; embed_key_b64: string }>;
	fields: Array<{ plaintext: string; aad: string | null; key_b64: string; ciphertext: string }>;
	history: { input: Array<Record<string, unknown>>; rows: Array<{ local_row: EncryptedDiffRow } | null> };
	unified_diffs: Array<{ current: string; restored: string; current_version: number; new_version: number; patch: string }>;
	status: { transitions: Array<[string, string, boolean]>; normalize: Array<[unknown, string]>; terminal: Array<[string, boolean]> };
};
const fixture = JSON.parse(
	readFileSync(
		new URL('../../../../../../../packages/openmates-rust/tests/crypto_fixtures/ts_embed_writes.json', import.meta.url),
		'utf8'
	)
) as Fixture;
const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

function fakePort(overrides: Partial<EmbedWriterPort> = {}): EmbedWriterPort {
	const unused = () => {
		throw new Error('unused');
	};
	return {
		adopt_chat_key: unused,
		adopt_embed_key_wrapper: unused,
		adopt_child_embed_key: unused,
		has_chat_key: () => true,
		has_embed_key: () => true,
		prepare_stream_completion: unused,
		prepare_processing_update: unused,
		encrypt_history_row: unused,
		reconcile_sealed_history: unused,
		adopt_canonical_row: unused,
		verify_canonical_head: unused,
		prepare_restore: unused,
		reconstruct_versions: unused,
		forget_chat: unused,
		clear: unused,
		...overrides
	};
}

describe('prepareStreamCompletion', () => {
	const child = fixture.finalized[2];

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('retries a pending parent key with the legacy backoff, then succeeds', async () => {
		let calls = 0;
		const port = fakePort({
			prepare_stream_completion: async () => {
				if (++calls < 3) throw PARENT_KEY_PENDING;
				return JSON.stringify(child.expected);
			}
		});
		const sleeps: number[] = [];
		const prepared = await prepareStreamCompletion(port, child.input, async (ms) => void sleeps.push(ms));
		expect(prepared).toEqual(child.expected);
		expect(sleeps).toEqual([100, 200]);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('gives up after five retries and never retries other failures', async () => {
		const sleeps: number[] = [];
		const pending = fakePort({ prepare_stream_completion: async () => Promise.reject(PARENT_KEY_PENDING) });
		await expect(prepareStreamCompletion(pending, child.input, async (ms) => void sleeps.push(ms))).rejects.toBe(PARENT_KEY_PENDING);
		expect(sleeps).toEqual([100, 200, 400, 800, 1600]);
		const cryptoFailure = fakePort({ prepare_stream_completion: async () => Promise.reject('crypto') });
		const sleep = vi.fn(async () => undefined);
		await expect(prepareStreamCompletion(cryptoFailure, child.input, sleep)).rejects.toBe('crypto');
		expect(sleep).not.toHaveBeenCalled();
	});
});

function historyIO(canonical: Map<number, { status: number; body: unknown }>, conflict = false) {
	const stored: EncryptedDiffRow[] = [];
	const sent: Array<Record<string, unknown>> = [];
	const io: EmbedHistoryIO = {
		readCanonical: async (_embedId, version) => canonical.get(version) ?? { status: 404, body: { detail: 'not_found' } },
		getLocalDiffs: async () => [],
		storeDiff: async (row) => void stored.push(row),
		sendDiff: async (payload) => {
			sent.push(payload);
			if (conflict) throw Object.assign(new Error('conflict'), { code: 'embed_diff_conflict' });
		}
	};
	return { io, stored, sent };
}
const fns: EmbedWriteFunctions = {
	embed_classify_canonical_read: (status, body, version, durable) => {
		if (status === 404) return 'absent';
		if (status === 409 && (durable || (version === 1 && body && JSON.parse(body).detail === 'snapshot_required'))) return 'absent';
		if (status >= 200 && status < 300) return 'present';
		throw 'embed_history_read_failed';
	},
	embed_history_head_version: (rows, embedId) => {
		const versions = (JSON.parse(rows) as Array<{ embed_id: string; version_number: number }>)
			.filter((r) => r.embed_id === embedId && r.version_number > 0)
			.map((r) => r.version_number);
		return versions.length ? Math.max(...versions) : undefined;
	}
};

describe('persistStreamedHistory', () => {
	const rows = fixture.history.input.slice(0, 3);
	const embedId = rows[0].embed_id as string;
	const localRows = fixture.history.rows.slice(0, 3).map((r) => r!.local_row);
	const options = { embedId, declaredVersion: 3, hashedUserId: 'h', sealedRootRevision: false, durableHead: true };

	// contract-test: supporting surface=gui.web assertions=storage.versions.metadata-and-payload
	it('ordinary path stores then sends each non-canonical row', async () => {
		const { io, stored, sent } = historyIO(new Map());
		const port = fakePort({
			encrypt_history_row: (_id, row) => {
				const version = (JSON.parse(row) as { version_number: number }).version_number;
				return JSON.stringify({ local_row: localRows[version - 1], server_payload: { version_number: version } });
			}
		});
		await persistStreamedHistory(port, fns, io, rows, options);
		expect(stored).toEqual(localRows);
		expect(sent.map((p) => p.version_number)).toEqual([1, 2, 3]);
	});

	// contract-test: supporting surface=gui.web assertions=storage.versions.metadata-and-payload
	it('adopts canonical rows instead of re-sending, including after a conflict', async () => {
		const canonical = new Map([[1, { status: 200, body: { rows: [] } }]]);
		const { io, stored, sent } = historyIO(canonical, true);
		const adopted: number[] = [];
		const port = fakePort({
			adopt_canonical_row: (_id, _page, row) => {
				const version = (JSON.parse(row) as { version_number: number }).version_number;
				adopted.push(version);
				return JSON.stringify(localRows[version - 1]);
			},
			encrypt_history_row: () => JSON.stringify({ local_row: localRows[1], server_payload: {} })
		});
		await expect(persistStreamedHistory(port, fns, io, rows.slice(0, 2), options)).rejects.toThrow('conflict');
		expect(adopted).toEqual([1]);
		expect(stored).toEqual([localRows[0], localRows[1]]);
		expect(sent).toHaveLength(1);
	});

	// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
	it('sealed path never sends and verifies the durable head', async () => {
		const head = new Map([[3, { status: 200, body: { embed_id: embedId, version_number: 3, rows: localRows } }]]);
		const { io, stored, sent } = historyIO(head);
		const port = fakePort({
			reconcile_sealed_history: () => JSON.stringify(localRows),
			verify_canonical_head: () => JSON.stringify(localRows)
		});
		await persistStreamedHistory(port, fns, io, rows, { ...options, sealedRootRevision: true });
		expect(sent).toHaveLength(0);
		expect(stored).toEqual([...localRows, ...localRows]);
	});
});

/** Minimal synchronous-callback IndexedDB double for the thin adapter. */
function fakeDb() {
	const stores: Record<string, Map<string, Record<string, unknown>>> = {
		embeds: new Map(),
		embed_keys: new Map(),
		embed_diffs: new Map()
	};
	const keyPaths: Record<string, string> = { embeds: 'contentRef', embed_keys: 'id', embed_diffs: 'id' };
	const db = {
		transaction(names: string | string[]) {
			const tx: Record<string, unknown> & { oncomplete?: () => void } = {
				objectStore(name: string) {
					if (!([] as string[]).concat(names).includes(name)) throw new Error(`store ${name} not in scope`);
					const store = stores[name];
					return {
						put(value: Record<string, unknown>) {
							store.set(String(value[keyPaths[name]]), structuredClone(value));
						},
						index(field: string) {
							return {
								getAll(key: string) {
									const request: Record<string, unknown> & { onsuccess?: () => void } = {};
									queueMicrotask(() => {
										request.result = [...store.values()].filter((row) => row[field] === key);
										request.onsuccess?.();
									});
									return request;
								}
							};
						}
					};
				}
			};
			queueMicrotask(() => tx.oncomplete?.());
			return tx;
		}
	};
	return { db: db as unknown as IDBDatabase, stores };
}

describe('embedWriteIdb', () => {
	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('writes the entry and wrappers with the legacy composite ids and normalized type', async () => {
		const { db, stores } = fakeDb();
		const prepared = fixture.finalized[0].expected;
		await persistPreparedEmbedWrite(db, prepared, (type) => `normalized:${type}`);
		const entry = stores.embeds.get(prepared.local_entry.contentRef)!;
		expect(entry.type).toBe('normalized:code');
		expect(entry.encrypted_content).toBe(prepared.local_entry.encrypted_content);
		const ids = [...stores.embed_keys.keys()];
		expect(ids).toEqual(prepared.local_key_wrappers.map(embedKeyStorageId));
		expect(ids[0].endsWith(':master:null')).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('reads revision rows sorted by version', async () => {
		const { db, stores } = fakeDb();
		const rows = fixture.history.rows.filter((r) => r !== null).map((r) => r!.local_row);
		for (const row of [...rows].reverse()) stores.embed_diffs.set(row.id, { ...row });
		expect((await getEmbedDiffs(db, rows[0].embed_id)).map((r) => r.version_number)).toEqual([1, 2, 3]);
	});
});

describe('TypeScript vector drift (ts_embed_writes.json)', () => {
	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('unified diffs, timestamps and status rules still match the vectors', () => {
		for (const c of fixture.unified_diffs) {
			expect(buildUnifiedDiff(c.current, c.restored, c.current_version, c.new_version)).toBe(c.patch);
		}
		expect(normalizeToUnixSeconds(1_789_999_000_123, 7)).toBe(1_789_999_000);
		expect(normalizeToUnixSeconds(0, 7)).toBe(7);
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		for (const [from, to, allowed] of fixture.status.transitions) expect(validateEmbedTransition(from, to)).toBe(allowed);
		warn.mockRestore();
		for (const [value, normalized] of fixture.status.normalize) expect(normalizeEmbedStatus(value)).toBe(normalized);
		for (const [value, terminal] of fixture.status.terminal) expect(isTerminalStatus(value)).toBe(terminal);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it('vector ciphertexts keep the deployed IV||ciphertext||tag layout', async () => {
		for (const field of fixture.fields) {
			const raw = bytes(field.ciphertext);
			const key = await webcrypto.subtle.importKey('raw', bytes(field.key_b64), 'AES-GCM', false, ['decrypt']);
			const params: AesGcmParams = { name: 'AES-GCM', iv: raw.slice(0, 12) };
			if (field.aad) params.additionalData = new TextEncoder().encode(field.aad);
			const plain = await webcrypto.subtle.decrypt(params, key, raw.slice(12));
			expect(new TextDecoder().decode(plain)).toBe(field.plaintext);
		}
	});
});
