/**
 * Page client of the shared Worker's `embedEdit` unit (`feature.embed-user-edits`;
 * VITE_OPENMATES_RUST_CORE builds only). One port per bound generation, opened
 * lazily. Forwards the Enhance WebSocket frames of the page's socket to the
 * Worker (the core's waker) while the port is open.
 *
 * No logic here: Enhance, restore, the chat event, the reconcile and the event
 * folding are the core's; failures reject with the core's stable code
 * (`UnitPortError.code`).
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import {
	EMBED_EDIT_UNIT_CLOSE,
	type EmbedChatItem,
	type EmbedEditProtocol,
	type EmbedEditScope,
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

/** Enhance the head version of image `embedId` (joins a run already going); resolves once saved. */
export async function enhanceImage(embedId: string, scope: EmbedEditScope): Promise<ImageEnhanceResult> {
	return (await unit()).request('enhanceImage', { embedId, scope }, { timeoutMs: ENHANCE_TIMEOUT_MS });
}

/** The Enhance of `embedId` running in the Worker (e.g. started before a reload), or null. */
export async function runningEnhance(embedId: string): Promise<RunningEnhance | null> {
	return (await unit()).request('runningEnhance', { embedId });
}

/** Restore version `restoredFrom` of `embedId` as its next version. */
export async function restoreEmbedVersion(embedId: string, scope: EmbedEditScope, restoredFrom: number): Promise<EmbedRevisionResult> {
	return (await unit()).request('restoreVersion', { embedId, scope, restoredFrom });
}

/** Write the chat's pending `embed_updated` events (chat open). */
export async function reconcileEmbedNotices(chatId: string): Promise<NoticeReconcileReport> {
	return (await unit()).request('reconcileNotices', { chatId });
}

/** Fold the chat's `embed_updated` events into chat items (core grouping). */
export async function groupEmbedUpdatedEvents(rows: EmbedEventRow[]): Promise<EmbedChatItem[]> {
	return (await unit()).request('groupUpdatedEvents', { rows });
}

/** Close before a logout/account-switch unbind. */
export function closeEmbedEditSession(): void {
	const stale = current;
	current = null;
	stale?.opening.then((opened) => opened.close(), () => undefined);
}
