/**
 * Unit tests for the client-authored embed revision commit: the exact
 * compare-and-swap payload (revision, stored or source hash, encrypted head and
 * history rows), the local cache written only after a committed receipt, and
 * conflicts / rejections that leave local state untouched.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const order: string[] = [];
const sent: Array<{ type: string; payload: Record<string, unknown> }> = [];
const listeners = new Map<string, (payload: unknown) => void>();
let reply: (request: Record<string, unknown>) => Record<string, unknown>;
let rawEntry: Record<string, unknown> | null;
let versions: { readonly: boolean; current_version: number; versions: Array<{ version_number: number; has_snapshot: boolean }> };

const prepareVersionRestoreUpdate = vi.fn(async () => { order.push('local-head'); return { updated: true }; });
const storeEmbedDiff = vi.fn(async (row: { version_number: number }) => { order.push(`local-diff-v${row.version_number}`); });
const dispatchEvent = vi.fn();

vi.mock('../embedStore', () => ({
	embedStore: {
		getRawEntry: vi.fn(async () => rawEntry),
		getEmbedKey: vi.fn(async () => new Uint8Array([1])),
		prepareVersionRestoreUpdate: (...args: unknown[]) => prepareVersionRestoreUpdate(...(args as [])),
	}
}));
vi.mock('../db', () => ({ chatDB: { getChat: vi.fn(async () => ({ chat_id: 'chat-1', team_id: null })) } }));
vi.mock('../embedDiffStore', () => ({
	buildUnifiedDiff: (before: string, after: string, from: number, to: number) => `patch:${from}->${to}:${before}=>${after}`,
	fetchEmbedVersions: vi.fn(async () => versions),
	storeEmbedDiff: (row: { version_number: number }) => storeEmbedDiff(row),
}));
vi.mock('../encryption/MetadataEncryptor', () => ({
	encryptWithEmbedKey: vi.fn(async (plain: string) => `enc(${plain})`),
}));
vi.mock('../canonicalEmbedWriteCoordinator', () => ({
	withCanonicalEmbedWrite: (_id: string, run: () => Promise<unknown>) => run(),
}));
vi.mock('../websocketService', () => ({
	webSocketService: {
		on: (type: string, handler: (payload: unknown) => void) => listeners.set(type, handler),
		off: (type: string) => listeners.delete(type),
		addEventListener: vi.fn(),
		removeEventListener: vi.fn(),
		sendMessage: vi.fn(async (type: string, payload: Record<string, unknown>) => {
			order.push('send');
			sent.push({ type, payload });
			const result = reply(payload);
			queueMicrotask(() => listeners.get('commit_chat_diagram_revision_result')?.({ request_id: payload.request_id, ...result }));
		}),
	}
}));
vi.mock('../chatSyncService', () => ({ chatSyncService: { dispatchEvent: (event: Event) => dispatchEvent(event) } }));
vi.mock('../../message_parsing/utils', () => ({
	computeSHA256: vi.fn(async (value: string) => (value.length.toString(16).padStart(2, '0')).repeat(32)),
}));

import { commitEmbedUserRevision, EmbedUserRevisionError } from '../embedUserRevision';

const STORED_HASH = 'a'.repeat(64);
const ORIGINAL = '<deck title="A"></deck>';
const EDITED = '<deck title="Launch"></deck>';
const sha = (value: string) => value.length.toString(16).padStart(2, '0').repeat(32);

function input(overrides: Partial<Parameters<typeof commitEmbedUserRevision>[0]> = {}) {
	return {
		embedId: 'deck-1', chatId: 'chat-1',
		current: { type: 'deck', slides_markup: ORIGINAL, version_number: 1, status: 'finished' },
		sourceField: 'slides_markup', originalSource: ORIGINAL, editedSource: EDITED,
		noun: 'deck', expectedHash: 'stored-head' as const,
		...overrides,
	};
}

beforeEach(() => {
	order.length = 0;
	sent.length = 0;
	listeners.clear();
	prepareVersionRestoreUpdate.mockClear();
	storeEmbedDiff.mockClear();
	dispatchEvent.mockClear();
	rawEntry = { version_number: 1, hashed_chat_id: 'hc', content_hash: STORED_HASH };
	versions = { readonly: false, current_version: 1, versions: [{ version_number: 1, has_snapshot: true }] };
	reply = (request) => ({ status: 'committed', current_revision: (request.expected_revision as number) + 1,
		current_content_hash: (request.head as { content_hash: string }).content_hash });
});

describe('commitEmbedUserRevision', () => {
	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('commits v1 -> v2 against the stored head hash, then writes the local cache', async () => {
		await expect(commitEmbedUserRevision(input())).resolves.toEqual({ version: 2, cacheSynchronized: true });
		expect(sent).toHaveLength(1);
		const { type, payload } = sent[0];
		expect(type).toBe('commit_chat_diagram_revision');
		expect(payload).toMatchObject({
			embed_id: 'deck-1', chat_id: 'chat-1', expected_revision: 1, expected_content_hash: STORED_HASH,
			head: { content_hash: sha(EDITED), status: 'finished' },
			history_rows: [{ version_number: 2, encrypted_patch: `enc(patch:1->2:${ORIGINAL}=>${EDITED})` }],
		});
		expect(payload).not.toHaveProperty('team_id');
		expect(String((payload.head as { encrypted_content: string }).encrypted_content)).toContain('Launch');
		expect(order).toEqual(['send', 'local-head', 'local-diff-v2']);
		expect(dispatchEvent).toHaveBeenCalledTimes(1);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('uses the source hash when asked to (diagram contract) and seeds a missing v1 snapshot', async () => {
		versions = { readonly: false, current_version: 1, versions: [] };
		await commitEmbedUserRevision(input({ expectedHash: 'source' }));
		const rows = sent[0].payload.history_rows as Array<Record<string, unknown>>;
		expect(sent[0].payload.expected_content_hash).toBe(sha(ORIGINAL));
		expect(rows.map((row) => row.version_number)).toEqual([1, 2]);
		expect(rows[0].encrypted_snapshot).toBe(`enc(${ORIGINAL})`);
		expect(order).toEqual(['send', 'local-head', 'local-diff-v1', 'local-diff-v2']);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('falls back to the source hash when the cached head has no stored hash', async () => {
		rawEntry = { version_number: 1, hashed_chat_id: 'hc' };
		await commitEmbedUserRevision(input());
		expect(sent[0].payload.expected_content_hash).toBe(sha(ORIGINAL));
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('adds a full checkpoint on every 32nd version', async () => {
		rawEntry = { version_number: 31, hashed_chat_id: 'hc', content_hash: STORED_HASH };
		versions = { readonly: false, current_version: 31, versions: [] };
		await commitEmbedUserRevision(input({ current: { slides_markup: ORIGINAL, version_number: 31 } }));
		const rows = sent[0].payload.history_rows as Array<Record<string, unknown>>;
		expect(rows).toHaveLength(1);
		expect(rows[0]).toMatchObject({ version_number: 32, encrypted_snapshot: `enc(${EDITED})` });
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('refuses a stale edit (server conflict) without touching the local cache', async () => {
		reply = () => ({ status: 'conflict', current_revision: 2, current_content_hash: 'b'.repeat(64) });
		const error = await commitEmbedUserRevision(input()).catch((caught: unknown) => caught);
		expect(error).toBeInstanceOf(EmbedUserRevisionError);
		expect((error as EmbedUserRevisionError).failure).toBe('conflict');
		expect(order).toEqual(['send']);
		expect(dispatchEvent).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('surfaces a server rejection code and writes nothing locally', async () => {
		reply = () => ({ status: 'rejected', code: 'diagram_access_denied' });
		const error = await commitEmbedUserRevision(input()).catch((caught: unknown) => caught);
		expect((error as EmbedUserRevisionError).failure).toBe('rejected');
		expect((error as Error).message).toBe('diagram_access_denied');
		expect(order).toEqual(['send']);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('does not send when the local head is behind the server history', async () => {
		versions = { readonly: false, current_version: 2, versions: [] };
		const error = await commitEmbedUserRevision(input()).catch((caught: unknown) => caught);
		expect((error as EmbedUserRevisionError).failure).toBe('conflict');
		expect((error as Error).message).toBe('The deck changed on another device. Reload before editing.');
		expect(sent).toHaveLength(0);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('does not send for a read-only embed or an unchanged source', async () => {
		await expect(commitEmbedUserRevision(input({ editedSource: ORIGINAL }))).resolves.toEqual({ version: 1, cacheSynchronized: true });
		versions = { readonly: true, current_version: 1, versions: [] };
		const error = await commitEmbedUserRevision(input()).catch((caught: unknown) => caught);
		expect((error as EmbedUserRevisionError).failure).toBe('readonly');
		expect(sent).toHaveLength(0);
	});

	// contract-test: supporting surface=gui.web assertions=slides.editor.save-checked-version,chats.persistence.client-encrypted
	it('keeps a committed save successful when the local cache write fails', async () => {
		prepareVersionRestoreUpdate.mockImplementationOnce(async () => ({ updated: false }));
		await expect(commitEmbedUserRevision(input())).resolves.toEqual({ version: 2, cacheSynchronized: false });
		expect(dispatchEvent).not.toHaveBeenCalled();
	});
});
