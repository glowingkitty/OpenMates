// Feeds the normal ActiveChat history from the shared Rust core in
// VITE_OPENMATES_RUST_CORE builds. Imported only from the flag guard in
// routes/+page.svelte, so default builds contain none of this code.
//
// Rust (WASM Worker, in-memory second device of the existing TS login) reads and
// decrypts the opened saved chat; ActiveChat renders the mapped rows with the
// unchanged ChatHistory/ChatMessage UI. Send/stream/cancel stay on the TS path.
import { authStore } from '@repo/ui';
import { installRustChatHistorySource, rustFailureCode } from '@openmates/ui/src/services/rustCore/activeChatRustHistory';
import type { RustHistoryRead } from '@openmates/ui/src/services/rustCore/activeChatRustHistory';
import { localReadToMessageWindow, RustHistoryRefusal, savedReadToMessageWindow } from '@openmates/ui/src/services/rustCore/savedChatMessageRows';
import type { MessageWindowResult } from '@openmates/ui/src/services/db/messageOperations';
import type { LocalSavedChatSession, ProductionSavedChatSession } from '@openmates/ui/src/services/rustCore/secondDeviceSavedChatSession';
import type { SavedChatReadback, LocalChatReadback } from '@openmates/ui/src/services/rustCore/savedReadProtocol';
import { createRustCoreWorker, createRustLocalSession, createRustSecondDeviceSession, preloadRustAdmissionModules, prewarmRustCoreWorker } from './rustCoreLoader';
import { registerRustCoreWorkerFactory } from '@openmates/ui/src/services/rustCore/host/workerFactoryRegistry';

/** Measurement-only opt-out: lets one flag build record the TS baseline. */
export const RUST_HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';

function isSavedRead(page: SavedChatReadback | LocalChatReadback): page is SavedChatReadback {
	return 'serverMessageCount' in page;
}

/** Stage marks (fixed names, no content) for the open-to-rendered breakdown. */
export function markRustStage(stage: string): void {
	if (typeof performance !== 'undefined') performance.mark(`openmates:rust:${stage}`);
}

/**
 * Resolves once the page is idle after the current open (bounded), so background
 * work (server-checked upgrade, reconcile) never competes with the cached rows'
 * render for the main thread or the origin's IndexedDB. TS ordering: cache first.
 */
const BACKGROUND_IDLE_TIMEOUT_MS = 1000;
function afterRender(): Promise<void> {
	return new Promise((resolve) => {
		if (typeof requestIdleCallback === 'function') requestIdleCallback(() => resolve(), { timeout: BACKGROUND_IDLE_TIMEOUT_MS });
		// Engines without idle callbacks (Safari): after the next paint.
		else requestAnimationFrame(() => setTimeout(resolve, 0));
	});
}

/** Returns a disposer; safe to call once per page mount. */
export function installRustChatHistory(): () => void {
	// Rust-core services in @openmates/ui (drafts) obtain the Worker through this registry.
	const unregisterWorker = registerRustCoreWorkerFactory(createRustCoreWorker);
	if (localStorage.getItem(RUST_HISTORY_OPT_OUT_KEY) === 'ts') return unregisterWorker;
	// Load the shared Worker's single WASM instance now, in parallel with the remaining
	// boot work; admission later leases a core unit on that already-loaded Worker.
	markRustStage('history-install');
	prewarmRustCoreWorker();
	preloadRustAdmissionModules();
	const lifetime = new AbortController();
	let session: ProductionSavedChatSession | null = null;
	let pending: Promise<ProductionSavedChatSession> | null = null;
	// Local-only admission (no server call) that serves the first cache-first
	// read while the TS server check is still in flight; upgraded on its Worker.
	let local: LocalSavedChatSession | null = null;
	let localPending: Promise<LocalSavedChatSession | null> | null = null;
	let localAttempted = false;
	let selected = '';
	let generation = 0;
	// The admitted session refuses concurrent reads ("busy"); reads are serialized.
	let queue: Promise<unknown> = Promise.resolve();

	const currentSelection = () => ({ chatId: selected, selectionGeneration: generation, revision: 0 });

	/** At most one local admission per page load, only before the first server-checked one. */
	const ensureLocal = (): Promise<LocalSavedChatSession | null> => {
		if (local && !local.signal.aborted) return Promise.resolve(local);
		if (localAttempted) return localPending?.then((admitted) => admitted && !admitted.signal.aborted ? admitted : null) ?? Promise.resolve(null);
		if (session || pending) return Promise.resolve(null);
		localAttempted = true;
		markRustStage('local-session-start');
		localPending = createRustLocalSession({ signal: lifetime.signal, currentSelection })
			.then((created) => { local = created; markRustStage('local-session-ready'); return created; },
				(error: unknown) => { console.warn('[RustCore] local admission failed:', rustFailureCode(error)); return null; });
		return localPending;
	};

	/** One server-checked admission; the first one upgrades the local session on its
	 * Worker. A snapshot superseded while admitting (`cancelled`/`invalidated_snapshot`:
	 * the TS profile lifecycle moved, e.g. a post-sync profile write, or the local
	 * session closed under the upgrade) is re-admitted ONCE on a fresh platform
	 * snapshot and Worker lease. Any other failure, or a second supersede, propagates. */
	const admit = async (): Promise<ProductionSavedChatSession> => {
		const admitted = await (localPending ?? Promise.resolve(null));
		const upgrading = admitted && !admitted.signal.aborted ? admitted : null;
		try {
			return await createRustSecondDeviceSession({ signal: lifetime.signal, currentSelection, local: upgrading });
		} catch (error) {
			const code = rustFailureCode(error);
			if (lifetime.signal.aborted || (code !== 'cancelled' && code !== 'invalidated_snapshot')) throw error;
			markRustStage(`session-readmit-${code}`);
			return createRustSecondDeviceSession({ signal: lifetime.signal, currentSelection, local: null });
		}
	};

	/** One live session; re-admitted lazily after a failure closed the previous one. */
	const ensureSession = (): Promise<ProductionSavedChatSession> => {
		if (session && !session.signal.aborted) return Promise.resolve(session);
		if (!pending) markRustStage('session-start');
		pending ??= admit()
			.then((created) => { session = created; markRustStage('session-ready'); return created; },
				(error: unknown) => {
					const code = rustFailureCode(error);
					markRustStage(`session-failed-${code}`);
					console.warn('[RustCore] session admission failed:', code);
					throw error;
				})
			.finally(() => { pending = null; });
		return pending;
	};

	/** Canonical Rust server page (foreground on a cache miss, else background reconcile). */
	const serverRead = async (chatId: string, anchorMessageId: string | null): Promise<MessageWindowResult> => {
		const owner = await ensureSession();
		selected = chatId;
		generation++;
		markRustStage('server-read-start');
		let page: SavedChatReadback | LocalChatReadback | null = null;
		try {
			await owner.publishPage(anchorMessageId ? { direction: 'around', anchorMessageId } : { direction: 'latest' },
				(published) => { page = published; });
		} catch (error) {
			// Reads are serialized, so a read-stage "unavailable" is Rust's explicit
			// unsupported-view refusal (role/queue shape), not a busy session.
			if (rustFailureCode(error) === 'unavailable') throw new RustHistoryRefusal('unsupported_view');
			throw error;
		}
		const published = page as SavedChatReadback | LocalChatReadback | null;
		if (!published || !isSavedRead(published)) throw new Error('protocol');
		markRustStage('server-read-end');
		return savedReadToMessageWindow(published, chatId, anchorMessageId !== null);
	};

	const enqueue = <T>(task: () => Promise<T>): Promise<T> => {
		if (lifetime.signal.aborted) return Promise.reject(new Error('cancelled'));
		const run = queue.then(task);
		queue = run.catch(() => undefined);
		return run;
	};

	/**
	 * Cache-first, like the TS IndexedDB path: Rust decrypts the existing retained
	 * rows; the server page reconciles in the background. A cache miss (no or
	 * unsupported retained rows, anchor not retained) reads the server directly.
	 */
	const read = async (chatId: string, anchorMessageId: string | null): Promise<RustHistoryRead> => {
		const early = session && !session.signal.aborted ? null : await ensureLocal();
		markRustStage(session && !session.signal.aborted ? 'read-online-session' : early && !early.signal.aborted ? 'read-local-session' : 'read-no-local-session');
		if (early && !early.signal.aborted) {
			const result = await readLocal(early, chatId, anchorMessageId);
			// Server check (upgrade) on the same Worker, started only once the page is idle
			// after the cached rows rendered, so its page-side IDB checks never contend
			// with the cached read or the render (TS ordering: cache first).
			if (result) {
				void afterRender().then(() => lifetime.signal.aborted ? undefined : ensureSession()).catch(() => undefined);
				return result;
			}
		}
		const owner = await ensureSession();
		selected = chatId;
		generation++;
		markRustStage('cache-read-start');
		let cached: LocalChatReadback | null = null;
		try {
			await owner.publishCachedPage(anchorMessageId ? { direction: 'around', anchorMessageId } : { direction: 'latest' },
				(published) => { cached = published; });
		} catch (error) {
			if (rustFailureCode(error) !== 'chat_unavailable') throw error;
		}
		markRustStage('cache-read-end');
		const page = cached as LocalChatReadback | null;
		if (page && page.chat.messages.length > 0 && (anchorMessageId === null || page.anchorFound)) {
			return { window: localReadToMessageWindow(page, chatId, anchorMessageId !== null), source: 'cache',
				reconcile: () => afterRender().then(() => enqueue(() => serverRead(chatId, anchorMessageId))) };
		}
		markRustStage(!page ? 'cache-miss-unavailable' : page.chat.messages.length === 0 ? 'cache-miss-empty' : 'cache-miss-anchor');
		return { window: await serverRead(chatId, anchorMessageId), source: 'server', reconcile: null };
	};

	/** Cache-first page from the local-only session; null on a miss (server read decides). */
	const readLocal = async (owner: LocalSavedChatSession, chatId: string, anchorMessageId: string | null): Promise<RustHistoryRead | null> => {
		selected = chatId;
		generation++;
		markRustStage('cache-read-start');
		let cached: LocalChatReadback | null = null;
		try {
			await owner.publishCachedPage(anchorMessageId ? { direction: 'around', anchorMessageId } : { direction: 'latest' },
				(published) => { cached = published; });
		} catch (error) {
			// Any non-miss failure closed the local session; the server-checked path decides.
			const code = rustFailureCode(error);
			markRustStage(code === 'chat_unavailable' ? 'local-cache-miss' : `local-cache-failed-${code}`);
			return null;
		}
		markRustStage('cache-read-end');
		const page = cached as LocalChatReadback | null;
		if (!page || page.chat.messages.length === 0 || (anchorMessageId !== null && !page.anchorFound)) return null;
		return { window: localReadToMessageWindow(page, chatId, anchorMessageId !== null), source: 'cache',
			reconcile: () => afterRender().then(() => enqueue(() => serverRead(chatId, anchorMessageId))) };
	};

	const uninstall = installRustChatHistorySource({
		readWindow: ({ chatId, anchorMessageId }) => enqueue(() => read(chatId, anchorMessageId))
	});

	// Admit as soon as the TS login is ready so the first chat open does not pay
	// for Worker/WASM startup. Failures are logged; the next read retries.
	const stopAuth = authStore.subscribe((state) => {
		// TS sets these optimistically from local data before its server check;
		// the local admission needs no server call. With a local session the
		// server-checked upgrade starts from read() right after its cached read, so
		// its platform/profile IDB checks do not contend with that read on the page.
		if (state.isAuthenticated && state.isInitialized && !lifetime.signal.aborted) {
			void ensureLocal().then((admitted) => admitted && !admitted.signal.aborted ? undefined : ensureSession())
				.catch(() => undefined);
		}
	});
	return () => { stopAuth(); uninstall(); lifetime.abort(); local?.close(); session?.close(); unregisterWorker(); };
}
