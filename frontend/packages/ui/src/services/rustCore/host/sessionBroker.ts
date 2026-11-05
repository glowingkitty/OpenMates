/**
 * Session broker over the single shared Rust core Worker.
 *
 * One admission per principal: the broker is the only caller of
 * `SharedRustCore.bind`, binds a principal once and reuses that generation for
 * every lease. A lease is one `core` unit port (one Worker-side dispatcher with
 * its own Rust client) under that generation; leases are reference counted.
 *
 * `lease.close()` never terminates the shared Worker: it asks the Worker-side
 * core unit to dispose its dispatcher (`CORE_UNIT_CLOSE` frame) and closes the
 * page end of the port. The realm, its single WASM instance and the bound
 * generation stay for the next lease.
 *
 * A lease is *lost* (listeners notified, port closed) when the Worker crashes,
 * when a different principal is admitted (the old generation is unbound first,
 * which also closes its Worker-side ports) or when the broker is disposed.
 * There is no TypeScript fallback.
 */
import { SharedCoreError, type SharedRustCore } from './sharedCoreRegistry';

/** Page -> core unit frame that disposes the unit's dispatcher. Never a valid core request. */
export const CORE_UNIT_CLOSE = Object.freeze({ coreUnitClose: 1 as const });

/** True only for the exact `CORE_UNIT_CLOSE` frame shape. */
export function isCoreUnitClose(value: unknown): boolean {
	return typeof value === 'object' && value !== null && Object.getPrototypeOf(value) === Object.prototype
		&& Object.keys(value).length === 1 && (value as Record<string, unknown>).coreUnitClose === 1;
}

const PRINCIPAL = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;

export interface CoreLease {
	/** Page end of the `core` unit port. */
	readonly port: MessagePort;
	readonly principal: string;
	readonly generation: number;
	/** True after `close()` or after the lease was lost. */
	readonly closed: boolean;
	/** Releases this lease only (idempotent). The shared Worker keeps running. */
	close(): void;
	/** Notified once if the lease ends without `close()` (crash, principal switch, dispose). */
	onLost(listener: () => void): () => void;
}

export interface LeaseOptions {
	signal?: AbortSignal;
	/** Extra core ports in their documented positions (extraPorts[0] is the recovery port). */
	extraPorts?: MessagePort[];
}

export interface SessionBroker {
	/** Loads the shared Worker's WASM binding early (no admission). */
	prewarm(signal?: AbortSignal): Promise<void>;
	/** Admits `principal` once (reused afterwards) and opens one core unit lease under it. */
	lease(principal: string, options?: LeaseOptions): Promise<CoreLease>;
	/** Principal of the current admission, null when none. */
	readonly principal: string | null;
	/** Open leases of the current admission. */
	readonly activeLeases: number;
	/** Loses every lease and unbinds the current admission. The broker stays usable. */
	dispose(): Promise<void>;
}

interface LeaseState { lease: CoreLease; lose(): void }
interface Admission { principal: string; bound: Promise<number>; leases: Set<LeaseState>; ended: boolean }

export function createSessionBroker(core: SharedRustCore): SessionBroker {
	let admission: Admission | null = null;
	// Admission changes (bind, principal switch, dispose) run one at a time.
	let transitions: Promise<unknown> = Promise.resolve();

	const serialize = <T>(task: () => Promise<T>): Promise<T> => {
		const run = transitions.then(task);
		transitions = run.catch(() => undefined);
		return run;
	};

	const end = (ending: Admission): void => {
		if (ending.ended) return;
		ending.ended = true;
		if (admission === ending) admission = null;
		for (const state of [...ending.leases]) state.lose();
	};

	core.onCrash(() => { if (admission) end(admission); });

	const admit = (principal: string, signal?: AbortSignal): Promise<Admission> => serialize(async () => {
		if (signal?.aborted) throw new SharedCoreError('shared_core_aborted');
		const current = admission;
		if (current && current.principal === principal && !current.ended) return current;
		if (current) {
			end(current);
			await core.unbind();
		}
		const next: Admission = { principal, bound: core.bind(principal, signal), leases: new Set(), ended: false };
		admission = next;
		try {
			await next.bound;
		} catch (error) {
			end(next);
			throw error;
		}
		return next;
	});

	return {
		get principal() { return admission?.principal ?? null; },
		get activeLeases() { return admission?.leases.size ?? 0; },
		prewarm(signal) { return core.prewarm(signal); },
		async lease(principal, options = {}) {
			if (!PRINCIPAL.test(principal)) {
				for (const port of options.extraPorts ?? []) port.close();
				throw new SharedCoreError('bad_envelope');
			}
			let owner: Admission;
			try {
				owner = await admit(principal, options.signal);
			} catch (error) {
				for (const port of options.extraPorts ?? []) port.close();
				throw error;
			}
			const generation = await owner.bound;
			const port = await core.openUnit('core', { extraPorts: options.extraPorts, signal: options.signal });
			if (owner.ended || admission !== owner || core.generation !== generation) {
				port.close();
				throw new SharedCoreError('stale_generation');
			}
			let closed = false;
			const lostListeners = new Set<() => void>();
			const release = () => {
				closed = true;
				owner.leases.delete(state);
				port.postMessage(CORE_UNIT_CLOSE);
				port.close();
			};
			const lease: CoreLease = {
				port, principal, generation,
				get closed() { return closed; },
				close() { if (!closed) release(); },
				onLost(listener) {
					lostListeners.add(listener);
					return () => { lostListeners.delete(listener); };
				}
			};
			const state: LeaseState = {
				lease,
				lose() {
					if (closed) return;
					release();
					for (const listener of [...lostListeners]) listener();
					lostListeners.clear();
				}
			};
			owner.leases.add(state);
			return lease;
		},
		dispose() {
			return serialize(async () => {
				const current = admission;
				if (!current) return;
				end(current);
				await core.unbind();
			});
		}
	};
}
