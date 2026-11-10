// Recovery delivery of an image child revision on the web shell: the Worker
// receipt handlers (Rust session and IndexedDB replaced by fakes) and the page
// sequence of rustRecoveredChildRevision.ts. Rust decides every receipt; these
// tests prove the glue verifies before it writes, writes a missing version
// through the live child revision path, fetches the page Rust asks for, opens
// rows through the parent's key load and never acknowledges an unverified output.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UnitPortError, UnitRefusal, type UnitPort } from '../../host/unitPort';
import type { EmbedWriteProtocol } from '../embedDataProtocol';
import { createChildRevisionHandlers } from '../childRevisionHandlers';
import type { RevisionRecoveryReceipt } from '../childRevisionProtocol';
import {
	verifyRecoveredRevisionEmbed,
	verifyRecoveredRevisionRow,
	type RecoveredRevisionIO
} from '../rustRecoveredChildRevision';

const idb = vi.hoisted(() => ({ heads: new Map<string, Record<string, unknown>>() }));
vi.mock('../../embedWriteIdb', () => ({
	getEmbedEntry: async (_db: unknown, ref: string) => idb.heads.get(ref) ?? null,
	getEmbedDiffs: async () => [],
	putEmbedDiff: async () => {},
	persistPreparedEmbedWrite: async () => {}
}));

const CHAT = 'chat-1';
const IMAGE = 'image-1';
const PARENT = 'parent-1';
const head = (version: number) => ({ embed_id: IMAGE, parent_embed_id: PARENT, version_number: version, hashed_message_id: 'h-msg-1' });
const sealed = { embed_id: IMAGE, parent_embed_id: PARENT, chat_id: CHAT, message_id: 'msg-2', type: 'image', revision: { base_version: 1 } };
const sealedRow = { embed_id: IMAGE, version_number: 2, snapshot: 'toon-v2', created_at: 1 };
const output = (kind: 'embed' | 'diff', version = 2) => ({ target_chat_id: CHAT, subject_id: IMAGE, output_kind: kind, output_version: version });
const VERIFIED_HEAD: RevisionRecoveryReceipt = { state: 'verified', canonical_digest: 'digest-head', canonical_source: 'head' };
const VERIFIED_ROW: RevisionRecoveryReceipt = { state: 'verified', canonical_digest: 'digest-row', canonical_source: 'version_row' };

function rustCall<T>(call: () => T | Promise<T>): Promise<T> {
	return Promise.resolve().then(call).catch((error) => {
		throw new UnitRefusal(typeof error === 'string' ? error : 'embed_write_failed');
	});
}

/** Page port over the real Worker handlers (no Worker), UnitPortError like the real port. */
function port(session: Record<string, unknown>, binding: Record<string, unknown> = {}): UnitPort<EmbedWriteProtocol> {
	const signal = new AbortController().signal;
	const real = createChildRevisionHandlers({
		session: () => session as never, binding: binding as never, openDb: async () => ({}) as IDBDatabase, rust: rustCall
	}) as unknown as Record<string, (payload: unknown, signal: AbortSignal) => unknown>;
	return {
		async request(op: string, payload: unknown) {
			try {
				return await real[op](payload, signal);
			} catch (error) {
				if (error instanceof UnitRefusal) throw new UnitPortError(error.code);
				throw error;
			}
		}
	} as unknown as UnitPort<EmbedWriteProtocol>;
}

function io(unit: UnitPort<EmbedWriteProtocol>, heads: Array<Record<string, unknown> | null>,
	pages: Record<number, { status: number; body: unknown }> = {}) {
	const calls: string[] = [];
	const value: RecoveredRevisionIO = {
		unit,
		loadKeys: vi.fn(async (_chat: string, embedId: string, parentId: string | null) => { calls.push(`keys:${embedId}:${parentId}`); }),
		readHead: vi.fn(async () => { calls.push('head'); return heads.shift() ?? null; }),
		readVersion: vi.fn(async (_chat: string, _id: string, version: number) => { calls.push(`page:${version}`); return pages[version] ?? { status: 404, body: undefined }; }),
		writeRevision: vi.fn(async () => { calls.push('write'); })
	};
	return { io: value, calls };
}

beforeEach(() => {
	idb.heads.clear();
	idb.heads.set(`embed:${IMAGE}`, head(1));
});

describe('recovered child revision (embed output)', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
	it('writes a version the server does not hold through the live path, then acknowledges the head digest', async () => {
		const receipts: RevisionRecoveryReceipt[] = [{ state: 'not_applied' }, VERIFIED_HEAD];
		const recoveryReceipt = vi.fn(() => JSON.stringify(receipts.shift()));
		const { io: page, calls } = io(port({ child_revision_recovery_receipt: recoveryReceipt }), [head(1), head(2)]);
		await expect(verifyRecoveredRevisionEmbed(page, output('embed'), sealed)).resolves.toEqual({ digest: 'digest-head', source: 'head' });
		expect(calls).toEqual([`keys:${IMAGE}:${PARENT}`, 'head', 'write', 'head']);
		// The Worker hands the stored head (message 1's hash) to Rust; the page never compares message ids.
		const [, , pageArg, storedArg] = recoveryReceipt.mock.calls[0] as unknown as [string, string, string | undefined, string];
		expect(pageArg).toBeUndefined();
		expect(JSON.parse(storedArg)).toEqual(head(1));
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('verifies a superseded version by the bounded-v1 page Rust asks for, without writing', async () => {
		const receipts: RevisionRecoveryReceipt[] = [{ state: 'version_page_required', version: 2 }, VERIFIED_ROW];
		const recoveryReceipt = vi.fn(() => JSON.stringify(receipts.shift()));
		const { io: page, calls } = io(port({ child_revision_recovery_receipt: recoveryReceipt }), [head(3)], { 2: { status: 200, body: { rows: [] } } });
		await expect(verifyRecoveredRevisionEmbed(page, output('embed'), sealed)).resolves.toEqual({ digest: 'digest-row', source: 'version_row' });
		expect(calls).toEqual([`keys:${IMAGE}:${PARENT}`, 'head', 'page:2']);
		expect(JSON.parse((recoveryReceipt.mock.calls as unknown as string[][])[1][2])).toEqual({ rows: [] });
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
	it('never acknowledges when Rust refuses or the write did not reach the server', async () => {
		const refused = io(port({ child_revision_recovery_receipt: () => { throw 'embed_revision_canonical_differs'; } }), [head(2)]);
		await expect(verifyRecoveredRevisionEmbed(refused.io, output('embed'), sealed)).rejects.toMatchObject({ code: 'embed_revision_canonical_differs' });
		expect(refused.calls).not.toContain('write');
		const pending = io(port({ child_revision_recovery_receipt: () => JSON.stringify({ state: 'not_applied' }) }), [head(1), head(1)]);
		await expect(verifyRecoveredRevisionEmbed(pending.io, output('embed'), sealed)).rejects.toMatchObject({ code: 'embed_revision_not_applied' });
		const missing = io(port({}), [null]);
		await expect(verifyRecoveredRevisionEmbed(missing.io, output('embed'), sealed)).rejects.toMatchObject({ code: 'embed_revision_head_missing' });
	});
});

describe('recovered child revision (diff output)', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
	it('loads the parent key from the canonical head and acknowledges the stored row', async () => {
		const rowReceipt = vi.fn(() => JSON.stringify(VERIFIED_ROW));
		const { io: page, calls } = io(port({ child_revision_row_receipt: rowReceipt }), [head(2)], { 2: { status: 200, body: { rows: ['r'] } } });
		await expect(verifyRecoveredRevisionRow(page, output('diff'), sealedRow)).resolves.toEqual({ digest: 'digest-row', source: 'version_row' });
		expect(calls).toEqual(['head', `keys:${IMAGE}:${PARENT}`, 'page:2']);
		expect(JSON.parse((rowReceipt.mock.calls as unknown as string[][])[0][0])).toEqual(sealedRow);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
	it('stays pending while the server has no row N+1 and refuses a row of another version', async () => {
		const rowReceipt = vi.fn((_row: string, _head: string, pageJson?: string) =>
			JSON.stringify(pageJson === undefined ? { state: 'not_applied' } : VERIFIED_ROW));
		const { io: page } = io(port({ child_revision_row_receipt: rowReceipt }), [head(2)]);
		await expect(verifyRecoveredRevisionRow(page, output('diff'), sealedRow)).rejects.toMatchObject({ code: 'embed_revision_not_applied' });
		expect(rowReceipt.mock.calls[0][2]).toBeUndefined();
		const other = io(port({ child_revision_row_receipt: rowReceipt }), [head(2)]);
		await expect(verifyRecoveredRevisionRow(other.io, output('diff', 3), sealedRow)).rejects.toMatchObject({ code: 'embed_revision_head_mismatch' });
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
	it('routes only Rust-classified child rows', async () => {
		const unit = port({}, { embed_child_revision_row: (json: string) => JSON.parse(json).version_number >= 2 });
		await expect(unit.request('isChildRevisionRow', { row: sealedRow })).resolves.toBe(true);
		await expect(unit.request('isChildRevisionRow', { row: { ...sealedRow, version_number: 1 } })).resolves.toBe(false);
		await expect(port({}).request('isChildRevisionRow', { row: sealedRow })).rejects.toMatchObject({ code: 'embed_revision_binding_missing' });
	});
});
