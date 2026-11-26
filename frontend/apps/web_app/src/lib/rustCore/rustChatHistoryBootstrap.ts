// Feeds the normal ActiveChat history from the shared Rust core in
// VITE_OPENMATES_RUST_CORE builds. Imported only from the flag guard in
// routes/+page.svelte, so default builds contain none of this code.
//
// Rust (WASM Worker, in-memory second device of the existing TS login) reads and
// decrypts the opened saved chat; ActiveChat renders the mapped rows with the
// unchanged ChatHistory/ChatMessage UI. Send/stream/cancel stay on the TS path.
import { authStore, chatListCache, phasedSyncState, userProfile } from '@repo/ui';
import { isActiveTeamContext } from '@openmates/ui/src/stores/teamStore';
import { chatMetadataCache } from '@openmates/ui/src/services/chatMetadataCache';
import { activeChatStore } from '@openmates/ui/src/stores/activeChatStore';
import { getHashParam } from '@openmates/ui/src/utils/settingsHashUtils';
import { get } from 'svelte/store';
import { installRustChatHistorySource, rustFailureCode } from '@openmates/ui/src/services/rustCore/activeChatRustHistory';
import type { RustHistoryRead } from '@openmates/ui/src/services/rustCore/activeChatRustHistory';
import { coldReadToMessageWindow, isConfirmedEmptyLatestLocalWindow, localReadToMessageWindow, RustHistoryRefusal, savedReadToMessageWindow } from '@openmates/ui/src/services/rustCore/savedChatMessageRows';
import type { SavedPageSelector } from '@openmates/ui/src/services/rustCore/protocol';
import type { MessageWindowResult } from '@openmates/ui/src/services/db/messageOperations';
import type { LocalSavedChatSession, ProductionSavedChatSession } from '@openmates/ui/src/services/rustCore/secondDeviceSavedChatSession';
import type { SavedChatReadback, LocalChatReadback } from '@openmates/ui/src/services/rustCore/savedReadProtocol';
import { createRustCoreWorker, createRustLocalSession, createRustSecondDeviceSession, preloadRustAdmissionModules, prewarmRustCoreWorker } from './rustCoreLoader';
import { registerRustCoreWorkerFactory } from '@openmates/ui/src/services/rustCore/host/workerFactoryRegistry';
import { backsOffServerCheck, keepsLocalSessionAfterServerCheckFailure, SERVER_CHECK_BACKOFF_MS } from '@openmates/ui/src/services/rustCore/serverCheckFailure';
import { isRecoverableSelectedHistoryFailure, readSelectedCacheAcrossDisconnect } from '@openmates/ui/src/services/rustCore/selectedHistoryHostFailure';
import { getWorkspaceCacheIdentity } from '@openmates/ui/src/services/workspaceQueryCache';
import { registerSocketFrameSink } from '@openmates/ui/src/services/rustCore/socketFrameForwarder';
import { notifyServerCheckedSession, registerServerCheckedSession } from '@openmates/ui/src/services/rustCore/host/serverSessionRegistry';
import {
	installOpenedChatStartup, OPENED_CHAT_COVERAGE_EVENT,
} from '@openmates/ui/src/services/rustCore/startupOpenedChats';
import type { OpenedChatPage } from '@openmates/ui/src/services/rustCore/startupOpenedChats';
import {
	loadOpenedHistoryReceipts, saveOpenedHistoryReceipt,
} from '@openmates/ui/src/services/rustCore/browserOpenedHistoryReceipt';
import type { LegacyOpenedHistoryPage, OpenedHistoryPageWitness } from '@openmates/ui/src/services/db/openedHistoryStorage';

/** Measurement-only opt-out: lets one flag build record the TS baseline. */
import { usesOpenedChatStartup } from '@openmates/ui/src/config/api';
export { RUST_HISTORY_OPT_OUT_KEY } from '@openmates/ui/src/config/api';

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
	if (!usesOpenedChatStartup()) return unregisterWorker;
	// Load the shared Worker's single WASM instance now, in parallel with the remaining
	// boot work; admission later leases a core unit on that already-loaded Worker.
	markRustStage('history-install');
	prewarmRustCoreWorker();
	preloadRustAdmissionModules();
	const lifetime = new AbortController();
	const uninstallOpenedStartup = installOpenedChatStartup({
		loadReceipts: loadOpenedHistoryReceipts,
		saveReceipt: saveOpenedHistoryReceipt,
		async prepare(scope, signal) {
			// The owned IDB transcript writer currently admits Personal only.
			if (scope.teamId !== null) throw new Error('chat_unavailable');
			let target = '';
			let readGeneration = 0;
			const retained = await createRustSecondDeviceSession({
				signal, currentSelection: () => ({ chatId: target, selectionGeneration: readGeneration, revision: 0 }),
			});
			return {
				async read(chatId, selector) {
					target = chatId;
					readGeneration++;
					const result: { page?: OpenedChatPage; witness?: OpenedHistoryPageWitness; legacy?: LegacyOpenedHistoryPage } = {};
					await retained.publishColdPage((page) => {
						const live = page.coldLivePage;
						if (!live) throw new Error('chat_unavailable');
						result.page = {
							start: live.startCursor, hasMoreBefore: live.hasMoreBefore, hasMoreAfter: live.hasMoreAfter,
							messagesVersion: live.messagesVersion ?? null,
							serverMessageCount: live.serverMessageCount ?? null, retainedRows: page.rowDispositions.length,
							rowsConfirmed: page.rowDispositions.every(row => row.incomingSuppliedWriteFieldsMatch),
						};
					}, selector, observation => {
						if ('rows' in observation) result.legacy = observation;
						else result.witness = observation;
					});
					if (!result.page) throw new Error('chat_unavailable');
					return { ...result.page, witness: result.witness, legacy: result.legacy };
				},
				close: () => retained.close(),
			};
		},
		resume(chatId, scope) {
			const hash = window.location.hash;
			if (activeChatStore.get() || getHashParam(hash, 'chat-id') || getHashParam(hash, 'share-chat-id')) return;
			if (!get(authStore).isAuthenticated || !isActiveTeamContext(scope.teamId, scope.contextEpoch)) return;
			const owner = get(userProfile).user_id;
			const chat = chatListCache.getPendingOrCachedChat(chatId);
			if (!owner || chat?.user_id !== owner || (chat.team_id ?? null) !== scope.teamId ||
				chat.is_hidden || chat.is_hidden_candidate || chat.is_anonymous || chat.parent_id || chat.is_sub_chat) return;
			const metadata = chatMetadataCache.getFreshMetadata(chatId);
			if (metadata?.title) phasedSyncState.setResumeChatData(
				chat, metadata.title, metadata.category, metadata.icon, false, metadata.summary,
			);
		},
		coverage: (detail) => window.dispatchEvent(new CustomEvent(OPENED_CHAT_COVERAGE_EVENT, { detail })),
	});
	let session: ProductionSavedChatSession | null = null;
	let pending: Promise<ProductionSavedChatSession> | null = null;
	// Local-only admission (no server call) that serves the first cache-first
	// read while the TS server check is still in flight; upgraded on its Worker.
	let local: LocalSavedChatSession | null = null;
	let localPending: Promise<LocalSavedChatSession | null> | null = null;
	let localAttempted = false;
	// After an unreachable-server failure no new server check starts until then (or `online`).
	let serverCheckBlockedUntil = 0;
	let selected = '';
	let generation = 0;
	let latestWindowIntent = 0;
	let pendingWindow: {
		chatId: string;
		anchorMessageId: string | null;
		workspace: string | null;
		online: boolean;
		result: Promise<RustHistoryRead>;
	} | null = null;
	let activeColdRead: { chatId: string; workspace: string | null; stop: AbortController } | null = null;
	// The admitted session refuses concurrent reads ("busy"); reads are serialized.
	let queue: Promise<unknown> = Promise.resolve();

	const currentSelection = () => ({ chatId: selected, selectionGeneration: generation, revision: 0 });

	/** A transport loss can retire the server-checked Worker. Reopen the
	 * existing local-only admission while offline so the next cached chat can
	 * be read without waiting for a network check. */
	const ensureLocal = (offlineSelection = false): Promise<LocalSavedChatSession | null> => {
		if (local && !local.signal.aborted) return Promise.resolve(local);
		if (localPending) return localPending;
		if (!offlineSelection && navigator.onLine && ((session && !session.signal.aborted) || pending || localAttempted)) {
			return Promise.resolve(null);
		}
		return startLocal();
	};

	const startLocal = (): Promise<LocalSavedChatSession | null> => {
		if (localPending) return localPending;
		localAttempted = true;
		markRustStage('local-session-start');
		const started = createRustLocalSession({ signal: lifetime.signal, currentSelection })
			.then((created) => { local = created; markRustStage('local-session-ready'); return created; },
				(error: unknown) => { console.warn('[RustCore] local admission failed:', rustFailureCode(error)); return null; })
			.finally(() => { if (localPending === started) localPending = null; });
		localPending = started;
		return started;
	};

	/** One server-checked admission; the first one upgrades the local session on its
	 * Worker. The upgrade hands the Worker over without advancing the shared profile
	 * lifecycle, so it no longer cancels its own freshly prepared platform snapshot.
	 * Safety net only: a snapshot superseded by an EXTERNAL revocation while admitting
	 * (`cancelled`/`invalidated_snapshot`: another tab's profile/credential change, a
	 * workspace clear, or the local session failing under the upgrade) is re-admitted
	 * ONCE on a fresh platform snapshot, which re-checks auth and refuses a logged-out
	 * or switched profile. Any other failure, or a second supersede, propagates. */
	const admit = async (): Promise<ProductionSavedChatSession> => {
		const admitted = await (localPending ?? Promise.resolve(local));
		const upgrading = admitted && !admitted.signal.aborted ? admitted : null;
		try {
			return await createRustSecondDeviceSession({ signal: lifetime.signal, currentSelection, local: upgrading, observeSelectedAdmission: true, reusePageAdmission: true });
		} catch (error) {
			const code = rustFailureCode(error);
			if (lifetime.signal.aborted || (code !== 'cancelled' && code !== 'invalidated_snapshot')) throw error;
			markRustStage(`session-readmit-${code}`);
			return createRustSecondDeviceSession({ signal: lifetime.signal, currentSelection, local: null, observeSelectedAdmission: true, reusePageAdmission: true });
		}
	};

	/** One live session; re-admitted lazily after a failure closed the previous one. */
	const ensureSession = (): Promise<ProductionSavedChatSession> => {
		if (session && !session.signal.aborted) return Promise.resolve(session);
		if (!navigator.onLine || (!pending && Date.now() < serverCheckBlockedUntil)) return Promise.reject(new Error('unavailable'));
		if (!pending) markRustStage('session-start');
		pending ??= admit()
			.then((created) => { session = created; markRustStage('session-ready'); notifyServerCheckedSession(); return created; },
				(error: unknown) => {
					const code = rustFailureCode(error);
					markRustStage(`session-failed-${code}`);
					console.warn('[RustCore] session admission failed:', code);
					// A failed upgrade closed the local session's Worker. When only the network
					// failed, restore a fresh local session BEFORE reporting the failure so the
					// offline-capable units (drafts) never see a window without an admitted client,
					// and hold further server checks back so a retry cannot tear it down again.
					// A server rejection (revoked/expired session) keeps nothing local.
					if (keepsLocalSessionAfterServerCheckFailure(code) && !lifetime.signal.aborted) {
						if (backsOffServerCheck(code)) serverCheckBlockedUntil = Date.now() + SERVER_CHECK_BACKOFF_MS;
						local = null; localPending = null;
						return startLocal().then(() => { throw error; });
					}
					throw error;
				})
			.finally(() => { pending = null; });
		return pending;
	};

	/** Refresh the selected latest window through the admitted Rust writer, which
	 * validates the original encrypted response and re-reads the committed rows.
	 * This also retains a newer tail when an older local window rendered first. */
	const assertWindowIntent = (intent: number, workspace: string | null): void => {
		if (lifetime.signal.aborted || intent !== latestWindowIntent ||
			(workspace !== null && getWorkspaceCacheIdentity() !== workspace)) throw new Error('cancelled');
	};
	const serverRead = async (chatId: string, anchorMessageId: string | null, intent: number,
		workspace: string | null, recoveringOwner?: string): Promise<MessageWindowResult> => {
		const currentIntent = () => {
			assertWindowIntent(intent, workspace);
			if (!navigator.onLine) throw new Error('chat_unavailable');
		};
		currentIntent();
		let owner = await ensureSession();
		currentIntent();
		if (recoveringOwner && owner.status.principal !== recoveringOwner) throw new Error('invalidated_snapshot');
		selected = chatId;
		generation++;
		if (anchorMessageId === null && !recoveringOwner) {
			const principal = owner.status.principal;
			let retained: MessageWindowResult | null = null;
			const cold = { chatId, workspace, stop: new AbortController() };
			activeColdRead = cold;
			try {
				await owner.publishColdPage(page => { retained = coldReadToMessageWindow(page, chatId); },
					undefined, undefined, cold.stop.signal);
			} catch (error) {
				// The compatibility view is an independently authorized read. It never
				// retries a rejected storage plan or consumes its data.
				if (!isRecoverableSelectedHistoryFailure(error)) throw error;
			} finally {
				if (activeColdRead === cold) activeColdRead = null;
			}
			assertWindowIntent(intent, workspace);
			if (retained) return retained;
			currentIntent();
			owner = await ensureSession();
			currentIntent();
			if (owner.status.principal !== principal) throw new Error('invalidated_snapshot');
		}
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
		assertWindowIntent(intent, workspace);
		const published = page as SavedChatReadback | LocalChatReadback | null;
		if (!published || !isSavedRead(published)) throw new Error('protocol');
		markRustStage('server-read-end');
		return savedReadToMessageWindow(published, chatId, anchorMessageId !== null);
	};

	/** Canonical Rust page for a chained selector (cursor from the previous Rust window). */
	const pageRead = async (chatId: string, selector: SavedPageSelector): Promise<MessageWindowResult> => {
		if (!navigator.onLine) throw new Error('unavailable');
		const owner = await ensureSession();
		if (!navigator.onLine) throw new Error('unavailable');
		selected = chatId;
		generation++;
		markRustStage('page-read-start');
		let page: SavedChatReadback | LocalChatReadback | null = null;
		try {
			await owner.publishPage(selector, (published) => { page = published; });
		} catch (error) {
			if (rustFailureCode(error) === 'unavailable') throw new RustHistoryRefusal('unsupported_view');
			throw error;
		}
		const published = page as SavedChatReadback | LocalChatReadback | null;
		if (!published || !isSavedRead(published)) throw new Error('protocol');
		markRustStage('page-read-end');
		return savedReadToMessageWindow(published, chatId, selector.direction === 'around');
	};

	const enqueue = <T>(task: () => Promise<T>): Promise<T> => {
		if (lifetime.signal.aborted) return Promise.reject(new Error('cancelled'));
		const run = queue.then(task);
		queue = run.catch(() => undefined);
		return run;
	};

	/** A delayed repair cannot retarget a newer open or retire a usable offline session. */
	const reconcileWindow = (chatId: string, anchorMessageId: string | null, intent: number, workspace: string | null) =>
		afterRender().then(() => enqueue(() => {
			return serverRead(chatId, anchorMessageId, intent, workspace);
		}));

	/**
	 * Cache-first, like the TS IndexedDB path: Rust decrypts the existing retained
	 * rows; the server page reconciles in the background. A cache miss (no or
	 * unsupported retained rows, anchor not retained) reads the server directly.
	 */
	const read = async (chatId: string, anchorMessageId: string | null, intent: number,
		workspace: string | null): Promise<RustHistoryRead> => {
		assertWindowIntent(intent, workspace);
		const readOffline = async (): Promise<RustHistoryRead> => {
			assertWindowIntent(intent, workspace);
			const admitted = await ensureLocal(true);
			assertWindowIntent(intent, workspace);
			markRustStage(admitted && !admitted.signal.aborted ? 'read-local-session' : 'read-no-local-session');
			if (admitted && !admitted.signal.aborted) {
				const { read } = await readLocal(admitted, chatId, anchorMessageId, intent, workspace);
				assertWindowIntent(intent, workspace);
				if (read) return read;
			}
			throw new Error('chat_unavailable');
		};
		if (!navigator.onLine) return readOffline();
		const early = session && !session.signal.aborted ? null : await ensureLocal();
		assertWindowIntent(intent, workspace);
		markRustStage(session && !session.signal.aborted ? 'read-online-session' : early && !early.signal.aborted ? 'read-local-session' : 'read-no-local-session');
		if (early && !early.signal.aborted) {
			const { read: result, confirmedEmptyLatest } = await readLocal(early, chatId, anchorMessageId, intent, workspace);
			assertWindowIntent(intent, workspace);
			// Server check (upgrade) on the same Worker, started only once the page is idle
			// after the cached rows rendered, so its page-side IDB checks never contend
			// with the cached read or the render (TS ordering: cache first).
			if (result) {
				if (navigator.onLine) {
					void afterRender().then(() => {
						if (navigator.onLine && !lifetime.signal.aborted) return ensureSession();
					}).catch(() => undefined);
				}
				return result;
			}
			if (confirmedEmptyLatest && workspace !== null) {
				if (!navigator.onLine) return readOffline();
				markRustStage('local-cache-empty-latest');
				// The same scoped latest cache was just read. A concurrently
				// admitted online session authorizes the canonical page only.
				return { window: await serverRead(chatId, null, intent, workspace), source: 'server', reconcile: null };
			}
		}
		const owner = session && !session.signal.aborted ? session : null;
		if (!navigator.onLine) return readOffline();
		if (!owner) return { window: await serverRead(chatId, anchorMessageId, intent, workspace), source: 'server', reconcile: null };
		selected = chatId;
		generation++;
		let cached: RustHistoryRead | null;
		try {
			cached = await readSelectedCacheAcrossDisconnect({
				isOnline: () => navigator.onLine,
				listenOffline: abort => {
					window.addEventListener('offline', abort);
					return () => window.removeEventListener('offline', abort);
				},
			}, async signal => {
				markRustStage('cache-read-start');
				let read: LocalChatReadback | null = null;
				try {
					await owner.publishCachedPage(anchorMessageId ? { direction: 'around', anchorMessageId } : { direction: 'latest' },
						published => { read = published; }, signal);
				} catch (error) {
					if (rustFailureCode(error) !== 'chat_unavailable') throw error;
				}
				assertWindowIntent(intent, workspace);
				markRustStage('cache-read-end');
				const page = read as LocalChatReadback | null;
				if (!page || !page.chat.messages.length || (anchorMessageId !== null && !page.anchorFound)) {
					markRustStage(!page ? 'cache-miss-unavailable' : !page.chat.messages.length ? 'cache-miss-empty' : 'cache-miss-anchor');
					return null;
				}
				return { window: localReadToMessageWindow(page, chatId, anchorMessageId !== null), source: 'cache',
					reconcile: navigator.onLine ? () => reconcileWindow(chatId, anchorMessageId, intent, workspace) : null };
			}, readOffline);
		} catch (error) {
			if (!isRecoverableSelectedHistoryFailure(error) || !workspace || getWorkspaceCacheIdentity() !== workspace) throw error;
			// The cache host authorized no data. The current intent gets one independent canonical read.
			return { window: await serverRead(chatId, anchorMessageId, intent, workspace, owner.status.principal),
				source: 'server', reconcile: null };
		}
		assertWindowIntent(intent, workspace);
		if (cached) return cached;
		if (!navigator.onLine) return readOffline();
		return { window: await serverRead(chatId, anchorMessageId, intent, workspace), source: 'server', reconcile: null };
	};

	/** A closed or unsupported local read does not establish an empty latest window. */
	const readLocal = async (owner: LocalSavedChatSession, chatId: string, anchorMessageId: string | null,
		intent: number, workspace: string | null): Promise<{ read: RustHistoryRead | null; confirmedEmptyLatest: boolean }> => {
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
			return { read: null, confirmedEmptyLatest: false };
		}
		markRustStage('cache-read-end');
		const page = cached as LocalChatReadback | null;
		if (!page || page.chat.messages.length === 0 || (anchorMessageId !== null && !page.anchorFound)) {
			return { read: null, confirmedEmptyLatest: isConfirmedEmptyLatestLocalWindow(page, chatId, anchorMessageId) };
		}
		return { read: { window: localReadToMessageWindow(page, chatId, anchorMessageId !== null), source: 'cache',
			reconcile: navigator.onLine ? () => reconcileWindow(chatId, anchorMessageId, intent, workspace) : null },
			confirmedEmptyLatest: false };
	};

	// A user-pressed server write of a sibling unit (embed edits) refused on the
	// local-only session asks for this same server-checked upgrade, e.g. in a chat
	// created after login, which never needed a server read. Chat-open work never
	// asks for it; it waits for `notifyServerCheckedSession`.
	const onOnline = () => {
		serverCheckBlockedUntil = 0;
		void afterRender().then(() => {
			const auth = get(authStore);
			if (navigator.onLine && auth.isAuthenticated && auth.isInitialized && !lifetime.signal.aborted) {
				return ensureSession();
			}
		}).catch(() => undefined);
	};
	window.addEventListener('online', onOnline);
	const unregisterServerSession = registerServerCheckedSession(() => ensureSession().then(() => undefined));

	// Server frames go to the core only through a live server-checked session; the
	// shared queue keeps them ordered behind reads (the Worker serves one request at a time).
	const unregisterFrameSink = registerSocketFrameSink({
		hasServerSession: () => !!session && !session.signal.aborted,
		hasLocalSession: () => !!local && !local.signal.aborted,
		ensureServerSession: () => ensureSession().then(() => undefined),
		ingest: (frames) => enqueue(() => session && !session.signal.aborted ? session.ingestSocketFrames(frames) : Promise.reject(new Error('session_expired'))),
		admit: (chatId, teamId) => enqueue(() => {
			// Admission stage marker (see socketFrameForwarder.markAdmit): past the page read queue, Worker op in flight.
			document.documentElement.dataset.rustCoreAdmit = 'worker';
			return session && !session.signal.aborted ? session.admitChat(chatId, teamId) : Promise.reject(new Error('session_expired'));
		})
	});
	const uninstall = installRustChatHistorySource({
		readWindow: ({ chatId, anchorMessageId }) => {
			const workspace = getWorkspaceCacheIdentity();
			const online = navigator.onLine;
			// Boot can redispatch the exact selected view during auth settlement.
			// Keep its in-flight read and leave each caller's view generation guard in place.
			if (!lifetime.signal.aborted && workspace !== null && pendingWindow?.workspace === workspace &&
				pendingWindow.chatId === chatId && pendingWindow.anchorMessageId === anchorMessageId &&
				pendingWindow.online === online) {
				markRustStage('history-joined-pending');
				return pendingWindow.result;
			}
			if (workspace !== null && pendingWindow?.workspace === workspace && pendingWindow.chatId !== chatId) {
				markRustStage('history-replaced-pending-target');
			}
			const intent = ++latestWindowIntent;
			// Only a different selected chat in this scope can stop the old
			// owned cold read. The serial queue still waits for its actual drain.
			if (workspace !== null && activeColdRead?.workspace === workspace && activeColdRead.chatId !== chatId) {
				activeColdRead.stop.abort();
			}
			const result = enqueue(() => read(chatId, anchorMessageId, intent, workspace)).finally(() => {
				if (pendingWindow?.result === result) pendingWindow = null;
			});
			pendingWindow = { chatId, anchorMessageId, workspace, online, result };
			return result;
		},
		readPage: ({ chatId, selector }) => enqueue(() => pageRead(chatId, selector))
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
	return () => { window.removeEventListener('online', onOnline); stopAuth(); uninstall(); unregisterServerSession(); unregisterFrameSink(); uninstallOpenedStartup(); lifetime.abort(); local?.close(); session?.close(); unregisterWorker(); };
}
