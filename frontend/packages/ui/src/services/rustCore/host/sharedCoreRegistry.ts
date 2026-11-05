/**
 * Page-side handle to the single shared Rust core Worker.
 *
 * @openmates/ui services never import web_app code: the web_app registers one
 * `SharedRustCore` (built with `createSharedCoreClient`) under the
 * VITE_OPENMATES_RUST_CORE guard. With the flag OFF nothing registers and
 * `requireSharedRustCore()` throws the fixed code `rust_core_not_enabled`.
 *
 * Supervision: a Worker `error`/`messageerror` marks the realm crashed, rejects
 * every pending control request with `shared_core_crashed`, drops the bound
 * generation, notifies `onCrash` listeners (units must treat their ports as
 * dead) and terminates the Worker. The next request respawns a fresh Worker.
 * There is no TypeScript fallback.
 */
import {
	SHARED_WORKER_PROTOCOL_VERSION,
	parseSharedControlReply,
	type SharedControlReply,
	type SharedNamespace,
	type SharedRefusalCode
} from './sharedWorkerProtocol';

export const SHARED_CORE_CONTROL_TIMEOUT_MS = 30_000;

export type SharedCoreErrorCode = SharedRefusalCode | 'shared_core_crashed' | 'shared_core_timeout' | 'shared_core_bad_reply'
	| 'shared_core_terminated' | 'shared_core_aborted' | 'rust_core_not_enabled';
export class SharedCoreError extends Error {
	constructor(readonly code: SharedCoreErrorCode) {
		super(code);
		this.name = 'SharedCoreError';
	}
}

export interface OpenUnitOptions {
	/** Extra ports in their documented positions (core: ports[1] is the recovery port). */
	extraPorts?: MessagePort[];
	signal?: AbortSignal;
}

export interface SharedRustCore {
	/** Opens `ns` in the current generation (or unbound for crypto/auth) and returns the page end of its port. */
	openUnit(ns: SharedNamespace, options?: OpenUnitOptions): Promise<MessagePort>;
	/** Admits one principal and returns the new generation. Refused `already_bound` until unbound. */
	bind(principal: string, signal?: AbortSignal): Promise<number>;
	/** Ends the current generation; the Worker closes every port opened under it. No-op when unbound. */
	unbind(signal?: AbortSignal): Promise<void>;
	/** Loads the realm's single WASM binding ahead of the first `open` (no authority, no generation). */
	prewarm(signal?: AbortSignal): Promise<void>;
	/** Current bound generation, null when unbound or after a crash. */
	readonly generation: number | null;
	/** Subscribes to crash notifications; returns the unsubscribe function. */
	onCrash(listener: () => void): () => void;
	/** Terminates the Worker (logout / account switch hard stop). Later calls respawn. */
	terminate(): void;
}

/** Minimal Worker surface so tests can supply a fake. */
export interface SharedWorkerEndpoint {
	postMessage(message: unknown, transfer: Transferable[]): void;
	addEventListener(type: 'message' | 'error' | 'messageerror', listener: (event: Event) => void): void;
	terminate(): void;
}

interface Pending { resolve(reply: Extract<SharedControlReply, { type: 'ready' }>): void; reject(error: SharedCoreError): void; cleanup(): void }

export function createSharedCoreClient(
	spawn: () => SharedWorkerEndpoint,
	options: { timeoutMs?: number } = {}
): SharedRustCore {
	const timeoutMs = options.timeoutMs ?? SHARED_CORE_CONTROL_TIMEOUT_MS;
	const crashListeners = new Set<() => void>();
	const pending = new Map<number, Pending>();
	let worker: SharedWorkerEndpoint | null = null;
	let generation: number | null = null;
	let nextId = 1;

	function failAll(code: SharedCoreErrorCode): void {
		for (const [id, entry] of [...pending]) {
			pending.delete(id);
			entry.cleanup();
			entry.reject(new SharedCoreError(code));
		}
	}
	function crash(failed: SharedWorkerEndpoint): void {
		if (worker !== failed) return;
		worker = null;
		generation = null;
		failed.terminate();
		failAll('shared_core_crashed');
		for (const listener of [...crashListeners]) listener();
	}
	function endpoint(): SharedWorkerEndpoint {
		if (worker) return worker;
		const spawned = spawn();
		worker = spawned;
		spawned.addEventListener('message', (event) => {
			if (worker !== spawned) return;
			const reply = parseSharedControlReply((event as MessageEvent<unknown>).data);
			if (!reply || reply.id === null) return;
			const entry = pending.get(reply.id);
			if (!entry) return;
			pending.delete(reply.id);
			entry.cleanup();
			if (reply.type === 'ready') entry.resolve(reply);
			else entry.reject(new SharedCoreError(reply.code));
		});
		spawned.addEventListener('error', () => crash(spawned));
		spawned.addEventListener('messageerror', () => crash(spawned));
		return spawned;
	}

	function control(message: Record<string, unknown>, transfer: MessagePort[], signal?: AbortSignal) {
		if (signal?.aborted) return Promise.reject(new SharedCoreError('shared_core_aborted'));
		const target = endpoint();
		const id = nextId++;
		return new Promise<Extract<SharedControlReply, { type: 'ready' }>>((resolve, reject) => {
			const drop = (code: SharedCoreErrorCode) => {
				const entry = pending.get(id);
				if (!entry) return;
				pending.delete(id);
				entry.cleanup();
				entry.reject(new SharedCoreError(code));
			};
			const onAbort = () => drop('shared_core_aborted');
			const timer = setTimeout(() => drop('shared_core_timeout'), timeoutMs);
			signal?.addEventListener('abort', onAbort, { once: true });
			pending.set(id, { resolve, reject, cleanup() { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); } });
			target.postMessage({ v: SHARED_WORKER_PROTOCOL_VERSION, id, ...message }, transfer);
		});
	}

	return {
		get generation() { return generation; },
		async openUnit(ns, open = {}) {
			const channel = new MessageChannel();
			const ports = [channel.port2, ...(open.extraPorts ?? [])];
			try {
				await control({ type: 'open', ns, generation }, ports, open.signal);
			} catch (error) {
				channel.port1.close();
				throw error;
			}
			return channel.port1;
		},
		async bind(principal, signal) {
			const reply = await control({ type: 'bind', principal }, [], signal);
			if (reply.generation === null) throw new SharedCoreError('shared_core_bad_reply');
			generation = reply.generation;
			return reply.generation;
		},
		async unbind(signal) {
			if (generation === null) return;
			const ending = generation;
			await control({ type: 'unbind', generation: ending }, [], signal);
			if (generation === ending) generation = null;
		},
		async prewarm(signal) {
			await control({ type: 'prewarm' }, [], signal);
		},
		onCrash(listener) {
			crashListeners.add(listener);
			return () => { crashListeners.delete(listener); };
		},
		terminate() {
			const active = worker;
			worker = null;
			generation = null;
			active?.terminate();
			failAll('shared_core_terminated');
		}
	};
}

let registered: SharedRustCore | null = null;

/** Registers the single shared core; returns an unregister function bound to this exact registration. */
export function registerSharedRustCore(core: SharedRustCore): () => void {
	registered = core;
	return () => { if (registered === core) registered = null; };
}
/** True only when the Rust-core build registered the shared Worker. */
export function isSharedRustCoreRegistered(): boolean { return registered !== null; }
/** Throws `rust_core_not_enabled` when nothing is registered (flag OFF). */
export function requireSharedRustCore(): SharedRustCore {
	if (!registered) throw new SharedCoreError('rust_core_not_enabled');
	return registered;
}
