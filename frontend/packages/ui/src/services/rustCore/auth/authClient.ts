/**
 * Page-side client for the Rust auth Worker. Executes the HTTP requests Rust
 * describes through the supplied page executor and resolves each call with the
 * Rust result. Any protocol violation or Worker failure rejects every pending
 * call with `rust_core_unavailable`; there is no TypeScript fallback.
 */
import { AUTH_PROTOCOL_VERSION, isAuthFromWorker, type AuthCall, type AuthHttpReply, type AuthHttpRequest } from './authProtocol';

export interface AuthEndpoint {
	postMessage(message: unknown): void;
	addEventListener(type: 'message' | 'error' | 'messageerror', listener: (event: MessageEvent<unknown>) => void): void;
	terminate(): void;
}
export class RustAuthError extends Error {
	constructor(readonly code: string) { super(code); this.name = 'RustAuthError'; }
}
export interface RustAuthClient {
	call<T>(call: AuthCall): Promise<T>;
	close(): void;
}
export type AuthHttpExecutor = (request: AuthHttpRequest) => Promise<AuthHttpReply>;

const READY_TIMEOUT_MS = 30_000;

export function createAuthClient(endpoint: AuthEndpoint, execute: AuthHttpExecutor): RustAuthClient {
	let nextId = 1;
	let closed = false;
	const pending = new Map<number, { resolve(value: unknown): void; reject(error: RustAuthError): void }>();
	let readyResolve!: () => void;
	let readyReject!: (error: RustAuthError) => void;
	const ready = new Promise<void>((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
	void ready.catch(() => undefined);
	const timer = setTimeout(() => fail(), READY_TIMEOUT_MS);

	function fail(): void {
		if (closed) return;
		closed = true;
		clearTimeout(timer);
		const error = new RustAuthError('rust_core_unavailable');
		readyReject(error);
		for (const waiting of pending.values()) waiting.reject(error);
		pending.clear();
		endpoint.terminate();
	}
	const post = (message: Record<string, unknown>) => endpoint.postMessage({ v: AUTH_PROTOCOL_VERSION, ...message });

	endpoint.addEventListener('error', () => fail());
	endpoint.addEventListener('messageerror', () => fail());
	endpoint.addEventListener('message', (event) => {
		const data = event.data;
		if (!isAuthFromWorker(data)) return fail();
		if ('ready' in data) {
			clearTimeout(timer);
			if (data.ready) readyResolve(); else fail();
			return;
		}
		const waiting = pending.get(data.id);
		if (!waiting) return fail();
		if ('http' in data) {
			const id = data.id;
			execute(data.http).then(
				(reply) => { if (!closed) post({ id, reply }); },
				() => { if (!closed) post({ id, replyFailed: true }); },
			);
			return;
		}
		pending.delete(data.id);
		if (data.ok) waiting.resolve(data.value); else waiting.reject(new RustAuthError(data.code));
	});

	return {
		async call<T>(call: AuthCall): Promise<T> {
			await ready;
			if (closed) throw new RustAuthError('rust_core_unavailable');
			const id = nextId++;
			return new Promise<T>((resolve, reject) => {
				pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
				post({ id, ...call });
			});
		},
		close(): void {
			if (closed) return;
			closed = true;
			clearTimeout(timer);
			const error = new RustAuthError('cancelled');
			for (const waiting of pending.values()) waiting.reject(error);
			pending.clear();
			endpoint.terminate();
		},
	};
}
