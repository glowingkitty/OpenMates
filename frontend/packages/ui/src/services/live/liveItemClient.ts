/**
 * Thin page facade to the core's live item in the shared Worker (`live` unit).
 * Forwarding only: calls become unit requests, unit-pushed events reach subscribers.
 * No sync, merge, crypto or permission logic lives here (client-core rules).
 * A Worker crash ends the port; the next call reopens it and the editor reopens its item.
 */
import { whenSharedRustCore, type SharedRustCore } from '../rustCore/host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../rustCore/host/unitPort';
import { SERVER_SESSION_TIMEOUT_MS, withServerSession } from '../rustCore/projects/projectTimelineClient';
import { ensureServerCheckedSession, onServerCheckedSessionRegistration } from '../rustCore/host/serverSessionRegistry';
import { webSocketService } from '../websocketService';
import { get } from 'svelte/store';
import { authStore } from '../../stores/authStore';
import { userProfile } from '../../stores/userProfile';
import type { LiveItemUnitProtocol } from '../rustCore/live/liveItemProtocol';
import { createLivePrivateCopyNotice } from './livePrivateCopy';
import type { LiveEventName, LiveEvents, LiveItemClient, LiveItemKind, LivePresence } from './liveItemTypes';

const EVENT_NAMES: ReadonlySet<string> = new Set<LiveEventName>(['liveRemoteUpdate', 'liveView', 'livePresence', 'liveStatus', 'liveVersion']);

/** What the facade needs from a transport; the default one is the shared Worker unit port. */
export interface LiveItemTransport {
	request<K extends keyof LiveItemUnitProtocol & string>(op: K, payload: LiveItemUnitProtocol[K]['request']): Promise<unknown>;
	/** Registers the sink for pushed events; called once per (re)opened transport. */
	onEvent(sink: (name: string, payload: unknown) => void): () => void;
}

/** Fire-and-forget callers (`void client.…`) must never see an unhandled rejection; the open reports failure. */
async function bestEffort(call: Promise<unknown>): Promise<void> {
	try { await call; } catch (error) { console.debug('[live] best-effort call refused', error instanceof Error ? error.message : error); }
}

type WorkerLiveItemClient = LiveItemClient & {
	scanRevokedPrivateCopies(): Promise<void>;
	liveRestoreDocument(itemId: string, source: number, head: number): Promise<{ version: number; content: string }>;
	liveRestoreVersion(itemId: string, source: number, head: number): Promise<{ version: number; content: string }>;
	liveOpenTeamRevisionContent(itemId: string, teamId: string, version: number, ciphertext: string, displayText?: boolean): Promise<string | null>;
};

export function createLiveItemClient(transport: LiveItemTransport): WorkerLiveItemClient {
	const listeners = new Map<LiveEventName, Set<(payload: never) => void>>();
	let stopEvents: (() => void) | null = null;

	function ensureEvents(): void {
		stopEvents ??= transport.onEvent((name, payload) => {
			if (!EVENT_NAMES.has(name)) return;
			for (const listener of [...(listeners.get(name as LiveEventName) ?? [])]) listener(payload as never);
		});
	}
	const restoreVersion = (itemId: string, source: number, head: number) =>
		transport.request('liveRestoreVersion', { itemId, source, head }) as Promise<{ version: number; content: string }>;

	return {
		async scanRevokedPrivateCopies() { ensureEvents(); await transport.request('liveScanRecovery', undefined); },
		async liveOpen(itemId: string, kind: LiveItemKind, projectId?: string, teamId?: string) { ensureEvents(); await transport.request('liveOpen', { itemId, kind, ...(projectId ? { projectId } : {}), ...(teamId ? { teamId } : {}) }); },
		async liveApplyMirrorUpdate(itemId: string, bytes: Uint8Array) { await bestEffort(transport.request('liveApplyMirrorUpdate', { itemId, bytes })); },
		async liveApplyOp(itemId: string, op: unknown) { await transport.request('liveApplyOp', { itemId, op }); },
		async liveSetPresence(itemId: string, presence: LivePresence) {
			// Every editor's presence carries the visible name; the core adds the hashed id and colour.
			const named = presence.display_name ? presence : { ...presence, display_name: get(userProfile).username || 'You' };
			await bestEffort(transport.request('liveSetPresence', { itemId, presence: named }));
		},
		async liveClose(itemId: string) { await bestEffort(transport.request('liveClose', { itemId })); },
		async liveOpenTeamRevisionContent(itemId: string, teamId: string, version: number, ciphertext: string, displayText = false) {
			return await transport.request('liveOpenTeamRevisionContent', { itemId, teamId, version, ciphertext, displayText }) as string | null;
		},
		async liveUndoLatestAssistant(itemId: string) {
			return await transport.request('liveUndoLatestAssistant', { itemId }) === true;
		},
		liveRestoreDocument: restoreVersion,
		liveRestoreVersion: restoreVersion,
		on<E extends LiveEventName>(event: E, listener: (payload: LiveEvents[E]) => void) {
			ensureEvents();
			const set = listeners.get(event) ?? new Set();
			set.add(listener as (payload: never) => void);
			listeners.set(event, set);
			return () => { set.delete(listener as (payload: never) => void); };
		},
	};
}

/** Transport over the shared Worker `live` unit (opened lazily, like the deckDocument client). */
export function createWorkerLiveTransport(): LiveItemTransport {
	let unit: { core: SharedRustCore; port: UnitPort<LiveItemUnitProtocol>; generation: number | null; dispose(): void } | null = null;
	let opening: Promise<NonNullable<typeof unit>> | null = null;
	const sinks = new Set<(name: string, payload: unknown) => void>();

	async function open(core: SharedRustCore): Promise<NonNullable<typeof unit>> {
		const generation = core.generation;
		const port = createUnitPort<LiveItemUnitProtocol>(await core.openUnit('live', { unbound: generation === null }));
		/** Forwarded call; a local-only session is upgraded to the server-checked one and the call resent. */
		const forward = <K extends keyof LiveItemUnitProtocol & string>(op: K, payload: LiveItemUnitProtocol[K]['request']) =>
			withServerSession(() => port.request(op, payload));
		const privateCopies = createLivePrivateCopyNotice(() => !port.closed && core.generation === generation);
		port.onEvent((name, payload) => {
			if (name === 'livePrivateCopy') {
				privateCopies.offer(payload);
				return;
			}
			if (name === 'liveSend') {
				// The core's outgoing frame: written on the page's socket, nothing decided here.
				const frame = payload as { type: string; payloadJson: string };
				void webSocketService.sendMessage(frame.type, JSON.parse(frame.payloadJson));
				return;
			}
			for (const sink of [...sinks]) sink(name, payload);
		});
		// Forward the socket's frames and connection state to the core (it consumes live frames).
		const onMessage = (event: Event) => {
			const frame = (event as CustomEvent<{ type?: string; payload?: unknown }>).detail;
			if (typeof frame?.type === 'string') void forward('liveFrame', { type: frame.type, payload: frame.payload }).catch(() => {});
		};
		const connected = (value: boolean) => () => { void forward('liveConnected', { connected: value }).catch(() => {}); };
		const onOpen = connected(true), onClose = connected(false);
		webSocketService.addEventListener('message', onMessage);
		webSocketService.addEventListener('open', onOpen);
		webSocketService.addEventListener('close', onClose);
		// The browser knows the network is gone before the socket's ping times out: the core
		// holds edits offline at once and resends them when the network is back.
		const onBrowserOnline = () => { if (webSocketService.isConnected()) onOpen(); };
		if (typeof window !== 'undefined') {
			window.addEventListener('offline', onClose);
			window.addEventListener('online', onBrowserOnline);
		}
		if (webSocketService.isConnected()) onOpen();
		// The signed-in user id (contributor of versions); the core hashes it.
		let sentUserId: string | null = null;
		const stopProfile = userProfile.subscribe((profile) => {
			const id = profile.user_id;
			if (id === sentUserId) return;
			if (sentUserId || !id) privateCopies.clear();
			sentUserId = id || null;
			if (!id) return;
			void forward('liveSetUser', { userId: id }).catch(() => { sentUserId = null; });
		});
		const opened = { core, port, generation, dispose };
		const stopCrashWatch = core.onCrash(dispose);
		function dispose(): void {
			privateCopies.clear();
			webSocketService.removeEventListener('message', onMessage);
			webSocketService.removeEventListener('open', onOpen);
			webSocketService.removeEventListener('close', onClose);
			if (typeof window !== 'undefined') {
				window.removeEventListener('offline', onClose);
				window.removeEventListener('online', onBrowserOnline);
			}
			stopProfile();
			stopCrashWatch();
			port.close();
			if (unit === opened) unit = null;
		}
		unit = opened;
		return opened;
	}

	async function current(core: SharedRustCore) {
		if (unit && (unit.port.closed || unit.core !== core || unit.core.generation !== unit.generation)) unit.dispose();
		if (unit) return unit;
		opening ??= open(core).finally(() => { opening = null; });
		return opening;
	}

	return {
		async request(op, payload) {
			const core = await whenSharedRustCore();
			const release = core.hold();
			try {
				const { port } = await current(core);
				return await withServerSession(() => port.request(op, payload));
			} finally {
				release();
			}
		},
		onEvent(sink) {
			sinks.add(sink);
			// Open the port now so events flow even before the first call.
			void whenSharedRustCore().then((core) => current(core)).catch(() => {});
			return () => { sinks.delete(sink); };
		},
	};
}

let shared: WorkerLiveItemClient | null = null;
/** The page-wide client bound to the shared Worker. */
export function liveItemClient(): WorkerLiveItemClient {
	shared ??= createLiveItemClient(createWorkerLiveTransport());
	return shared;
}

/** Starts the account-bound recovery check once the app has a signed-in profile. */
export function startLivePrivateCopyRecovery(signal: AbortSignal): void {
	if (signal.aborted) return;
	let principal: string | undefined;
	let scanningPrincipal: string | undefined;
	let admissionRegistered = false;
	async function scan() {
		const account = principal;
		if (!admissionRegistered || !account || account === scanningPrincipal ||
			!navigator.onLine || signal.aborted) return;
		scanningPrincipal = account;
		try {
			// The live unit is bound to a principal. On a cold home page
			// the Worker can exist before any server-checked session does.
			const admitted = await ensureServerCheckedSession(SERVER_SESSION_TIMEOUT_MS);
			if (admitted && !signal.aborted && principal === account) {
				await liveItemClient().scanRevokedPrivateCopies();
			}
		} catch (error) {
			const code = error instanceof Error && /^[a-z_]{1,64}$/.test(error.message) ? error.message : 'unavailable';
			console.debug('[live] Private-copy scan deferred', code);
		} finally {
			if (scanningPrincipal === account) scanningPrincipal = undefined;
		}
	}
	const requestScan = () => { void scan(); };
	const accountChanged = () => {
		const auth = get(authStore);
		const next = auth.isAuthenticated && auth.isInitialized ? get(userProfile).user_id || undefined : undefined;
		if (next === principal) return;
		principal = next;
		requestScan();
	};
	const stopProfile = userProfile.subscribe(accountChanged);
	const stopAuth = authStore.subscribe(accountChanged);
	const stopRegistration = onServerCheckedSessionRegistration(() => {
		admissionRegistered = true;
		queueMicrotask(requestScan);
	});
	window.addEventListener('online', requestScan, { signal });
	signal.addEventListener('abort', () => {
		stopProfile();
		stopAuth();
		stopRegistration();
	}, { once: true });
}
