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
 * dead) and terminates the Worker. `terminate()` (idle retirement, logout /
 * account switch hard stop) notifies the same listeners; each listener is told
 * which of the two happened. The next request respawns a fresh Worker.
 * There is no TypeScript fallback.
 *
 * Unit ports: every `createUnitPort` over a port this client opened is ended
 * here, not by its 30 s request timeout. `unbind()` ends the ports of the
 * ending generation with `unit_unbound` as soon as the unbind is sent (the
 * Worker may be busy in that very request); ports opened unbound (pre-bind
 * units such as search and embedData) are untouched. A crash or `terminate()`
 * ends every port with `unit_retired`. Callers open a new port to continue.
 */
import {
	SHARED_WORKER_PROTOCOL_VERSION,
	parseSharedControlReply,
	type SharedControlReply,
	type SharedNamespace,
	type SharedRefusalCode
} from './sharedWorkerProtocol';
import { retireUnitPorts, type UnitRetireCode } from './unitPort';

export const SHARED_CORE_CONTROL_TIMEOUT_MS = 30_000;

export type SharedCoreErrorCode = SharedRefusalCode | 'shared_core_crashed' | 'shared_core_timeout' | 'shared_core_bad_reply'
	| 'shared_core_terminated' | 'shared_core_aborted' | 'rust_core_not_enabled';
export class SharedCoreError extends Error {
	constructor(readonly code: SharedCoreErrorCode) {
		super(code);
		this.name = 'SharedCoreError';
	}
}

/** Why the shared Worker stopped: it failed (`crashed`) or was stopped on purpose (`terminated`). */
export type SharedCoreStop = 'crashed' | 'terminated';

export interface OpenUnitOptions {
	/** Extra ports in their documented positions (core: ports[1] is the recovery port). */
	extraPorts?: MessagePort[];
	signal?: AbortSignal;
	/** Open a pre-bind namespace (crypto/auth) outside any generation, so unbind does not close it. */
	unbound?: boolean;
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
	/**
	 * Subscribes to Worker stops, a crash and a planned `terminate()` alike (unit ports are dead
	 * either way); the listener gets the reason. Returns the unsubscribe function.
	 */
	onCrash(listener: (stop: SharedCoreStop) => void): () => void;
	/** Terminates the Worker (logout / account switch hard stop). Later calls respawn. */
	terminate(): void;
	/**
	 * Marks unit work in flight (a crypto/core call). Returns an idempotent release.
	 * A crash or `terminate()` clears every lease, so a dead unit cannot pin the realm.
	 */
	hold(): () => void;
	/** True while a control request (open/bind/unbind/prewarm) is pending or a lease is held. */
	readonly busy: boolean;
	/** Calls `listener` once when the realm next becomes idle; returns the cancel function. */
	onIdle(listener: () => void): () => void;
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
	const crashListeners = new Set<(stop: SharedCoreStop) => void>();
	const pending = new Map<number, Pending>();
	let worker: SharedWorkerEndpoint | null = null;
	let generation: number | null = null;
	let nextId = 1;
	let leases = 0;
	let leaseEpoch = 0;
	const idleListeners = new Set<() => void>();
	// Page end of each opened port -> its generation (null: opened unbound). Weak: closed ports just drop out.
	const opened = new WeakMap<MessagePort, number | null>();
	// Generation whose unbind is in flight; an `open` answered meanwhile is already stale.
	let ending: number | null = null;

	function retirePorts(code: UnitRetireCode, ofGeneration?: number): void {
		retireUnitPorts((port) => opened.has(port) && (ofGeneration === undefined || opened.get(port) === ofGeneration), code);
	}

	function isBusy(): boolean { return pending.size > 0 || leases > 0; }
	function settleIdle(): void {
		if (isBusy()) return;
		const listeners = [...idleListeners];
		idleListeners.clear();
		for (const listener of listeners) listener();
	}
	function clearLeases(): void { leases = 0; leaseEpoch++; }

	function failAll(code: SharedCoreErrorCode): void {
		for (const [id, entry] of [...pending]) {
			pending.delete(id);
			entry.cleanup();
			entry.reject(new SharedCoreError(code));
		}
		settleIdle();
	}
	function crash(failed: SharedWorkerEndpoint): void {
		if (worker !== failed) return;
		worker = null;
		generation = null;
		ending = null;
		clearLeases();
		failed.terminate();
		failAll('shared_core_crashed');
		retirePorts('unit_retired');
		for (const listener of [...crashListeners]) listener('crashed');
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
			settleIdle();
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
				settleIdle();
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
			const under = open.unbound ? null : generation;
			try {
				await control({ type: 'open', ns, generation: under }, ports, open.signal);
			} catch (error) {
				channel.port1.close();
				throw error;
			}
			// Opened under a generation whose unbind was sent meanwhile: the Worker closes it right after.
			if (under !== null && (under !== generation || under === ending)) {
				channel.port1.close();
				throw new SharedCoreError('stale_generation');
			}
			opened.set(channel.port1, under);
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
			if (signal?.aborted) throw new SharedCoreError('shared_core_aborted');
			const unbinding = generation;
			ending = unbinding;
			const sent = control({ type: 'unbind', generation: unbinding }, [], signal);
			retirePorts('unit_unbound', unbinding);
			try {
				await sent;
			} finally {
				if (ending === unbinding) ending = null;
			}
			if (generation === unbinding) generation = null;
		},
		async prewarm(signal) {
			await control({ type: 'prewarm' }, [], signal);
		},
		onCrash(listener) {
			crashListeners.add(listener);
			return () => { crashListeners.delete(listener); };
		},
		get busy() { return isBusy(); },
		hold() {
			const epoch = leaseEpoch;
			let released = false;
			leases++;
			return () => {
				if (released || epoch !== leaseEpoch) return;
				released = true;
				leases--;
				settleIdle();
			};
		},
		onIdle(listener) {
			idleListeners.add(listener);
			return () => { idleListeners.delete(listener); };
		},
		terminate() {
			const active = worker;
			worker = null;
			generation = null;
			ending = null;
			clearLeases();
			active?.terminate();
			failAll('shared_core_terminated');
			retirePorts('unit_retired');
			if (active) for (const listener of [...crashListeners]) listener('terminated');
		}
	};
}

let registered: SharedRustCore | null = null;
const registrationWaiters = new Set<(core: SharedRustCore) => void>();

/** Registers the single shared core; returns an unregister function bound to this exact registration. */
export function registerSharedRustCore(core: SharedRustCore): () => void {
	registered = core;
	for (const waiter of [...registrationWaiters]) waiter(core);
	return () => { if (registered === core) registered = null; };
}
/**
 * Resolves with the registered core, waiting for a registration still in flight
 * (the web_app registers it from a lazily imported chunk). Rejects with
 * `shared_core_timeout` after `timeoutMs` and `shared_core_aborted` on abort.
 */
export function whenSharedRustCore(options: { timeoutMs?: number; signal?: AbortSignal } = {}): Promise<SharedRustCore> {
	if (registered) return Promise.resolve(registered);
	if (options.signal?.aborted) return Promise.reject(new SharedCoreError('shared_core_aborted'));
	return new Promise((resolve, reject) => {
		const settle = (error: SharedCoreError | null, core?: SharedRustCore) => {
			registrationWaiters.delete(waiter);
			clearTimeout(timer);
			options.signal?.removeEventListener('abort', onAbort);
			if (error) reject(error); else resolve(core!);
		};
		const waiter = (core: SharedRustCore) => settle(null, core);
		const onAbort = () => settle(new SharedCoreError('shared_core_aborted'));
		const timer = setTimeout(() => settle(new SharedCoreError('shared_core_timeout')), options.timeoutMs ?? SHARED_CORE_CONTROL_TIMEOUT_MS);
		options.signal?.addEventListener('abort', onAbort, { once: true });
		registrationWaiters.add(waiter);
	});
}
/** True only when the Rust-core build registered the shared Worker. */
export function isSharedRustCoreRegistered(): boolean { return registered !== null; }
/** Throws `rust_core_not_enabled` when nothing is registered (flag OFF). */
export function requireSharedRustCore(): SharedRustCore {
	if (!registered) throw new SharedCoreError('rust_core_not_enabled');
	return registered;
}
