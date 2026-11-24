/**
 * `live` namespace installer of the shared Rust core Worker. Marshalling only: each
 * handler forwards to the core client's `live_*` calls (browser_live_item.rs); the core's events are pushed to
 * the page as unit events (liveRemoteUpdate, liveView, livePresence, liveStatus, liveVersion) and its outgoing
 * socket frames as `liveSend` (the page writes them on its WebSocket).
 */
import { postUnitEvent, serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { borrowCoreClient, type CoreBorrowRefusal, type CoreClientBorrow } from '../drafts/coreClientBorrow';
import { isLiveItemBinding, type LiveCoreClient, type LiveItemBinding, type LiveItemUnitProtocol } from './liveItemProtocol';

import { createLiveOutboxStorage } from './liveOutboxStorage';

const KINDS = new Set(['doc', 'sheet', 'deck', 'code']);

function record(payload: unknown): Record<string, unknown> {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
	return payload as Record<string, unknown>;
}
function itemOf(payload: unknown): string {
	const id = record(payload).itemId;
	if (typeof id !== 'string' || id.length === 0 || id.length > 256) throw new UnitRefusal('protocol');
	return id;
}
function run(call: () => void): true {
	try {
		call();
		return true;
	} catch (error) {
		throw new UnitRefusal(typeof error === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(error) ? error : 'protocol');
	}
}

const BORROW_TIMEOUT_MS = 5000;
const TICK_MS = 2000;

export interface LiveItemDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}
const defaultDeps = (): LiveItemDeps => ({ borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs) });

export function createLiveItemHandlers(binding: LiveItemBinding, connection: string, principal: string, deps: LiveItemDeps,
	signal: AbortSignal, sequence: <T>(call: () => Promise<T>) => Promise<T>): UnitHandlers<LiveItemUnitProtocol> {
	/** One core call on a borrowed admitted client; always released. */
	function withClient<T>(call: (client: LiveCoreClient, handle: string, generation: number) => Promise<T>,
		timeoutMs = BORROW_TIMEOUT_MS): Promise<T> {
		return sequence(async () => {
			const borrow = await deps.borrow(principal, signal, timeoutMs);
			if (borrow === 'none') throw new UnitRefusal('not_admitted');
			if (borrow === 'busy') throw new UnitRefusal('core_busy');
			if (borrow === 'local') throw new UnitRefusal('local_session');
			try {
				return await call(borrow.client as unknown as LiveCoreClient, borrow.status.handle, borrow.status.generation);
			} catch (error) {
				throw new UnitRefusal(typeof error === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(error) ? error : 'protocol');
			} finally {
				borrow.release();
			}
		});
	}
	return {
		liveScanRecovery: async () => {
			await withClient((c, h, g) => c.live_scan_recovery(connection, h, g));
			return true;
		},
		liveOpen: async (p) => {
			const kind = record(p).kind;
			if (typeof kind !== 'string' || !KINDS.has(kind)) throw new UnitRefusal('protocol');
			const id = itemOf(p);
			const projectId = record(p).projectId;
			if (projectId !== undefined && (typeof projectId !== 'string' || projectId.length === 0 || projectId.length > 256)) throw new UnitRefusal('protocol');
			const teamId = record(p).teamId;
			if (teamId !== undefined && (typeof teamId !== 'string' || teamId.length === 0 || teamId.length > 256)) throw new UnitRefusal('protocol');
			await withClient((c, h, g) => c.live_open(connection, h, g, id, kind, projectId as string | undefined, teamId as string | undefined));
			return true;
		},
		liveApplyMirrorUpdate: async (p) => {
			const bytes = record(p).bytes;
			if (Object.prototype.toString.call(bytes) !== '[object Uint8Array]') throw new UnitRefusal('protocol');
			const id = itemOf(p);
			await withClient((c, h, g) => c.live_apply_mirror_update(connection, h, g, id, bytes as Uint8Array));
			return true;
		},
		liveApplyOp: async (p) => {
			const id = itemOf(p);
			await withClient((c, h, g) => c.live_apply_op(connection, h, g, id, JSON.stringify(record(p).op)));
			return true;
		},
		liveSetPresence: async (p) => {
			const id = itemOf(p);
			await withClient((c, h, g) => c.live_set_presence(connection, h, g, id, JSON.stringify(record(p).presence)));
			return true;
		},
		liveClose: async (p) => {
			const id = itemOf(p);
			await withClient((c, h, g) => c.live_close(connection, h, g, id));
			return true;
		},
		liveOpenTeamRevisionContent: async (p) => {
			const { teamId, version, ciphertext, displayText } = record(p);
			if (typeof teamId !== 'string' || teamId.length === 0 || teamId.length > 256 ||
				typeof version !== 'number' || !Number.isInteger(version) || version < 1 || version > 2_147_483_647 ||
				typeof ciphertext !== 'string' || ciphertext.length > 4 * 1024 * 1024 ||
				typeof displayText !== 'boolean') throw new UnitRefusal('protocol');
			const item = itemOf(p);
			return (await withClient((client, handle, generation) =>
				client.live_open_team_revision_content(handle, generation, teamId, item, version, ciphertext, displayText))) ?? null;
		},
		liveRestoreVersion: async (p) => {
			const { source, head } = record(p);
			if (typeof source !== 'number' || !Number.isSafeInteger(source) ||
				typeof head !== 'number' || !Number.isSafeInteger(head)) throw new UnitRefusal('protocol');
			return withClient((c, h, g) => c.live_restore_version(connection, h, g, itemOf(p), source, head));
		},
		liveUndoLatestAssistant: (p) => withClient((c, h, g) => c.live_undo_latest_assistant(connection, h, g, itemOf(p))),
		liveFrame: async (p) => {
			const type = record(p).type;
			if (typeof type !== 'string' || !binding.live_is_frame(type)) return false;
			return withClient((c) => c.live_on_frame(connection, type, JSON.stringify(record(p).payload ?? {})));
		},
		liveConnected: async (p) => {
			const connected = record(p).connected === true;
			await withClient((c) => c.live_set_connected(connection, connected));
			return true;
		},
		liveSetUser: (p) => {
			const userId = record(p).userId;
			if (typeof userId !== 'string' || userId.length === 0 || userId.length > 256) throw new UnitRefusal('protocol');
			return sequence(async () => run(() => binding.live_set_user(connection, userId)));
		},
	};
}

export function installLiveItemUnit(context: UnitInstallContext, deps: LiveItemDeps = defaultDeps()): () => void {
	const principal = context.principal;
	const binding = context.binding;
	if (context.ports.length !== 1 || !principal || !isLiveItemBinding(binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const connection = crypto.randomUUID();
	const outboxStorage = createLiveOutboxStorage(context.signal);
	let pending: Promise<void> | undefined;
	function sequence<T>(call: () => Promise<T>): Promise<T> {
		// Preserve port order across async borrows, especially edits before Close.
		const result = (pending ?? Promise.resolve()).then(call);
		const settled = result.then(() => {}, () => {});
		pending = settled;
		void settled.then(() => { if (pending === settled) pending = undefined; });
		return result;
	}
	// The core pushes its events and outgoing socket frames to the page as unit events.
	binding.live_configure(
		connection,
		(event, payload) => postUnitEvent(port, event, payload),
		(type, payloadJson) => postUnitEvent(port, 'liveSend', { type, payloadJson }),
		outboxStorage.keys,
		outboxStorage.read,
		outboxStorage.compareAndPut,
	);
	const stop = serveUnitPort<LiveItemUnitProtocol>(port, createLiveItemHandlers(binding, connection, principal, deps, context.signal, sequence));
	// Clock tick of the core (presence expiry, due checkpoints); a busy client skips the tick.
	const timer = setInterval(() => {
		if (pending) return;
		void sequence(async () => {
			const borrow = await deps.borrow(principal, context.signal, 0);
			if (typeof borrow === 'string') return;
			try {
				await (borrow.client as unknown as LiveCoreClient).live_tick(connection);
			} finally {
				borrow.release();
			}
		}).catch(() => {});
	}, TICK_MS);
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		clearInterval(timer);
		stop();
		binding.live_dispose(connection);
		outboxStorage.close();
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	port.addEventListener('close', dispose, { once: true });
	return dispose;
}
