/**
 * Page client of the shared Worker's `embedEdit` unit (`feature.embed-user-edits`;
 * VITE_OPENMATES_RUST_CORE builds only). One port per bound generation, opened
 * lazily. Forwards the Enhance WebSocket frames of the page's socket to the
 * Worker (the core's waker) while the port is open.
 *
 * No logic here: content edits, Enhance, restore, the chat event, the reconcile and the event
 * folding are the core's; failures reject with the core's stable code
 * (`UnitPortError.code`).
 *
 * The page's history session may still be the local-only admission (no server
 * authority) when the user edits, e.g. in a chat created after login. A
 * USER-PRESSED write (Enhance, content edit, restore) the unit refuses with
 * `local_session` / `not_admitted` (before any core call) waits for this page's
 * running streamed-embed writes, asks the history bootstrap for its existing
 * server-checked upgrade (serverSessionRegistry), bounded, and is sent once
 * more. The chat-open notice reconcile never causes an upgrade: on a local
 * session it resolves `deferred` and runs once a server-checked session exists.
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { ensureServerCheckedSession, onceServerCheckedSession } from '../host/serverSessionRegistry';
import { canonicalEmbedWritesSettled } from '../../canonicalEmbedWriteCoordinator';
import {
	EMBED_EDIT_UNIT_CLOSE,
	type EmbedChatItem,
	type EmbedEditProtocol,
	type EmbedEditScope,
	type EmbedEventDelivery,
	type EmbedEventNotice,
	type EmbedEventRow,
	type EmbedRevisionResult,
	type ImageEnhanceResult,
	type NoticeReconcileReport,
	type RunningEnhance
} from './embedEditProtocol';

export const EMBED_EDITS_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

/** An Enhance job can take minutes; the Worker answers when it is saved. */
const ENHANCE_TIMEOUT_MS = 10 * 60_000;
const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;
const ENHANCE_FRAMES = ['image_enhance_ready', 'image_enhance_failed'] as const;
/** A user-pressed write: the unit may wait for a busy core (EMBED_EDIT_USER_BORROW_TIMEOUT_MS) before the core call. */
const WRITE_TIMEOUT_MS = 60_000;
/** Bound of the server-checked upgrade a refused write asks for (Worker restore + server session check). */
export const SERVER_SESSION_TIMEOUT_MS = 15_000;
/**
 * Whole budget of a refused user write from its refusal: the upgrade plus the
 * one resend. A failed or slow upgrade rejects with its code inside this, well
 * before the UI's own 45 s save expectation and the 60 s port timeout.
 */
export const SERVER_SESSION_RETRY_BUDGET_MS = 40_000;
/** Unit refusals that mean "no server-checked client yet"; the unit made no core call. */
const NEEDS_SERVER_SESSION = new Set(['local_session', 'not_admitted']);

interface Opened { core: SharedRustCore; generation: number; unit: UnitPort<EmbedEditProtocol>; close(): void }
let current: { generation: number; opening: Promise<Opened> } | null = null;

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('embed_edit_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

async function open(core: SharedRustCore, generation: number): Promise<Opened> {
	const raw = await core.openUnit('embedEdit');
	const unit = createUnitPort<EmbedEditProtocol>(raw);
	const { webSocketService } = await import('../../websocketService');
	const forwards = ENHANCE_FRAMES.map((type) => {
		const handler = (payload: unknown) => {
			if (unit.closed) return;
			unit.request('enhanceFrame', { type, payload }).catch((error: unknown) => {
				console.warn('[embedEditSession] Enhance frame not forwarded:', (error as { code?: unknown })?.code ?? error);
			});
		};
		webSocketService.on(type, handler);
		return () => webSocketService.off(type, handler);
	});
	let stopCrash = () => {};
	const close = () => {
		stopCrash();
		for (const stop of forwards) stop();
		if (unit.closed) return;
		raw.postMessage(EMBED_EDIT_UNIT_CLOSE);
		unit.close();
	};
	stopCrash = core.onCrash(close);
	return { core, generation, unit, close };
}

/** The `embedEdit` port of the current generation (opens it on first use). */
async function unit(): Promise<UnitPort<EmbedEditProtocol>> {
	if (!EMBED_EDITS_ENABLED) throw new UnitPortError('embed_edits_unavailable');
	const core = requireSharedRustCore();
	const generation = await boundGeneration(core);
	if (current?.generation === generation) {
		const opened = await current.opening;
		if (opened.core === core && !opened.unit.closed) return opened.unit;
	}
	const stale = current;
	stale?.opening.then((opened) => opened.close(), () => undefined);
	const opening = open(core, generation);
	current = { generation, opening };
	opening.catch(() => { if (current?.opening === opening) current = null; });
	return (await opening).unit;
}

function refusalCode(error: unknown): unknown {
	return (error as { code?: unknown } | null)?.code;
}

/** Report of a reconcile held back until a server-checked session exists. */
export const RECONCILE_DEFERRED = 'server_session_pending';

/**
 * The default upgrade of a refused user write: first let this page's running
 * streamed-embed writes settle (the new session must not join one midway),
 * then the server-checked upgrade, both inside SERVER_SESSION_TIMEOUT_MS.
 */
async function upgradeAfterEmbedWrites(timeoutMs: number): Promise<boolean> {
	const started = Date.now();
	let timer: ReturnType<typeof setTimeout> | undefined;
	const bound = new Promise<never>((_, reject) => {
		timer = setTimeout(() => reject(new Error('embed_writes_pending')), timeoutMs);
	});
	try {
		await Promise.race([canonicalEmbedWritesSettled(), bound]);
	} finally {
		clearTimeout(timer);
	}
	return ensureServerCheckedSession(Math.max(1, timeoutMs - (Date.now() - started)));
}

/**
 * Sends a server write; a `local_session` / `not_admitted` refusal asks for the
 * page's server-checked session and sends it once more. Without a registered
 * upgrade, or when it fails, the original refusal stands. The resend gets the
 * rest of SERVER_SESSION_RETRY_BUDGET_MS as its timeout (`send(timeoutMs)`).
 */
export async function withServerSession<T>(send: (timeoutMs?: number) => Promise<T>,
	ensure: (timeoutMs: number) => Promise<boolean> = upgradeAfterEmbedWrites): Promise<T> {
	try {
		return await send();
	} catch (error) {
		if (!NEEDS_SERVER_SESSION.has(refusalCode(error) as string)) throw error;
		const deadline = Date.now() + SERVER_SESSION_RETRY_BUDGET_MS;
		let admitted: boolean;
		try {
			admitted = await ensure(SERVER_SESSION_TIMEOUT_MS);
		} catch (failure) {
			console.warn('[embedEditSession] Server-checked session unavailable:', failure instanceof Error ? failure.message : failure);
			throw error;
		}
		if (!admitted) throw error;
		return send(Math.max(1, deadline - Date.now()));
	}
}

/** Hands a written `embed_updated` row to the open chat (the page's `chatUpdated` event). */
async function dispatchChatUpdated(notice: EmbedEventNotice): Promise<void> {
	const { chatSyncService } = await import('../../chatSyncService');
	const newMessage = { message_id: notice.message_id, chat_id: notice.chat_id, role: 'system' as const,
		content: notice.content, created_at: notice.created_at, status: 'synced' as const };
	chatSyncService.dispatchEvent(new CustomEvent('chatUpdated', {
		detail: { chat_id: notice.chat_id, type: 'system_message_added', newMessage }
	}));
}

/**
 * Shows the chat event of a saved version on this page: the server sends the
 * stored row only to the user's other devices, so a written event's `notice`
 * goes to the open chat here. A deferred event logs its stable reason code
 * (no ids, no content); the server keeps it pending for the next chat open.
 */
export async function showEventNotice(result: { event?: EmbedEventDelivery; notice?: EmbedEventNotice },
	dispatch: (notice: EmbedEventNotice) => Promise<void> = dispatchChatUpdated): Promise<void> {
	if (result.event?.state === 'deferred') {
		console.warn('[embedEditSession] Chat event of the saved version deferred:', result.event.code);
		return;
	}
	if (result.notice) await dispatch(result.notice);
}

async function shown<T extends { event?: EmbedEventDelivery; notice?: EmbedEventNotice }>(saving: Promise<T>): Promise<T> {
	const result = await saving;
	await showEventNotice(result).catch((error: unknown) => {
		console.warn('[embedEditSession] Chat event row not shown:', error instanceof Error ? error.message : error);
	});
	return result;
}

/** Enhance the head version of image `embedId` (joins a run already going); resolves once saved. */
export async function enhanceImage(embedId: string, scope: EmbedEditScope): Promise<ImageEnhanceResult> {
	return shown(withServerSession(async () => (await unit()).request('enhanceImage', { embedId, scope },
		{ timeoutMs: ENHANCE_TIMEOUT_MS })));
}

/** The Enhance of `embedId` running in the Worker (e.g. started before a reload), or null. */
export async function runningEnhance(embedId: string): Promise<RunningEnhance | null> {
	return (await unit()).request('runningEnhance', { embedId });
}

/** Save `content` (new head TOON) of an edit made on version `baseVersion` of `embedId` as its next version. */
export async function commitContentRevision(embedId: string, scope: EmbedEditScope, baseVersion: number,
	content: string): Promise<EmbedRevisionResult> {
	return shown(withServerSession(async (timeoutMs = WRITE_TIMEOUT_MS) => (await unit()).request('commitContentRevision',
		{ embedId, scope, baseVersion, content }, { timeoutMs })));
}

/** Restore version `restoredFrom` of `embedId` as its next version. */
export async function restoreEmbedVersion(embedId: string, scope: EmbedEditScope, restoredFrom: number): Promise<EmbedRevisionResult> {
	return shown(withServerSession(async (timeoutMs = WRITE_TIMEOUT_MS) => (await unit()).request('restoreVersion',
		{ embedId, scope, restoredFrom }, { timeoutMs })));
}

/** Chats whose chat-open reconcile waits for a server-checked session. */
const deferredReconciles = new Set<string>();
let stopDeferredWatch: (() => void) | null = null;

type ReconcileSend = (chatId: string) => Promise<NoticeReconcileReport>;

/**
 * Chat-open reconcile through `send`. A `local_session` / `not_admitted`
 * refusal resolves `deferred: RECONCILE_DEFERRED` without asking for an
 * upgrade; the chat is reconciled again (through `send`) once `watch` reports a
 * server-checked admission. Other refusals reject.
 */
export async function reconcileOrDefer(chatId: string, send: ReconcileSend,
	watch: (listener: () => void) => () => void = onceServerCheckedSession): Promise<NoticeReconcileReport> {
	try {
		return await send(chatId);
	} catch (error) {
		if (!NEEDS_SERVER_SESSION.has(refusalCode(error) as string)) throw error;
		deferredReconciles.add(chatId);
		stopDeferredWatch ??= watch(() => {
			stopDeferredWatch = null;
			const chats = [...deferredReconciles];
			deferredReconciles.clear();
			for (const chat of chats) {
				reconcileOrDefer(chat, send, watch).catch((failure: unknown) => {
					console.warn('[embedEditSession] Deferred embed update notices not reconciled:', refusalCode(failure) ?? failure);
				});
			}
		});
		return { written: 0, already_present: 0, unresolved: [], deferred: RECONCILE_DEFERRED };
	}
}

/** Write the chat's pending `embed_updated` events (chat open); see `reconcileOrDefer`. */
export function reconcileEmbedNotices(chatId: string): Promise<NoticeReconcileReport> {
	return reconcileOrDefer(chatId, async (chat) => (await unit()).request('reconcileNotices', { chatId: chat }));
}

/** Fold the chat's `embed_updated` events into chat items (core grouping). */
export async function groupEmbedUpdatedEvents(rows: EmbedEventRow[]): Promise<EmbedChatItem[]> {
	return (await unit()).request('groupUpdatedEvents', { rows });
}

/** Close before a logout/account-switch unbind. */
export function closeEmbedEditSession(): void {
	deferredReconciles.clear();
	stopDeferredWatch?.();
	stopDeferredWatch = null;
	const stale = current;
	current = null;
	stale?.opening.then((opened) => opened.close(), () => undefined);
}
