/**
 * `embedEdit` namespace installer of the shared Rust core Worker
 * (`feature.embed-user-edits`; VITE_OPENMATES_RUST_CORE builds only).
 *
 * Marshalling only. Every call runs on the ADMITTED client of the bound history
 * `core` lease, borrowed through coreClientBorrow (no second client or
 * admission). Each Enhance start, Enhance save and restore first reads the
 * embed's server head through the core (`embed_user_edit_head`, which also
 * loads its key wrappers into the client cache) and passes that head back
 * unchanged; the Worker keeps no head or version logic (a content edit hands the
 * version it was made on to the core, which refuses a moved head). The core does the Enhance request, job reads, commit, version
 * and hash checks, the `embed_updated` chat event and the event folding.
 *
 * Enhance runs as start -> job reads -> save, each a short borrow: the client
 * is never held for the whole job (minutes), so chat reads keep going in
 * between. Between two reads the run waits for the job's WebSocket frame
 * (`image_enhance_ready` / `image_enhance_failed`, forwarded by the page to the
 * core's waker), at most ENHANCE_RECHECK_MS; the core decides each read's state.
 * A run lives in the Worker realm (module scope), so a page that reloads while
 * the Worker lives joins it again (`runningEnhance` + `enhanceImage`).
 *
 * Borrow bounds: a user-pressed write (Enhance start and save, content edit,
 * restore) waits up to EMBED_EDIT_USER_BORROW_TIMEOUT_MS for a busy dispatcher,
 * which covers the history reconcile and reads that follow an assistant turn;
 * the chat-open reconcile keeps the short EMBED_EDIT_BORROW_TIMEOUT_MS. A job
 * read that finds the dispatcher busy is simply read again later (the job runs
 * on the server meanwhile). `local_session` / `not_admitted` refusals happen
 * before any core call; the page client upgrades its session and resends.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import {
	isEmbedEditUnitClose,
	type EmbedChatItem,
	type EmbedEditProtocol,
	type EmbedEditScope,
	type EmbedEventDelivery,
	type EmbedEventNotice,
	type EmbedRevisionResult,
	type EnhanceJob,
	type ImageEnhanceResult,
	type NoticeReconcileReport,
	type RunningEnhance
} from './embedEditProtocol';

/** Bounded wait for the history dispatcher to become idle (one short core call follows). */
export const EMBED_EDIT_BORROW_TIMEOUT_MS = 10_000;
/** Longer bound for a write the user pressed; stays below the page client's write timeout. */
export const EMBED_EDIT_USER_BORROW_TIMEOUT_MS = 30_000;
/** Longest pause between two job reads when no frame arrives (the server allows 60 reads a minute). */
export const ENHANCE_RECHECK_MS = 5_000;
/** Consecutive job reads refused `core_busy` before the run gives up with that code. */
export const ENHANCE_MAX_BUSY_READS = 8;
/** One job read per call: the core reads once and answers `enhance_timeout` while the job is pending. */
const SINGLE_READ_DEADLINE_MS = 1;

interface EnhanceWaker { notify_frame(type: string, payloadJson: string): boolean; free?(): void }

/** BrowserCoreClient exports of browser_embed_user_edit.rs (all resolve to JSON). */
export interface EmbedEditClient {
	embed_user_edit_head(handle: string, generation: number, embedId: string): Promise<string>;
	start_image_enhance(handle: string, generation: number, embedId: string, headJson: string, scopeJson: string,
		operationId?: string): Promise<string>;
	wait_image_enhance(handle: string, generation: number, operationId: string, waker: EnhanceWaker,
		deadlineMs?: number): Promise<string>;
	save_image_enhance_result(handle: string, generation: number, embedId: string, headJson: string, scopeJson: string,
		operationId: string, identityJson?: string): Promise<string>;
	commit_embed_content_revision(handle: string, generation: number, embedId: string, headJson: string, baseVersion: number,
		scopeJson: string, content: string, textPreview?: string, operationId?: string, identityJson?: string): Promise<string>;
	restore_embed_version(handle: string, generation: number, embedId: string, headJson: string, scopeJson: string,
		restoredFrom: number, identityJson?: string): Promise<string>;
	reconcile_embed_update_notices(handle: string, generation: number, chatId: string): Promise<string>;
}

export interface EmbedEditBinding {
	BrowserImageEnhanceWaker: new () => EnhanceWaker;
	embed_group_updated_events(rowsJson: string): string;
}

export function isEmbedEditBinding(value: unknown): value is EmbedEditBinding {
	const binding = value as Partial<EmbedEditBinding> | null;
	return typeof binding?.BrowserImageEnhanceWaker === 'function' && typeof binding.embed_group_updated_events === 'function';
}

export interface EmbedEditDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
	sleep(ms: number, wake: Promise<void>, signal: AbortSignal): Promise<void>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

/** Core rejections are stable code strings; keep them, never internal text. */
function code(error: unknown): string {
	if (error instanceof UnitRefusal) return error.code;
	const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(raw) ? raw : 'embed_edit_failed';
}
function text(value: unknown, field: string): string {
	if (typeof value !== 'string' || value.length === 0) throw new UnitRefusal(`embed_edit_bad_${field}`);
	return value;
}
function scopeOf(value: unknown): EmbedEditScope {
	const scope = value as Record<string, unknown> | null;
	const team = scope?.team_id === undefined ? {} : { team_id: text(scope.team_id, 'team') };
	if (scope?.kind === 'chat') return { kind: 'chat', chat_id: text(scope.chat_id, 'chat'), ...team };
	if (scope?.kind === 'project') return { kind: 'project', project_id: text(scope.project_id, 'project'), ...team };
	throw new UnitRefusal('embed_edit_bad_scope');
}
function versionOf(value: unknown): number {
	if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw new UnitRefusal('embed_edit_bad_version');
	return value;
}
function parse<T>(raw: unknown): T {
	if (typeof raw !== 'string') throw new UnitRefusal('embed_edit_protocol');
	try {
		return JSON.parse(raw) as T;
	} catch {
		throw new UnitRefusal('embed_edit_protocol');
	}
}

/** Core `EmbedRevisionOutcome` -> page result (drops the ciphertext and history rows). */
export function revisionResult(outcome: unknown): EmbedRevisionResult {
	const value = outcome as { commit?: { committed?: { version?: unknown; base_version?: unknown; content_hash?: unknown }; cache_synchronized?: unknown };
		event?: EmbedEventDelivery; notice?: EmbedEventNotice } | null;
	const committed = value?.commit?.committed;
	if (typeof committed?.version !== 'number' || typeof committed.base_version !== 'number' || !value?.event
		|| typeof committed.content_hash !== 'string') {
		throw new UnitRefusal('embed_edit_protocol');
	}
	return { version: committed.version, base_version: committed.base_version, event: value.event,
		cache_synchronized: value.commit?.cache_synchronized === true, content_hash: committed.content_hash,
		...(value.notice ? { notice: value.notice } : {}) };
}

/** Core `ImageEnhanceSaved` -> page result. */
export function enhanceResult(saved: unknown): ImageEnhanceResult {
	const value = saved as { state?: unknown; operation_id?: unknown; version?: unknown; outcome?: unknown } | null;
	if (typeof value?.operation_id !== 'string') throw new UnitRefusal('embed_edit_protocol');
	if (value.state === 'already_committed' && typeof value.version === 'number') {
		return { operation_id: value.operation_id, version: value.version };
	}
	if (value.state !== 'committed') throw new UnitRefusal('embed_edit_protocol');
	const outcome = revisionResult(value.outcome);
	return { operation_id: value.operation_id, version: outcome.version, event: outcome.event,
		...(outcome.notice ? { notice: outcome.notice } : {}) };
}

interface EnhanceRun extends RunningEnhance {
	readonly waker: EnhanceWaker;
	readonly done: Promise<ImageEnhanceResult>;
	wake(): void;
	woken: Promise<void>;
}

/** Runs of this Worker realm by `${principal}:${embedId}` (one run per image at a time). */
const runs = new Map<string, EnhanceRun>();

function defaultSleep(ms: number, wake: Promise<void>, signal: AbortSignal): Promise<void> {
	return new Promise<void>((resolve, reject) => {
		const timer = setTimeout(done, ms);
		function done() {
			clearTimeout(timer);
			signal.removeEventListener('abort', aborted);
			resolve();
		}
		function aborted() {
			clearTimeout(timer);
			reject(new UnitRefusal('cancelled'));
		}
		signal.addEventListener('abort', aborted, { once: true });
		void wake.then(done);
	});
}

const defaultDeps = (): EmbedEditDeps => ({
	borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs),
	sleep: defaultSleep
});

export function createEmbedEditHandlers(binding: EmbedEditBinding, principal: string, deps: EmbedEditDeps,
	lifetime: AbortSignal): UnitHandlers<EmbedEditProtocol> {
	/** One core call on a borrowed admitted client; always released. */
	async function withClient<T>(work: (client: EmbedEditClient, handle: string, generation: number) => Promise<string>,
		map: (raw: unknown) => T, timeoutMs: number = EMBED_EDIT_USER_BORROW_TIMEOUT_MS): Promise<T> {
		const borrow = await deps.borrow(principal, lifetime, timeoutMs);
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		try {
			const raw = await work(borrow.client as unknown as EmbedEditClient, borrow.status.handle, borrow.status.generation);
			return map(parse(raw));
		} catch (error) {
			throw new UnitRefusal(code(error));
		} finally {
			borrow.release();
		}
	}
	/** The core's server head of the embed (`head_json` of the next call), read on the same borrow. */
	async function head(client: EmbedEditClient, handle: string, generation: number, embedId: string): Promise<string> {
		const read = parse<{ head?: unknown }>(await client.embed_user_edit_head(handle, generation, embedId));
		if (typeof read?.head !== 'object' || read.head === null) throw new UnitRefusal('embed_edit_protocol');
		return JSON.stringify(read.head);
	}

	async function run(entry: EnhanceRun, embedId: string): Promise<ImageEnhanceResult> {
		const scope = JSON.stringify(entry.scope);
		let job = await withClient((client, handle, generation) =>
			head(client, handle, generation, embedId).then((row) => client.start_image_enhance(handle, generation, embedId, row, scope)), (raw) => raw as EnhanceJob);
		entry.operation_id = job.operation_id;
		let busyReads = 0;
		while (job.state === 'pending') {
			await deps.sleep(ENHANCE_RECHECK_MS, entry.woken, lifetime);
			entry.woken = new Promise<void>((resolve) => { entry.wake = resolve; });
			try {
				job = await withClient((client, handle, generation) =>
					client.wait_image_enhance(handle, generation, job.operation_id, entry.waker, SINGLE_READ_DEADLINE_MS), (raw) => raw as EnhanceJob,
					EMBED_EDIT_BORROW_TIMEOUT_MS);
				busyReads = 0;
			} catch (error) {
				if (error instanceof UnitRefusal && error.code === 'enhance_timeout') { busyReads = 0; continue; }
				// The dispatcher stayed busy: the job keeps running on the server; read it again (bounded).
				if (error instanceof UnitRefusal && error.code === 'core_busy' && ++busyReads < ENHANCE_MAX_BUSY_READS) continue;
				throw error;
			}
		}
		const operationId = job.operation_id;
		return withClient((client, handle, generation) =>
			head(client, handle, generation, embedId).then((row) => client.save_image_enhance_result(handle, generation, embedId, row, scope, operationId)), enhanceResult);
	}

	return {
		enhanceImage(payload) {
			const request = payload as { embedId?: unknown; scope?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const scope = scopeOf(request?.scope);
			const key = `${principal}:${embedId}`;
			const existing = runs.get(key);
			// A second press joins the running Enhance instead of starting another job.
			if (existing) return existing.done;
			const state: Omit<EnhanceRun, 'done'> = {
				operation_id: null, scope, waker: new binding.BrowserImageEnhanceWaker(), wake: () => {}, woken: Promise.resolve()
			};
			state.woken = new Promise<void>((resolve) => { state.wake = resolve; });
			const entry = state as EnhanceRun;
			Object.assign(entry, { done: run(entry, embedId).finally(() => {
				if (runs.get(key) === entry) runs.delete(key);
				entry.waker.free?.();
			}) });
			runs.set(key, entry);
			return entry.done;
		},
		runningEnhance(payload) {
			const embedId = text((payload as { embedId?: unknown } | null)?.embedId, 'embed_id');
			const entry = runs.get(`${principal}:${embedId}`);
			return entry ? { operation_id: entry.operation_id, scope: entry.scope } : null;
		},
		enhanceFrame(payload) {
			const request = payload as { type?: unknown; payload?: unknown } | null;
			const type = text(request?.type, 'type');
			const frame = JSON.stringify(request?.payload ?? null);
			let woke = false;
			for (const [key, entry] of runs) {
				if (!key.startsWith(`${principal}:`)) continue;
				let matched = false;
				try {
					matched = entry.waker.notify_frame(type, frame);
				} catch (error) {
					throw new UnitRefusal(code(error));
				}
				const target = (request?.payload as { operation_id?: unknown } | null)?.operation_id;
				if (matched && (entry.operation_id === null || entry.operation_id === target)) {
					entry.wake();
					woke = true;
				}
			}
			return woke;
		},
		async commitContentRevision(payload) {
			const request = payload as { embedId?: unknown; scope?: unknown; baseVersion?: unknown; content?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const scope = JSON.stringify(scopeOf(request?.scope));
			const baseVersion = versionOf(request?.baseVersion);
			const content = text(request?.content, 'content');
			return withClient((client, handle, generation) =>
				head(client, handle, generation, embedId).then((row) =>
					client.commit_embed_content_revision(handle, generation, embedId, row, baseVersion, scope, content)), revisionResult);
		},
		async restoreVersion(payload) {
			const request = payload as { embedId?: unknown; scope?: unknown; restoredFrom?: unknown } | null;
			const embedId = text(request?.embedId, 'embed_id');
			const scope = JSON.stringify(scopeOf(request?.scope));
			const restoredFrom = versionOf(request?.restoredFrom);
			return withClient((client, handle, generation) =>
				head(client, handle, generation, embedId).then((row) => client.restore_embed_version(handle, generation, embedId, row, scope, restoredFrom)), revisionResult);
		},
		async reconcileNotices(payload) {
			const chatId = text((payload as { chatId?: unknown } | null)?.chatId, 'chat');
			return withClient((client, handle, generation) => client.reconcile_embed_update_notices(handle, generation, chatId),
				(raw) => raw as NoticeReconcileReport, EMBED_EDIT_BORROW_TIMEOUT_MS);
		},
		groupUpdatedEvents(payload) {
			const rows = (payload as { rows?: unknown } | null)?.rows;
			if (!Array.isArray(rows)) throw new UnitRefusal('embed_edit_bad_rows');
			try {
				return parse<EmbedChatItem[]>(binding.embed_group_updated_events(JSON.stringify(rows)));
			} catch (error) {
				throw new UnitRefusal(code(error));
			}
		}
	};
}

export function installEmbedEditUnit(context: UnitInstallContext, deps: EmbedEditDeps = defaultDeps()): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal || !isEmbedEditBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<EmbedEditProtocol>(port, createEmbedEditHandlers(context.binding, principal, deps, context.signal));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		stop();
		port.close();
	};
	function control(event: MessageEvent<unknown>): void {
		if (isEmbedEditUnitClose(event.data)) dispose();
	}
	port.addEventListener('message', control);
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
