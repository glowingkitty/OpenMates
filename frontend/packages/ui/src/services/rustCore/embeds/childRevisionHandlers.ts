/**
 * Worker handlers of the `embedWrite` unit for image versions (wire contract
 * "Core API for shells"; VITE_OPENMATES_RUST_CORE builds only).
 *
 * Persist (resumable): `prepareChildRevision` hands the event, the child's
 * stored head and its local `embed_diffs` rows exactly as stored (durability
 * markers included) to Rust on the first run and on every replay; Rust returns
 * only the writes the server has not confirmed. Per step, strictly in order:
 * `runChildRevisionStep` stores the local value (`local_row`, or the pending
 * `local_entry` plus wrappers) and returns the server payload; after the page's
 * send succeeded, `confirmChildRevisionStep` stores `confirmed_row` /
 * `confirmed_entry` (or `adoptChildRevisionRow` stores the canonical row after
 * a conflict). Nothing here decides a key, hash, version, row or marker.
 * Read: `embedVersionContent` opens version K from the stored head and rows;
 * `cacheVersionPage` stores the rows Rust validated from a fetched page;
 * `embedHeadVersion`, `embedVersionsByMessage` and `embedPinnedEmbeds` are the
 * core's version rules.
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import {
	PARENT_KEY_PENDING,
	type EmbedWriterPort,
	type EncryptedDiffRow,
	type PreparedEmbedWrite
} from '../embedWriteAdapter';
import { getEmbedDiffs, getEmbedEntry, persistPreparedEmbedWrite, putEmbedDiff } from '../embedWriteIdb';
import type {
	ChildRevisionFunctions,
	ChildRevisionPlan,
	ChildRevisionProtocol,
	ChildRevisionStepKind,
	ChildRevisionWriterPort,
	MessageImageVersion,
	PinnedEmbed
} from './childRevisionProtocol';
import type { ChatsDbOpener } from './embedWorkerIdb';

/** A replay of a version the head already holds: nothing to write (contract: just ACK). */
export const REVISION_ALREADY_APPLIED = 'embed_revision_already_applied';
const PARENT_KEY_RETRIES = 5;
const PARENT_KEY_BASE_DELAY_MS = 100;

type RawStep =
	| {
		op: 'store_embed_diff'; role: 'base_snapshot' | 'history'; local_row: EncryptedDiffRow;
		server_payload: Record<string, unknown>; confirmed_row: EncryptedDiffRow;
	}
	| { op: 'store_embed'; store_payload: Record<string, unknown>; confirmed_entry: PreparedEmbedWrite['local_entry'] };
type PreparedRevision = PreparedEmbedWrite & {
	child_revision?: { base_version: number; version_number: number; steps: RawStep[] };
};
/** `next`: the step to run; `stored`: its local value is stored and its send is in flight. */
interface Pending { prepared: PreparedRevision; steps: RawStep[]; normalizedType: string; next: number; stored: boolean }

function text(value: unknown, field: string): string {
	if (typeof value !== 'string' || value.length === 0) throw new UnitRefusal(`embed_write_bad_${field}`);
	return value;
}
function index(value: unknown): number {
	if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new UnitRefusal('embed_write_bad_index');
	return value;
}
function parseJson<T>(raw: unknown): T {
	if (typeof raw !== 'string') throw new UnitRefusal('embed_write_protocol');
	try {
		return JSON.parse(raw) as T;
	} catch {
		throw new UnitRefusal('embed_write_protocol');
	}
}
function stepKind(step: RawStep): ChildRevisionStepKind {
	if (step.op === 'store_embed') {
		if (!step.confirmed_entry) throw new UnitRefusal('embed_write_protocol');
		return { op: 'store_embed' };
	}
	if (step.op !== 'store_embed_diff' || !step.local_row || !step.confirmed_row) throw new UnitRefusal('embed_write_protocol');
	return { op: 'store_embed_diff', role: step.role, version: step.local_row.version_number };
}

export interface ChildRevisionDeps {
	session: () => EmbedWriterPort & ChildRevisionWriterPort;
	binding: ChildRevisionFunctions;
	openDb: ChatsDbOpener;
	/** The unit's Rust wrapper: keeps a stable rejection code, never internal text. */
	rust: <T>(call: () => T | Promise<T>) => Promise<T>;
	sleep?: (ms: number) => Promise<void>;
}

export function createChildRevisionHandlers(deps: ChildRevisionDeps): UnitHandlers<ChildRevisionProtocol> {
	const { session, binding, openDb, rust } = deps;
	const sleep = deps.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
	const pending = new Map<string, Pending>();

	/** The child arrives before its parent's key loads: the core asks to retry (legacy backoff). */
	async function prepare(payloadJson: string, head: string | undefined, rows: string): Promise<unknown> {
		for (let attempt = 0; ; attempt++) {
			try {
				return await rust(() => session().prepare_child_revision(payloadJson, head, rows));
			} catch (error) {
				if (!(error instanceof UnitRefusal) || error.code !== PARENT_KEY_PENDING || attempt >= PARENT_KEY_RETRIES) throw error;
			}
			await sleep(PARENT_KEY_BASE_DELAY_MS * 2 ** attempt);
		}
	}
	/** Step `at` of the prepared revision; strict order: only the next step, in the expected phase. */
	function current(embedId: string, at: number, stored: boolean): { revision: Pending; step: RawStep } {
		const revision = pending.get(embedId);
		const step = revision?.steps[at];
		if (!revision || !step) throw new UnitRefusal('embed_revision_not_prepared');
		if (at !== revision.next || revision.stored !== stored) throw new UnitRefusal('embed_revision_step_order');
		return { revision, step };
	}
	function free<T>(name: keyof ChildRevisionFunctions): (...args: string[]) => T {
		const fn = binding[name] as ((...args: string[]) => T) | undefined;
		if (typeof fn !== 'function') throw new UnitRefusal('embed_revision_binding_missing');
		return fn;
	}

	return {
		async prepareChildRevision(payload) {
			const request = payload as { payload?: Record<string, unknown>; normalizedType?: unknown } | null;
			const input = request?.payload;
			if (typeof input !== 'object' || input === null) throw new UnitRefusal('embed_write_bad_payload');
			const embedId = text(input.embed_id, 'embed_id');
			const normalizedType = text(request?.normalizedType, 'type');
			const db = await openDb();
			const head = await getEmbedEntry(db, `embed:${embedId}`);
			const rows = await getEmbedDiffs(db, embedId);
			let prepared: PreparedRevision;
			try {
				prepared = parseJson<PreparedRevision>(await prepare(JSON.stringify(input), head ? JSON.stringify(head) : undefined, JSON.stringify(rows)));
			} catch (error) {
				if (error instanceof UnitRefusal && error.code === REVISION_ALREADY_APPLIED) {
					const plan: ChildRevisionPlan = { already_applied: true, base_version: null, version_number: null, steps: [] };
					return plan;
				}
				throw error;
			}
			const writes = prepared.child_revision;
			if (!writes || !Array.isArray(writes.steps) || writes.steps.length === 0) throw new UnitRefusal('embed_write_protocol');
			if (prepared.local_entry?.type !== input.type) throw new UnitRefusal('embed_write_type_mismatch');
			const steps = writes.steps.map(stepKind);
			pending.set(embedId, { prepared, steps: writes.steps, normalizedType, next: 0, stored: false });
			const plan: ChildRevisionPlan = {
				already_applied: false, base_version: writes.base_version, version_number: writes.version_number, steps
			};
			return plan;
		},
		async runChildRevisionStep(payload) {
			const request = payload as { embedId?: unknown; index?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const { revision, step } = current(embedId, index(request?.index), false);
			const db = await openDb();
			if (step.op === 'store_embed_diff') {
				await putEmbedDiff(db, step.local_row);
				revision.stored = true;
				return { op: 'store_embed_diff', version: step.local_row.version_number, server_payload: step.server_payload };
			}
			// The top-level local entry carries `revision_pending_version` until the send is confirmed.
			await persistPreparedEmbedWrite(db, revision.prepared, () => revision.normalizedType);
			revision.stored = true;
			const { prepared } = revision;
			return {
				op: 'store_embed',
				store_payload: step.store_payload,
				embed_ref_registration: prepared.embed_ref_registration,
				child_ref_embed_ids: prepared.child_ref_embed_ids,
				content_ref: prepared.local_entry.contentRef
			};
		},
		async confirmChildRevisionStep(payload) {
			const request = payload as { embedId?: unknown; index?: unknown } | null;
			const { revision, step } = current(text(request?.embedId, 'embed_id'), index(request?.index), true);
			const db = await openDb();
			if (step.op === 'store_embed_diff') {
				await putEmbedDiff(db, step.confirmed_row);
			} else {
				// Wrappers were stored with the pending entry; only the entry changes (marker dropped).
				const confirmed: PreparedEmbedWrite = { ...revision.prepared, local_entry: step.confirmed_entry, local_key_wrappers: [] };
				await persistPreparedEmbedWrite(db, confirmed, () => revision.normalizedType);
			}
			revision.next += 1;
			revision.stored = false;
			return null;
		},
		async adoptChildRevisionRow(payload) {
			const request = payload as { embedId?: unknown; index?: unknown; page?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const { revision, step } = current(embedId, index(request?.index), true);
			if (step.op !== 'store_embed_diff') throw new UnitRefusal('embed_write_bad_index');
			const adopted = parseJson<EncryptedDiffRow>(await rust(() =>
				session().adopt_child_revision_row(JSON.stringify(step.local_row), JSON.stringify(request?.page ?? null))));
			await putEmbedDiff(await openDb(), adopted);
			revision.next += 1;
			revision.stored = false;
			return adopted;
		},
		endChildRevision(payload) {
			pending.delete(text((payload as { embedId?: unknown } | null)?.embedId, 'embed_id'));
			return null;
		},
		async embedVersionContent(payload) {
			const request = payload as { embedId?: unknown; version?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const version = request?.version;
			if (typeof version !== 'number' || !Number.isSafeInteger(version) || version < 1) throw new UnitRefusal('embed_write_bad_version');
			const db = await openDb();
			const head = await getEmbedEntry(db, `embed:${embedId}`);
			if (!head) throw new UnitRefusal('embed_version_unavailable');
			const rows = await getEmbedDiffs(db, embedId);
			return rust(() => session().embed_version_content(embedId, version, JSON.stringify(head), JSON.stringify(rows)));
		},
		async cacheVersionPage(payload) {
			const request = payload as { embedId?: unknown; page?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const db = await openDb();
			const head = await getEmbedEntry(db, `embed:${embedId}`);
			if (!head) throw new UnitRefusal('embed_version_unavailable');
			const rows = parseJson<EncryptedDiffRow[]>(await rust(() =>
				session().cache_version_page(embedId, JSON.stringify(head), JSON.stringify(request?.page ?? null))));
			if (!Array.isArray(rows)) throw new UnitRefusal('embed_write_protocol');
			for (const row of rows) await putEmbedDiff(db, row);
			return rows.length;
		},
		async embedHeadVersion(payload) {
			const embedId = text((payload as { embedId?: unknown } | null)?.embedId, 'embed_id');
			const head = await getEmbedEntry(await openDb(), `embed:${embedId}`);
			if (!head) return null;
			const headVersion = free<number>('embed_head_version');
			const version = await rust(() => headVersion(JSON.stringify(head)));
			// The parent id only routes the key load; the version comes from the core.
			return { version, parent_embed_id: typeof head.parent_embed_id === 'string' && head.parent_embed_id ? head.parent_embed_id : null };
		},
		async embedVersionsByMessage(payload) {
			const request = payload as { messages?: unknown; embedId?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			if (!Array.isArray(request?.messages)) throw new UnitRefusal('embed_write_bad_messages');
			const fn = free<string>('embed_versions_by_message');
			return parseJson<MessageImageVersion[]>(await rust(() => fn(JSON.stringify(request.messages), embedId)));
		},
		async embedPinnedEmbeds(payload) {
			const parentContent = text((payload as { parentContent?: unknown } | null)?.parentContent, 'content');
			const fn = free<string>('embed_pinned_embeds');
			return parseJson<PinnedEmbed[]>(await rust(() => fn(parentContent)));
		}
	};
}
