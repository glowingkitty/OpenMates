/**
 * Browser effect adapter for Rust's explicit-open and startup history policy.
 * No transcript data passes through the readiness/coverage callbacks.
 */
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from '../workspaceCacheLifecycle';
import type { OpenedHistoryCompletion, OpenedHistoryCursor, OpenedHistorySelector } from './persist/persistProtocol';
import { LEGACY_COVERAGE_ROW_LIMIT } from '../db/openedHistoryStorage';
import type { LegacyOpenedHistoryPage, OpenedHistoryPageWitness } from '../db/openedHistoryStorage';
import type { OpenedHistoryStoredState } from './browserOpenedHistoryReceipt';

export interface OpenedChatStartupScope { teamId: string | null; contextEpoch: number }
export interface OpenedChatPage {
	start: OpenedHistoryCursor | null;
	hasMoreBefore: boolean;
	hasMoreAfter: boolean;
	rowsConfirmed: boolean;
	retainedRows: number;
	serverMessageCount: number | null;
	messagesVersion: number | null;
	witness?: OpenedHistoryPageWitness;
	legacy?: LegacyOpenedHistoryPage;
}

export interface OpenedChatStartupAdapter {
	prepare(scope: OpenedChatStartupScope, signal: AbortSignal): Promise<{
		read(chatId: string, selector: OpenedHistorySelector): Promise<OpenedChatPage>;
		close(): void;
	}>;
	loadReceipts?(ids: readonly string[], scope: OpenedChatStartupScope, signal: AbortSignal):
		Promise<Map<string, OpenedHistoryStoredState> | null>;
	saveReceipt?(chatId: string, scope: OpenedChatStartupScope, signal: AbortSignal,
		witness: OpenedHistoryPageWitness, complete: OpenedHistoryCompletion): Promise<void>;
	resume?(chatId: string, scope: OpenedChatStartupScope): void;
	coverage?(evidence: Readonly<{ newestTail: boolean; completeChats: number; requestedChats: number }>): void;
}

export const OPENED_CHAT_COVERAGE_EVENT = 'openmates:opened-chat-coverage';

interface RetainedProgress {
	readonly selector: OpenedHistorySelector | null;
	readonly expectedVersion: number | null;
	readonly retainedRows: number;
	readonly verifiedConnection: number;
	readonly witness?: OpenedHistoryPageWitness;
	readonly legacy?: boolean;
}

interface StartupOffer {
	readonly ids: string[];
	readonly scope: OpenedChatStartupScope;
	readonly epoch: number;
	readonly connectionEpoch: number;
	readonly messagesVersions: unknown;
	readonly deadline: number;
	readonly progress: Map<string, RetainedProgress>;
	resumePublished: boolean;
	refreshHead: boolean;
	pagesRead: number;
}

let adapter: OpenedChatStartupAdapter | null = null;
let startup: AbortController | null = null;
let offered: StartupOffer | null = null;
let disconnectedThrough = -1;
let manualEpoch: number | null = null;
let pendingForeground: string | null = null;
let renderedChat: string | null = null;
let navigationRevision = 0;
let explicitOpenTail = Promise.resolve<boolean>(false);

function clearOffer(): void {
	renderedChat = null;
	pendingForeground = null;
	offered = null;
	startup?.abort();
}

registerWorkspaceCacheClear(clearOffer);

export function installOpenedChatStartup(next: OpenedChatStartupAdapter): () => void {
	if (adapter && adapter !== next) clearOffer();
	adapter = next;
	if (offered) void runOpenedChatStartup(offered).catch(() => {});
	return () => {
		if (adapter !== next) return;
		adapter = null;
		clearOffer();
	};
}

/** Revoke this socket's effect lease while preserving confirmed Rust progress. */
export function suspendOpenedChatStartup(connectionEpoch: number): void {
	disconnectedThrough = Math.max(disconnectedThrough, connectionEpoch);
	if (offered && offered.connectionEpoch <= disconnectedThrough) startup?.abort();
}

export function cancelOpenedChatStartup(chatId?: string): void {
	manualEpoch = getWorkspaceCacheEpoch();
	// A blocked server read can outlive an idle callback. Hold the prefetch
	// lease until this deliberate selection has actually reached its view.
	pendingForeground = chatId && chatId !== renderedChat ? chatId : null;
	navigationRevision++;
	startup?.abort();
}

/** Called by the mounted transcript after a selected window or its inline
 * empty/error state has had an opportunity to paint. Stale paints from an
 * earlier click do not release the current foreground read. */
export function reportOpenedChatFrame(chatId: string | null): void {
	renderedChat = chatId;
	if (!chatId || pendingForeground !== chatId) return;
	pendingForeground = null;
	if (offered) void runOpenedChatStartup(offered).catch(() => {});
}

export function openedChatStartupAvailable(): boolean {
	return adapter !== null;
}

/** Called only for an intentional navigation to an already admitted saved chat. */
export function recordOpenedChat(chatId: string, teamId: string | null): Promise<boolean> {
	const workspaceEpoch = getWorkspaceCacheEpoch();
	const task = explicitOpenTail.catch(() => false).then(async () => {
		const [{ isActiveTeamContext, getActiveTeamContextSnapshot }, { persistCall }, { getApiEndpoint }, auth, signup, { get }] =
			await Promise.all([
				import('../../stores/teamStore'), import('./persist/persistUnitClient'), import('../../config/api'),
				import('../../stores/authStore'), import('../../stores/signupState'), import('svelte/store'),
			]);
		const contextEpoch = getActiveTeamContextSnapshot().epoch;
		const isCurrent = () => get(auth.authStore).isAuthenticated && !get(signup.forcedLogoutInProgress) &&
			workspaceEpoch === getWorkspaceCacheEpoch() && isActiveTeamContext(teamId, contextEpoch);
		if (!isCurrent()) return false;
		const binding = await persistCall('startupOpened', { kind: 'record', chatId, teamId });
		if (!('path' in binding) || !isCurrent()) return false;
		const signal = new AbortController();
		const timeout = window.setTimeout(() => signal.abort(), 10_000);
		const unregister = registerWorkspaceCacheClear(() => signal.abort());
		try {
			const response = await fetch(getApiEndpoint(binding.path), {
				method: 'POST', credentials: 'include', signal: signal.signal,
			});
			return isCurrent() && response.ok && (await response.json()).recorded === true && isCurrent();
		} finally {
			window.clearTimeout(timeout);
			unregister();
		}
	});
	explicitOpenTail = task;
	return task;
}

function yieldIdle(signal: AbortSignal): Promise<void> {
	return new Promise((resolve, reject) => {
		if (signal.aborted) { reject(new Error('cancelled')); return; }
		const onAbort = () => { cancel(); reject(new Error('cancelled')); };
		const done = () => { signal.removeEventListener('abort', onAbort); resolve(); };
		const idle = typeof requestIdleCallback === 'function';
		const id = idle ? requestIdleCallback(done, { timeout: 1000 }) : window.setTimeout(done, 0);
		const cancel = () => idle ? cancelIdleCallback(id) : window.clearTimeout(id);
		signal.addEventListener('abort', onAbort, { once: true });
	});
}

/** Phase 1a offers ordered IDs on an authenticated, scoped socket. An offer
 * can wait for the Worker adapter, or supersede an interrupted socket's work. */
export async function offerOpenedChatStartup(
	ids: readonly string[], scope: OpenedChatStartupScope, connectionEpoch: number,
	messagesVersions: unknown = null,
): Promise<void> {
	const epoch = getWorkspaceCacheEpoch();
	if (connectionEpoch <= disconnectedThrough || (offered && connectionEpoch < offered.connectionEpoch)) return;
	const previous = offered?.epoch === epoch && offered.scope.teamId === scope.teamId &&
		offered.scope.contextEpoch === scope.contextEpoch ? offered : null;
	const sameIds = previous !== null && previous.ids.length === ids.length && ids.every((id, index) => previous.ids[index] === id);
	if (sameIds && previous.connectionEpoch === connectionEpoch) return;

	const next: StartupOffer = {
		ids: [...ids], scope: { ...scope }, epoch, connectionEpoch, messagesVersions,
		deadline: Date.now() + 120_000, progress: new Map(), pagesRead: 0,
		resumePublished: previous !== null && previous.ids[0] === ids[0] && previous.resumePublished,
		refreshHead: previous !== null && (previous.ids[0] === ids[0] ? previous.refreshHead : previous.progress.has(ids[0])),
	};
	for (const id of ids) {
		const retained = previous?.progress.get(id);
		if (retained) next.progress.set(id, retained);
	}

	offered = next;
	startup?.abort();
	await runOpenedChatStartup(next);
}

async function runOpenedChatStartup(offer: StartupOffer): Promise<void> {
	const origin = adapter;
	const { epoch, scope, connectionEpoch } = offer;
	const current = () => offered === offer && adapter === origin &&
		epoch === getWorkspaceCacheEpoch() && connectionEpoch > disconnectedThrough;
	if (!origin || startup || pendingForeground || !current() || Date.now() >= offer.deadline) return;
	const revision = navigationRevision;
	const run = new AbortController();
	startup = run;
	const check = () => {
		if (run.signal.aborted || !current()) throw new Error('cancelled');
	};
	const timeout = window.setTimeout(() => run.abort(), Math.max(0, offer.deadline - Date.now()));
	let reader: Awaited<ReturnType<OpenedChatStartupAdapter['prepare']>> | null = null;
	try {
		const [{ persistCall }, { isActiveTeamContext }] = await Promise.all([
			import('./persist/persistUnitClient'), import('../../stores/teamStore'),
		]);
		check();
		if (!isActiveTeamContext(scope.teamId, scope.contextEpoch)) return;
		const publishResume = (head: string | undefined) => {
			if (!head || manualEpoch === epoch || offer.resumePublished) return;
			offer.resumePublished = true;
			origin.resume?.(head, scope);
		};
		let restoredReceipts = false;
		if (origin.loadReceipts) {
			// Foreground resume uses only the already authenticated offer and
			// the adapter's exact local view guards. Legacy disk proof follows.
			publishResume(offer.ids[0]);
			await yieldIdle(run.signal);
			check();
			const saved = await origin.loadReceipts(offer.ids, scope, run.signal).catch((error: unknown) => {
				check();
				if (!(error instanceof DOMException)) throw error;
				// A refused local receipt read leaves no durable authority.
				return new Map(offer.ids.map(id => [id, { revision: null } as OpenedHistoryStoredState]));
			});
			check();
			if (saved) for (const [chatId, state] of saved) {
				const retained = offer.progress.get(chatId);
				if (retained?.witness?.after === state.revision &&
					retained?.witness?.encryptedChatKey === state.encryptedChatKey ||
					state.legacy && retained?.selector && !retained.witness) continue;
				offer.progress.delete(chatId);
				if (state.completion && state.revision && state.encryptedChatKey) {
					restoredReceipts = true;
					offer.progress.set(chatId, {
						selector: null, expectedVersion: state.completion.messagesVersion, retainedRows: state.completion.retainedRows,
						verifiedConnection: -1, legacy: state.legacy,
						witness: { before: null, after: state.revision, encryptedChatKey: state.encryptedChatKey },
					});
				}
			}
		}
		const complete = Object.fromEntries([...offer.progress].filter(([, progress]) => progress.selector === null)
			.map(([id, progress]) => [id, {
				messagesVersion: progress.expectedVersion,
				verifiedOnConnection: progress.verifiedConnection === connectionEpoch,
			}]));
		const plan = await persistCall('startupOpened', {
			kind: 'begin', ids: offer.ids, messagesVersions: offer.messagesVersions,
			refreshHead: offer.refreshHead, complete,
		});
		check();
		if (!('chatIds' in plan) || plan.chatIds.length === 0) return;

		const head = plan.chatIds[0];
		const pendingLatest = new Set(plan.latestChatIds);
		const completeCount = () => plan.chatIds.filter(id =>
			!pendingLatest.has(id) && offer.progress.get(id)?.selector === null).length;
		publishResume(head);
		if (restoredReceipts) origin.coverage?.({
			newestTail: !pendingLatest.has(head) && offer.progress.has(head),
			completeChats: completeCount(), requestedChats: plan.chatIds.length,
		});
		if (pendingLatest.size === 0 || offer.pagesRead >= plan.pageBudget) return;
		if (manualEpoch === epoch) await yieldIdle(run.signal);
		check();
		reader = await origin.prepare(scope, run.signal);
		for (const chatId of plan.latestChatIds) {
			const retained = offer.progress.get(chatId);
			// Each reader has its own cursor scope. Rust can reuse past
			// coverage only after checking the newly authenticated tail.
			let confirmedCoverage = retained && retained.expectedVersion !== null ? {
				cursor: retained.selector?.direction === 'before' ? retained.selector.cursor : null,
				messagesVersion: retained.expectedVersion,
				retainedRows: retained.retainedRows,
			} : undefined;
			let selector: OpenedHistorySelector | null = plan.selector;
			let expectedVersion: number | null = null;
			let retainedRows = 0;
			let witness: OpenedHistoryPageWitness | undefined;
			let legacyWitness: OpenedHistoryPageWitness | null = null;
			let legacyStopped = false;
			while (selector && offer.pagesRead < plan.pageBudget) {
				check();
				if (offer.pagesRead > 0) await yieldIdle(run.signal);
				check();
				const page = await reader.read(chatId, selector);
				check();
				retainedRows += page.retainedRows;
				const nextWitness = page.witness;
				if (selector.direction === 'latest') {
					if (retained?.witness && !retained.legacy && (!nextWitness || retained.witness.after !== nextWitness.before ||
						retained.witness.encryptedChatKey !== nextWitness.encryptedChatKey)) confirmedCoverage = undefined;
					witness = nextWitness;
				} else if (witness && nextWitness && witness.after === nextWitness.before &&
					witness.encryptedChatKey === nextWitness.encryptedChatKey) {
					witness = nextWitness;
				} else if (witness || nextWitness) {
					// A foreign message write interrupted the confirmed range.
					// Preserve readable rows and require a fresh proof on the next offer.
					offer.progress.delete(chatId);
					break;
				}
				const decision = await persistCall('startupOpened', { kind: 'advance', progress: {
					chatId, previous: selector.direction === 'before' ? selector.cursor : null,
					start: page.start, hasMoreBefore: page.hasMoreBefore, hasMoreAfter: page.hasMoreAfter,
					rowsConfirmed: page.rowsConfirmed, pagesRead: ++offer.pagesRead, retainedRows,
					serverMessageCount: page.serverMessageCount,
					messagesVersion: page.messagesVersion, expectedVersion, confirmedCoverage,
				} }).catch((error: unknown) => {
					// A rejected Rust continuation is no longer a coverage proof.
					// A later authoritative offer can restart this chat at latest.
					check();
					offer.progress.delete(chatId);
					throw error;
				});
				check();
				if (!('done' in decision)) return;
				expectedVersion = page.messagesVersion;
				selector = decision.selector;
				retainedRows = decision.reusedRows ?? retainedRows;
				confirmedCoverage = undefined;
				if (page.legacy && !legacyStopped) {
					const prior = legacyWitness?.after ?? null;
					legacyStopped = retainedRows > LEGACY_COVERAGE_ROW_LIMIT || decision.reusedRows !== undefined ||
						!!legacyWitness && legacyWitness.encryptedChatKey !== page.legacy.encryptedChatKey;
					if (!legacyStopped) {
						const digest = await persistCall('startupOpened', {
							kind: 'coverageDigest', chatId, previous: prior, rows: page.legacy.rows,
						}).catch(() => null);
						check();
						if (digest && 'digest' in digest) legacyWitness = {
							before: prior, after: digest.digest, encryptedChatKey: page.legacy.encryptedChatKey,
						};
						else legacyStopped = true;
					}
				}
				offer.progress.set(chatId, {
					selector, expectedVersion, retainedRows, verifiedConnection: connectionEpoch, witness,
					legacy: !!page.legacy,
				});
				const completionWitness = witness ?? (!legacyStopped ? legacyWitness : null);
				if (selector === null && completionWitness && expectedVersion !== null) {
					await origin.saveReceipt?.(chatId, scope, run.signal, completionWitness, {
						messagesVersion: expectedVersion, retainedRows,
					}).catch((error: unknown) => {
						check();
						if (!(error instanceof DOMException)) throw error;
					});
					check();
				}
				pendingLatest.delete(chatId);
				if (chatId === head) offer.refreshHead = false;
				origin.coverage?.({
					newestTail: offer.progress.has(head), completeChats: completeCount(), requestedChats: plan.chatIds.length,
				});
			}
			if (selector || offer.pagesRead >= plan.pageBudget) break;
		}
	} finally {
		window.clearTimeout(timeout);
		try {
			reader?.close();
		} finally {
			if (startup === run) startup = null;
			// Only a newer offer or an intervening explicit navigation may
			// schedule another lease. A read/transport failure cannot retry itself.
			const next = offered;
			if (next && (next !== offer || navigationRevision !== revision && manualEpoch === epoch)) {
				void runOpenedChatStartup(next).catch(() => {});
			}
		}
	}
}
