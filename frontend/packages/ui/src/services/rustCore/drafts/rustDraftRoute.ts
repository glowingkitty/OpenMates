/**
 * Page side of the shared Rust core Worker's `drafts` unit (Rust-core build only;
 * draftSave.ts imports it dynamically behind VITE_OPENMATES_RUST_CORE).
 *
 * Routing is explicit and marked, never silent: a save goes to Rust when the
 * shared core is bound and the unit accepts the chat shape (existing saved
 * Personal chat on the admitted history client). Every refusal decided before
 * any Rust write returns `legacy` with its code, and the caller runs the
 * existing TS writer for that save. A failure after Rust started writing is
 * `failed`: the editor stays unsaved and no TS rewrite happens. The one
 * exception retried (once, through Rust) is a post-commit readback conflict.
 *
 * Marker: `document.documentElement.dataset.rustCoreDraft` is `rust-local`,
 * `rust-synced`, `rust-ack-failed-<code>`, `ts-<code>` or `rust-failed-<code>`
 * (E2E and bench read it).
 */
import { isSharedRustCoreRegistered, requireSharedRustCore, SharedCoreError } from '../host/sharedCoreRegistry';
import type { SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError } from '../host/unitPort';
import type { UnitPort } from '../host/unitPort';
import { browserProfileLifecycle } from '../platformLifecycle';
import { isDraftRoutingCode, validDraftSaveResponse } from './draftsProtocol';
import type { DraftRemotePayload, DraftsProtocol } from './draftsProtocol';

export type RustDraftSaveOutcome =
	| { kind: 'legacy'; code: string }
	| { kind: 'failed'; code: string }
	| { kind: 'saved'; version: number; synced: Promise<void> };

export interface RustDraftSaveInput {
	chatId: string;
	markdown: string;
	/** The chat-list preview the UI derived (formatDraftPreview); Rust encrypts it unchanged. */
	preview: string;
	/** Personal workspace epoch captured when the save started. */
	workspaceEpoch: number;
	/** Sends the ciphertext `update_draft` on the existing socket; resolves on receipt or after it queued its own replay. */
	send(payload: DraftRemotePayload): Promise<void>;
}

/**
 * Post-commit readback refusal: Rust's store transaction committed, then the row
 * or its queued intent no longer matched (a concurrent chats_db writer, e.g. a TS
 * read-modify-write of the chat row during reconnect, replaced it). One fresh Rust
 * save re-captures the current row and writes the same editor content again;
 * any intent the first write left stays durable and the server version check
 * settles it on replay, as for any queued draft.
 */
const READBACK_CONFLICT = 'draft_effect_readback_draft';
const MAX_SAVE_ATTEMPTS = 2;

interface OpenedUnit { core: SharedRustCore; generation: number; port: UnitPort<DraftsProtocol>; stopCrash: () => void }
let opened: OpenedUnit | null = null;
let opening: Promise<OpenedUnit> | null = null;

function mark(value: string): void {
	if (typeof document !== 'undefined') document.documentElement.dataset.rustCoreDraft = value;
	// Timing evidence next to the history session marks (openmates:rust:*).
	if (typeof performance !== 'undefined') performance.mark(`openmates:rust:draft-${value}`);
}

/**
 * Stage durations of one Rust save as `openmates:rust:draft-timing` (startTime =
 * route entry; detail: first save on this unit port, unit open, save round trip
 * and the Worker's DraftSaveTiming). Numbers only; the bench reads them.
 */
function timingMark(entered: number, detail: Record<string, unknown>): void {
	if (typeof performance === 'undefined' || typeof performance.mark !== 'function') return;
	performance.mark('openmates:rust:draft-timing', { startTime: entered, detail });
}

function drop(unit: OpenedUnit): void {
	if (opened === unit) opened = null;
	unit.stopCrash();
	unit.port.close();
}

async function unit(core: SharedRustCore, generation: number): Promise<OpenedUnit> {
	if (opened && opened.core === core && opened.generation === generation && !opened.port.closed) return opened;
	if (opened) drop(opened);
	opening ??= core.openUnit('drafts').then((raw) => {
		const created: OpenedUnit = { core, generation, port: createUnitPort<DraftsProtocol>(raw), stopCrash: () => {} };
		created.stopCrash = core.onCrash(() => drop(created));
		opened = created;
		return created;
	}).finally(() => { opening = null; });
	const result = await opening;
	if (result.generation !== generation) throw new SharedCoreError('shared_core_aborted');
	return result;
}

function errorCode(error: unknown): string {
	return error instanceof UnitPortError || error instanceof SharedCoreError ? error.code : 'unavailable';
}

function legacy(code: string): RustDraftSaveOutcome {
	mark(`ts-${code}`);
	console.info(`[DraftService] Draft save routed to the TypeScript writer (rust core: ${code}).`);
	return { kind: 'legacy', code };
}

type SaveAttempt =
	| { kind: 'saved'; reply: DraftsProtocol['save']['response']; requestMs: number }
	| { kind: 'refused'; code: string };

/** One `save` request on the unit (the markdown buffer is transferred, so each attempt encodes afresh). */
async function requestSave(drafts: OpenedUnit, input: RustDraftSaveInput, scope: DraftsProtocol['save']['request']['scope']): Promise<SaveAttempt> {
	const markdown = new TextEncoder().encode(input.markdown);
	const requested = performance.now();
	try {
		const reply = await drafts.port.request('save', {
			chatId: input.chatId, markdown, preview: input.preview, scope, nowSeconds: Math.floor(Date.now() / 1000)
		}, { transfer: [markdown.buffer] });
		if (!validDraftSaveResponse(reply, input.chatId)) throw new UnitPortError('unit_bad_reply');
		return { kind: 'saved', reply, requestMs: performance.now() - requested };
	} catch (error) {
		return { kind: 'refused', code: errorCode(error) };
	}
}

/** Saves one editor draft through Rust, or names why this save stays on the TS writer. */
export async function saveDraftWithRustCore(input: RustDraftSaveInput): Promise<RustDraftSaveOutcome> {
	if (!isSharedRustCoreRegistered()) return legacy('rust_core_not_enabled');
	const core = requireSharedRustCore();
	const generation = core.generation;
	if (generation === null) return legacy('not_bound');
	let lifecycleGeneration: number;
	try {
		lifecycleGeneration = browserProfileLifecycle.current();
	} catch {
		return legacy('profile_mutation');
	}
	const entered = performance.now();
	const firstOnUnit = !opened || opened.core !== core || opened.generation !== generation || opened.port.closed;
	let drafts: OpenedUnit;
	try {
		drafts = await unit(core, generation);
	} catch (error) {
		return legacy(`open_${errorCode(error)}`);
	}
	const unitOpenMs = performance.now() - entered;
	const release = core.hold();
	let saved: DraftsProtocol['save']['response'];
	try {
		const scope = { lifecycleGeneration, workspaceEpoch: input.workspaceEpoch };
		let attempt = 1;
		let outcome = await requestSave(drafts, input, scope);
		while (outcome.kind === 'refused' && outcome.code === READBACK_CONFLICT && attempt < MAX_SAVE_ATTEMPTS) {
			console.warn(`[DraftService] Rust draft row changed right after its write (${outcome.code}); saving it once more.`);
			attempt += 1;
			outcome = await requestSave(drafts, input, scope);
		}
		if (outcome.kind === 'refused') {
			// Only the first attempt may route to TS: a retry follows a committed Rust write.
			if (attempt === 1 && isDraftRoutingCode(outcome.code)) return legacy(outcome.code);
			mark(`rust-failed-${outcome.code}`);
			console.warn(`[DraftService] Rust draft save failed (${outcome.code}); the draft stays unsaved.`);
			return { kind: 'failed', code: outcome.code };
		}
		saved = outcome.reply;
		timingMark(entered, { firstOnUnit, unitOpenMs, attempts: attempt, requestMs: outcome.requestMs, ...saved.timing });
	} finally {
		release();
	}
	mark('rust-local');
	const synced = (async () => {
		try {
			await input.send(saved.payload);
		} catch (error) {
			// The encrypted intent stays durable in pending_sync_changes for offline replay;
			// only the in-memory handle is freed. A refused release means the unit already
			// dropped it (generation ended), which needs no further action.
			void drafts.port.request('release', { resourceId: saved.resourceId }).catch(() => undefined);
			throw error;
		}
		const held = core.hold();
		try {
			await drafts.port.request('acknowledge', { resourceId: saved.resourceId });
		} catch (error) {
			// The server already has this version. A refused ack (the row changed
			// meanwhile, or the generation ended) leaves the encrypted intent durable;
			// the next offline replay re-sends that same draft_v and the server version
			// check decides it, as for any TS-queued draft.
			const code = errorCode(error);
			mark(`rust-ack-failed-${code}`);
			console.warn(`[DraftService] Rust draft intent kept after delivery (${code}); offline replay settles it.`);
			return;
		} finally {
			held();
		}
		mark('rust-synced');
	})();
	return { kind: 'saved', version: saved.version, synced };
}

/** Test seam: forget the cached unit port. */
export function resetRustDraftRouteForTests(): void {
	if (opened) drop(opened);
	opening = null;
}
