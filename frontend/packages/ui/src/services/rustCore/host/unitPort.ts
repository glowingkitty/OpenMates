/**
 * Typed request/response over one shared-Worker namespace MessagePort.
 *
 * Wire (v1): `{v:1,id,type:'request',op,payload}` and `{v:1,id,type:'cancel'}`
 * from the page; `{v:1,id,type:'result',ok:true,value}` or
 * `{v:1,id,type:'result',ok:false,code}` from the unit. Units that already have
 * their own protocol keep it and do not need this helper.
 *
 * Supervision: the shared-core client (sharedCoreRegistry.ts) ends every live
 * page port it opened through `retireUnitPorts` the moment its generation is
 * unbound (`unit_unbound`) or the Worker realm crashes / is terminated
 * (`unit_retired`). Pending requests reject at once with that code, and so does
 * every later request on that port; the caller opens a new port after rebind.
 */

export const UNIT_PORT_VERSION = 1 as const;
export const UNIT_PORT_DEFAULT_TIMEOUT_MS = 30_000;

/** Map of operation name to its request and response payloads. */
export type UnitProtocol = Record<string, { request: unknown; response: unknown }>;

export type UnitPortErrorCode = 'unit_timeout' | 'unit_aborted' | 'unit_closed' | 'unit_unbound' | 'unit_retired' | 'unit_bad_reply'
	| (string & {});
/** Codes the supervisor ends a port with: its generation was unbound, or its Worker realm is gone. */
export type UnitRetireCode = 'unit_unbound' | 'unit_retired';
export class UnitPortError extends Error {
	constructor(readonly code: UnitPortErrorCode) {
		super(code);
		this.name = 'UnitPortError';
	}
}

export interface UnitRequestOptions { signal?: AbortSignal; timeoutMs?: number; transfer?: Transferable[] }

export interface UnitPort<P extends UnitProtocol> {
	request<K extends keyof P & string>(op: K, payload: P[K]['request'], options?: UnitRequestOptions): Promise<P[K]['response']>;
	/** Rejects every pending request with `unit_closed` and closes the port. */
	close(): void;
	/** True after `close()` or after the supervisor retired the port. */
	readonly closed: boolean;
}

const ERROR_CODE = /^[a-z][a-z0-9_]{0,63}$/;

interface Pending { resolve(value: unknown): void; reject(error: UnitPortError): void; cleanup(): void }

/** Live page-side unit ports (removed when they end), keyed by their MessagePort. */
const live = new Map<MessagePort, (code: UnitRetireCode) => void>();

/**
 * Ends every live unit port whose MessagePort `select` picks: pending and later
 * requests reject with `code`. Called by the shared-core supervisor only.
 */
export function retireUnitPorts(select: (port: MessagePort) => boolean, code: UnitRetireCode): void {
	for (const [port, retire] of [...live]) if (select(port)) retire(code);
}

export function createUnitPort<P extends UnitProtocol>(port: MessagePort, defaults: { timeoutMs?: number } = {}): UnitPort<P> {
	const pending = new Map<number, Pending>();
	let nextId = 1;
	let closed = false;
	let endCode: UnitPortErrorCode = 'unit_closed';

	function settle(id: number): Pending | undefined {
		const entry = pending.get(id);
		if (!entry) return undefined;
		pending.delete(id);
		entry.cleanup();
		return entry;
	}

	port.onmessage = (event: MessageEvent<unknown>) => {
		const data = event.data as Record<string, unknown> | null;
		if (typeof data !== 'object' || data === null || data.v !== UNIT_PORT_VERSION || data.type !== 'result'
			|| typeof data.id !== 'number') return;
		const entry = settle(data.id);
		if (!entry) return;
		if (data.ok === true) entry.resolve(data.value);
		else if (data.ok === false && typeof data.code === 'string' && ERROR_CODE.test(data.code)) entry.reject(new UnitPortError(data.code));
		else entry.reject(new UnitPortError('unit_bad_reply'));
	};
	port.start();

	const unit: UnitPort<P> = {
		get closed() { return closed; },
		request(op, payload, options = {}) {
			if (closed) return Promise.reject(new UnitPortError(endCode));
			const { signal } = options;
			if (signal?.aborted) return Promise.reject(new UnitPortError('unit_aborted'));
			const id = nextId++;
			const timeoutMs = options.timeoutMs ?? defaults.timeoutMs ?? UNIT_PORT_DEFAULT_TIMEOUT_MS;
			return new Promise((resolve, reject) => {
				const cancel = (code: UnitPortErrorCode) => {
					const entry = settle(id);
					if (!entry) return;
					if (!closed) port.postMessage({ v: UNIT_PORT_VERSION, id, type: 'cancel' });
					entry.reject(new UnitPortError(code));
				};
				const onAbort = () => cancel('unit_aborted');
				const timer = setTimeout(() => cancel('unit_timeout'), timeoutMs);
				signal?.addEventListener('abort', onAbort, { once: true });
				pending.set(id, {
					resolve: resolve as (value: unknown) => void,
					reject,
					cleanup() { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); }
				});
				port.postMessage({ v: UNIT_PORT_VERSION, id, type: 'request', op, payload }, options.transfer ?? []);
			});
		},
		close() { end('unit_closed'); }
	};

	function end(code: UnitPortErrorCode): void {
		if (closed) return;
		closed = true;
		endCode = code;
		live.delete(port);
		for (const id of [...pending.keys()]) settle(id)?.reject(new UnitPortError(code));
		port.onmessage = null;
		port.close();
	}
	live.set(port, end);
	return unit;
}

/** Unit-side handler map: each handler receives an AbortSignal fired by a page `cancel`. */
export type UnitHandlers<P extends UnitProtocol> = {
	[K in keyof P & string]: (payload: P[K]['request'], signal: AbortSignal) => Promise<P[K]['response']> | P[K]['response'];
};

/** Thrown by a unit handler to answer with a fixed error code. */
export class UnitRefusal extends Error {
	constructor(readonly code: string) {
		super(code);
		this.name = 'UnitRefusal';
	}
}

/**
 * Serves a unit's handlers on its port (Worker side). A handler that throws
 * `UnitRefusal` answers with its code; any other throw answers `unit_failed`
 * so internal error text never crosses the port.
 */
export function serveUnitPort<P extends UnitProtocol>(port: MessagePort, handlers: UnitHandlers<P>): () => void {
	const running = new Map<number, AbortController>();
	port.onmessage = async (event: MessageEvent<unknown>) => {
		const data = event.data as Record<string, unknown> | null;
		if (typeof data !== 'object' || data === null || data.v !== UNIT_PORT_VERSION || typeof data.id !== 'number') return;
		const id = data.id;
		if (data.type === 'cancel') { running.get(id)?.abort(); return; }
		if (data.type !== 'request') return;
		const handler = typeof data.op === 'string' && Object.hasOwn(handlers, data.op)
			? (handlers as Record<string, (payload: unknown, signal: AbortSignal) => unknown>)[data.op] : undefined;
		if (!handler) { port.postMessage({ v: UNIT_PORT_VERSION, id, type: 'result', ok: false, code: 'unknown_operation' }); return; }
		const controller = new AbortController();
		running.set(id, controller);
		try {
			const value = await handler(data.payload, controller.signal);
			port.postMessage({ v: UNIT_PORT_VERSION, id, type: 'result', ok: true, value });
		} catch (error) {
			const code = error instanceof UnitRefusal && ERROR_CODE.test(error.code) ? error.code : 'unit_failed';
			port.postMessage({ v: UNIT_PORT_VERSION, id, type: 'result', ok: false, code });
		} finally {
			running.delete(id);
		}
	};
	port.start();
	return () => {
		for (const controller of running.values()) controller.abort();
		running.clear();
		port.onmessage = null;
	};
}
