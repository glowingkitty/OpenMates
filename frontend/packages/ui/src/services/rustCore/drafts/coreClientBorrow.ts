/**
 * Borrow of a core dispatcher's ADMITTED Rust client by a sibling unit of the
 * same shared Worker realm (the `drafts` unit).
 *
 * No second client and no second admission: the drafts unit runs its short Rust
 * draft calls on the client the history `core` lease already admitted for the
 * bound principal. A borrow is granted only while that dispatcher is idle (no
 * request, client phase, send, initial sync or admission in flight) and marks
 * the dispatcher busy until released, exactly like one of its own requests: a
 * request arriving meanwhile is held and delivered when the borrow is released.
 * The client is never freed under a borrow: `reading` defers its retirement and
 * `release()` completes a retirement that happened meanwhile.
 *
 * Registration is the single hook in workerRuntime.ts (`registerCoreClientBorrows`).
 */
import type { WorkerRuntimeState } from '../workerRuntimeState';
import { retireOriginalClient } from '../workerRuntimeState';
import type { RustClient } from '../workerRuntimeTypes';

/** Admitted session identity of a borrowed client (read while idle). */
export interface BorrowedCoreStatus { readonly handle: string; readonly generation: number; readonly principal: string }
export interface CoreClientBorrow {
	readonly client: RustClient;
	readonly status: BorrowedCoreStatus;
	/** Idempotent. The dispatcher accepts requests again afterwards. */
	release(): void;
}
/**
 * `none`: no admitted client for the principal (history not bound); `local`: only
 * a local-only (cache-read) client, which has no server authority; `busy`: an
 * admitted client exists but its dispatcher stayed busy.
 */
export type CoreBorrowRefusal = 'none' | 'local' | 'busy';

const sources = new Set<WorkerRuntimeState>();
/**
 * Page requests that reached a dispatcher while a borrow was active, in arrival
 * order. They are delivered to the dispatcher's own listener when the borrow is
 * released, so a history request that lands in the gap between two of its
 * requests waits a few milliseconds instead of being refused as busy.
 */
const deferred = new WeakMap<WorkerRuntimeState, { lent: boolean; events: Event[]; deliver: (event: Event) => void }>();

/** Called once per core dispatcher by installBrowserCoreWorker; returns the unregister hook. */
export function registerCoreClientBorrows(rt: WorkerRuntimeState): () => void {
	sources.add(rt);
	const deliver = rt.receiveListener;
	const gate = { lent: false, events: [] as Event[], deliver };
	deferred.set(rt, gate);
	// The dispatcher re-adds `rt.receiveListener` itself (owned cache reads), so the
	// gate replaces that one listener rather than adding a second.
	const gated = (event: Event) => {
		if (gate.lent || gate.events.length > 0) gate.events.push(event);
		else deliver(event);
	};
	rt.endpoint.removeEventListener('message', deliver);
	rt.receiveListener = gated;
	rt.endpoint.addEventListener('message', gated);
	return () => {
		sources.delete(rt);
		deferred.delete(rt);
		gate.events.length = 0;
	};
}

/** Delivers requests held during a borrow, stopping if one of them lends the client again. */
function flushDeferred(rt: WorkerRuntimeState): void {
	const gate = deferred.get(rt);
	if (!gate || gate.lent) return;
	while (gate.events.length > 0 && !gate.lent) gate.deliver(gate.events.shift() as Event);
}

/**
 * Owned cache reads drive Rust operations on the client without setting
 * `reading`; a draft operation entering between their awaits would unwind the
 * client's active-operation lease out of order, so any in-flight read is busy.
 */
function idle(rt: WorkerRuntimeState): boolean {
	return !rt.busy && rt.reading === null && rt.sending === null && rt.initialSync === null
		&& rt.firstSessionTask === null && rt.passwordAdmission === null
		&& rt.cacheRead === null && rt.localRead === null && rt.ownedCacheReads.size === 0;
}

function lend(rt: WorkerRuntimeState, client: RustClient): () => void {
	rt.busy = true;
	rt.reading = client;
	const gate = deferred.get(rt);
	if (gate) gate.lent = true;
	let released = false;
	return () => {
		if (released) return;
		released = true;
		if (rt.reading === client) rt.reading = null;
		rt.busy = false;
		if (gate) gate.lent = false;
		retireOriginalClient(rt, client);
		flushDeferred(rt);
	};
}

/** One attempt. Local-only (cache-read) admissions confer no server authority and are skipped. */
export function tryBorrowCoreClient(principal: string): CoreClientBorrow | CoreBorrowRefusal {
	let busy = false, local = false;
	for (const rt of sources) {
		const client = rt.client, expected = rt.configuration.expectedPrincipal;
		if (rt.disposed || !client || rt.configuration.admission !== 'existing_key' || !expected
			|| expected.toLowerCase() !== principal.toLowerCase()) continue;
		if (!idle(rt)) { busy = true; continue; }
		const release = lend(rt, client);
		const status = client.admitted_status();
		let snapshot: BorrowedCoreStatus | null = null, statusLocal = false;
		try {
			statusLocal = status.local_read_only === true;
			if (status.local_read_only !== true && status.principal.toLowerCase() === principal.toLowerCase()) {
				snapshot = Object.freeze({ handle: status.handle, generation: status.generation, principal: status.principal });
			}
		} finally { status.free(); }
		if (!snapshot) { local ||= statusLocal; release(); continue; }
		return Object.freeze({ client, status: snapshot, release });
	}
	return busy ? 'busy' : local ? 'local' : 'none';
}

const RETRY_MS = 20;

/** Waits (bounded) for an idle admitted client. Never borrows past `signal`. */
export async function borrowCoreClient(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal> {
	const deadline = Date.now() + timeoutMs;
	for (;;) {
		if (signal.aborted) throw new Error('cancelled');
		const outcome = tryBorrowCoreClient(principal);
		if (outcome !== 'busy' || Date.now() >= deadline) return outcome;
		await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
	}
}
