// Image versions on the web shell: the `embedWrite` unit's child-revision
// handlers (Rust session and IndexedDB replaced by in-memory fakes) and the
// page-side step runner. Rust decides every row and marker; these tests prove
// the shell glue stores each step's local value, sends, stores the confirmed
// value only after a successful send, stops at the first failure, resumes a
// replay from the stored markers, adopts a row another writer stored first and
// keeps typed codes. The fake planner mirrors the core's resume rule.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UnitPortError, UnitRefusal, type UnitPort } from '../../host/unitPort';
import type { EmbedWriteProtocol } from '../embedDataProtocol';
import type { StreamCompletionInput } from '../../embedWriteAdapter';
import { createChildRevisionHandlers } from '../childRevisionHandlers';
import { runChildRevision } from '../rustChildRevisionWrite';

/** In-memory `embeds` (by contentRef) and `embed_diffs` (by id), as the Worker stores them. */
const idb = vi.hoisted(() => ({
	heads: new Map<string, Record<string, unknown>>(),
	diffs: new Map<string, Record<string, unknown>>()
}));

vi.mock('../../embedWriteIdb', () => ({
	getEmbedEntry: async (_db: unknown, ref: string) => idb.heads.get(ref) ?? null,
	getEmbedDiffs: async (_db: unknown, embedId: string) => [...idb.diffs.values()]
		.filter((row) => row.embed_id === embedId)
		.sort((a, b) => Number(a.version_number) - Number(b.version_number)),
	putEmbedDiff: async (_db: unknown, row: Record<string, unknown>) => { idb.diffs.set(String(row.id), row); },
	persistPreparedEmbedWrite: async (_db: unknown, prepared: { local_entry: Record<string, unknown> }) => {
		idb.heads.set(String(prepared.local_entry.contentRef), prepared.local_entry);
	}
}));

const EMBED = 'embed-1';
const REF = `embed:${EMBED}`;
const row = (version: number, confirmed = false) => ({
	id: `${EMBED}_v${version}`, embed_id: EMBED, version_number: version, encrypted_snapshot: `snap-${version}`,
	...(confirmed ? { server_confirmed: true } : {})
});
const headAt = (version: number, pending?: number) => ({
	contentRef: REF, type: 'image', version_number: version, parent_embed_id: 'parent-1',
	...(pending ? { revision_pending_version: pending } : {})
});

/** Fake `prepare_child_revision`: only the writes the stored markers do not confirm (core resume rule). */
function planFromStored(_payload: string, headJson: string | undefined, rowsJson: string): string {
	const head = JSON.parse(headJson ?? 'null') as Record<string, unknown> | null;
	const rows = JSON.parse(rowsJson) as Array<Record<string, unknown>>;
	const confirmed = (version: number) => rows.some((r) => r.version_number === version && r.server_confirmed === true);
	const headDone = head?.version_number === 2 && head.revision_pending_version === undefined;
	if (headDone && confirmed(2)) throw 'embed_revision_already_applied';
	const steps: unknown[] = [];
	if (!confirmed(1)) steps.push({ op: 'store_embed_diff', role: 'base_snapshot', local_row: row(1), server_payload: { v: 1 }, confirmed_row: row(1, true) });
	if (!headDone) steps.push({ op: 'store_embed', store_payload: { embed_id: EMBED, version_number: 2 }, confirmed_entry: headAt(2) });
	if (!confirmed(2)) steps.push({ op: 'store_embed_diff', role: 'history', local_row: row(2), server_payload: { v: 2 }, confirmed_row: row(2, true) });
	return JSON.stringify({
		local_entry: headAt(2, 2), local_key_wrappers: [], embed_ref_registration: null, child_ref_embed_ids: [],
		child_revision: { base_version: 1, version_number: 2, steps }
	});
}

function rustCall<T>(call: () => T | Promise<T>): Promise<T> {
	return Promise.resolve().then(call).catch((error) => {
		throw new UnitRefusal(typeof error === 'string' ? error : 'embed_write_failed');
	});
}

type Handler = (payload: unknown) => Promise<unknown>;
type LooseHandlers = Record<keyof EmbedWriteProtocol & string, Handler>;

function handlers(session: Record<string, unknown>, binding: Record<string, unknown> = {}): LooseHandlers {
	const signal = new AbortController().signal;
	const real = createChildRevisionHandlers({
		session: () => session as never,
		binding: binding as never,
		openDb: async () => ({}) as IDBDatabase,
		rust: rustCall,
		sleep: async () => {}
	}) as unknown as Record<string, (payload: unknown, signal: AbortSignal) => unknown>;
	return new Proxy({} as LooseHandlers, {
		get: (_target, op: string) => async (payload: unknown) => real[op](payload, signal)
	});
}

const input = { embed_id: EMBED, type: 'image', version_number: 2 } as unknown as StreamCompletionInput;

/** A page port that calls the handlers directly (no Worker), with UnitPortError like the real port. */
function port(h: LooseHandlers): UnitPort<EmbedWriteProtocol> {
	return {
		async request(op: keyof LooseHandlers, payload: unknown) {
			try {
				return await h[op](payload);
			} catch (error) {
				if (error instanceof UnitRefusal) throw new UnitPortError(error.code);
				throw error;
			}
		}
	} as unknown as UnitPort<EmbedWriteProtocol>;
}

beforeEach(() => {
	idb.heads.clear();
	idb.diffs.clear();
	idb.heads.set(REF, headAt(1));
});

describe('child revision handlers', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('hands the stored head and rows to Rust and returns only the step kinds', async () => {
		idb.diffs.set(row(1).id, row(1));
		const prepare = vi.fn(async (payload: string, head: string | undefined, rows: string) => planFromStored(payload, head, rows));
		const plan = await handlers({ prepare_child_revision: prepare }).prepareChildRevision({ payload: input, normalizedType: 'image' });
		// Rows go to Rust exactly as stored, markers included.
		expect(prepare).toHaveBeenCalledWith(JSON.stringify(input), JSON.stringify(headAt(1)), JSON.stringify([row(1)]));
		expect(plan).toEqual({
			already_applied: false, base_version: 1, version_number: 2,
			steps: [{ op: 'store_embed_diff', role: 'base_snapshot', version: 1 }, { op: 'store_embed' }, { op: 'store_embed_diff', role: 'history', version: 2 }]
		});
		expect(JSON.stringify(plan)).not.toMatch(/local_row|confirmed_row|confirmed_entry/);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('treats a replay of a stored version as already applied and retries a pending parent key', async () => {
		const prepare = vi.fn()
			.mockRejectedValueOnce('embed_parent_key_pending')
			.mockRejectedValueOnce('embed_revision_already_applied');
		const plan = await handlers({ prepare_child_revision: prepare }).prepareChildRevision({ payload: input, normalizedType: 'image' });
		expect(prepare).toHaveBeenCalledTimes(2);
		expect(plan).toMatchObject({ already_applied: true, steps: [] });
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('stores the local value, then the confirmed value only after the send, strictly in order', async () => {
		const h = handlers({ prepare_child_revision: planFromStored });
		await h.prepareChildRevision({ payload: input, normalizedType: 'image' });
		await expect(h.runChildRevisionStep({ embedId: EMBED, index: 1 })).rejects.toMatchObject({ code: 'embed_revision_step_order' });
		await expect(h.confirmChildRevisionStep({ embedId: EMBED, index: 0 })).rejects.toMatchObject({ code: 'embed_revision_step_order' });
		expect(await h.runChildRevisionStep({ embedId: EMBED, index: 0 })).toEqual({ op: 'store_embed_diff', version: 1, server_payload: { v: 1 } });
		expect(idb.diffs.get(row(1).id)).toEqual(row(1));
		await expect(h.runChildRevisionStep({ embedId: EMBED, index: 1 })).rejects.toMatchObject({ code: 'embed_revision_step_order' });
		await h.confirmChildRevisionStep({ embedId: EMBED, index: 0 });
		expect(idb.diffs.get(row(1).id)).toEqual(row(1, true));
		expect(await h.runChildRevisionStep({ embedId: EMBED, index: 1 })).toMatchObject({ op: 'store_embed', content_ref: REF });
		expect(idb.heads.get(REF)).toEqual(headAt(2, 2));
		await h.confirmChildRevisionStep({ embedId: EMBED, index: 1 });
		expect(idb.heads.get(REF)).toEqual(headAt(2));
		await h.endChildRevision({ embedId: EMBED });
		await expect(h.runChildRevisionStep({ embedId: EMBED, index: 2 })).rejects.toMatchObject({ code: 'embed_revision_not_prepared' });
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('caches a fetched page through Rust, opens versions from stored rows and asks the core for the head version', async () => {
		const open = vi.fn(() => 'toon-v1');
		const cache = vi.fn(() => JSON.stringify([row(1, true)]));
		const h = handlers({ embed_version_content: open, cache_version_page: cache }, { embed_head_version: () => 1 });
		const page = { embed_id: EMBED, version_number: 1, rows: [{ version_number: 1, encrypted_snapshot: 'snap-1' }] };
		expect(await h.cacheVersionPage({ embedId: EMBED, page })).toBe(1);
		expect(cache).toHaveBeenCalledWith(EMBED, JSON.stringify(headAt(1)), JSON.stringify(page));
		expect(idb.diffs.get(row(1).id)).toEqual(row(1, true));
		expect(await h.embedVersionContent({ embedId: EMBED, version: 1 })).toBe('toon-v1');
		expect(open).toHaveBeenCalledWith(EMBED, 1, JSON.stringify(headAt(1)), JSON.stringify([row(1, true)]));
		expect(await h.embedHeadVersion({ embedId: EMBED })).toEqual({ version: 1, parent_embed_id: 'parent-1' });
		// Without the core export the shell does not read version_number itself.
		await expect(handlers({}).embedHeadVersion({ embedId: EMBED })).rejects.toMatchObject({ code: 'embed_revision_binding_missing' });
		await expect(h.embedVersionsByMessage({ messages: [], embedId: EMBED })).rejects.toMatchObject({ code: 'embed_revision_binding_missing' });
		const bound = handlers({}, { embed_versions_by_message: () => JSON.stringify([{ message_id: 'm1', version: 1, pinned_here: false }]) });
		expect(await bound.embedVersionsByMessage({ messages: [], embedId: EMBED })).toEqual([{ message_id: 'm1', version: 1, pinned_here: false }]);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.message-shows-its-version
	it('keeps a stored child head the core finds newer than a synced row, and asks only for stored heads', async () => {
		idb.heads.set(REF, headAt(3));
		const regresses = vi.fn((stored: string, incoming: string) =>
			(JSON.parse(incoming).version_number ?? 1) < JSON.parse(stored).version_number);
		const h = handlers({}, { embed_synced_head_regresses: regresses });
		const older = { embed_id: EMBED, parent_embed_id: 'parent-1', version_number: 2 };
		const kept = await h.embedSyncedHeadsKept({ rows: [
			{ embedId: EMBED, incoming: older },
			{ embedId: 'not-stored', incoming: { embed_id: 'not-stored', parent_embed_id: 'parent-1', version_number: 1 } }
		] });
		expect(kept).toEqual([EMBED]);
		// The stored row goes to Rust as stored; a row this device does not hold is never compared.
		expect(regresses).toHaveBeenCalledTimes(1);
		expect(regresses).toHaveBeenCalledWith(JSON.stringify(headAt(3)), JSON.stringify(older));
		expect(await h.embedSyncedHeadsKept({ rows: [{ embedId: EMBED, incoming: { ...older, version_number: 3 } }] })).toEqual([]);
		await expect(handlers({}).embedSyncedHeadsKept({ rows: [{ embedId: EMBED, incoming: older }] }))
			.rejects.toMatchObject({ code: 'embed_revision_binding_missing' });
		await expect(h.embedSyncedHeadsKept({ rows: 'x' })).rejects.toMatchObject({ code: 'embed_write_bad_rows' });
	});
});

describe('runChildRevision', () => {
	function io(overrides: Partial<Parameters<typeof runChildRevision>[3]> = {}) {
		const calls: string[] = [];
		return {
			calls,
			io: {
				sendStoreEmbed: vi.fn(async () => { calls.push('store_embed'); return true; }),
				sendStoreEmbedDiff: vi.fn(async (payload: Record<string, unknown>) => { calls.push(`diff:${payload.v}`); }),
				readCanonical: vi.fn(async () => ({ status: 200, body: { rows: [] } })),
				afterHeadStored: vi.fn(async () => { calls.push('after_head'); }),
				...overrides
			}
		};
	}

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('sends base snapshot, head and history in order', async () => {
		const unit = port(handlers({ prepare_child_revision: planFromStored }));
		const { calls, io: sink } = io();
		expect(await runChildRevision(unit, input, 'image', sink)).toBe(true);
		expect(calls).toEqual(['diff:1', 'store_embed', 'after_head', 'diff:2']);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('stops before history when the head was not durable', async () => {
		const unit = port(handlers({ prepare_child_revision: planFromStored }));
		const { calls, io: sink } = io({ sendStoreEmbed: vi.fn(async () => false) });
		await expect(runChildRevision(unit, input, 'image', sink)).rejects.toMatchObject({ code: 'embed_revision_head_not_durable' });
		expect(calls).toEqual(['diff:1']);
		// The head stays pending locally; history N+1 was never stored or sent.
		expect(idb.heads.get(REF)).toEqual(headAt(2, 2));
		expect(idb.diffs.has(row(2).id)).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('resumes a replay after a failed head send: resends head and history, not the confirmed base', async () => {
		const prepare = vi.fn(planFromStored);
		const unit = port(handlers({ prepare_child_revision: prepare }));
		const failed = io({ sendStoreEmbed: vi.fn(async () => false) });
		await expect(runChildRevision(unit, input, 'image', failed.io)).rejects.toMatchObject({ code: 'embed_revision_head_not_durable' });

		const replay = io();
		expect(await runChildRevision(unit, input, 'image', replay.io)).toBe(true);
		// The replay hands Rust the pending head and the confirmed base row exactly as stored.
		expect(prepare).toHaveBeenLastCalledWith(JSON.stringify(input), JSON.stringify(headAt(2, 2)), JSON.stringify([row(1, true)]));
		expect(replay.calls).toEqual(['store_embed', 'after_head', 'diff:2']);
		expect(idb.heads.get(REF)).toEqual(headAt(2));
		expect(idb.diffs.get(row(2).id)).toEqual(row(2, true));

		// A third delivery finds everything confirmed: nothing to write.
		const third = io();
		expect(await runChildRevision(unit, input, 'image', third.io)).toBe(false);
		expect(third.calls).toEqual([]);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('adopts the canonical row when another writer stored it first and rethrows other errors', async () => {
		const adopt = vi.fn(() => JSON.stringify({ ...row(1, true), adopted: true }));
		const unit = port(handlers({ prepare_child_revision: planFromStored, adopt_child_revision_row: adopt }));
		let first = true;
		const { calls, io: sink } = io({
			sendStoreEmbedDiff: vi.fn(async (payload: Record<string, unknown>) => {
				if (first) { first = false; throw Object.assign(new Error('taken'), { code: 'embed_diff_conflict' }); }
				calls.push(`diff:${payload.v}`);
			})
		});
		await runChildRevision(unit, input, 'image', sink);
		expect(adopt).toHaveBeenCalledWith(JSON.stringify(row(1)), JSON.stringify({ rows: [] }));
		expect(idb.diffs.get(row(1).id)).toEqual({ ...row(1, true), adopted: true });
		expect(calls).toEqual(['store_embed', 'after_head', 'diff:2']);

		idb.heads.set(REF, headAt(1));
		idb.diffs.clear();
		const failing = io({ sendStoreEmbedDiff: vi.fn(async () => { throw Object.assign(new Error('denied'), { code: 'forbidden' }); }) });
		await expect(runChildRevision(unit, input, 'image', failing.io)).rejects.toMatchObject({ code: 'forbidden' });
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('writes nothing for a replay', async () => {
		const unit = port(handlers({ prepare_child_revision: async () => { throw 'embed_revision_already_applied'; } }));
		const { calls, io: sink } = io();
		expect(await runChildRevision(unit, input, 'image', sink)).toBe(false);
		expect(calls).toEqual([]);
	});
});
