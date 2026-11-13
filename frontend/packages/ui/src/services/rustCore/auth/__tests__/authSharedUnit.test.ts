// contract-test-file: tooling
// Rust web auth on the shared Rust core Worker: the pre-bind `auth` unit
// (installer, close frame, in-flight login release), the page client over the
// unit port, and realm retirement (terminate + respawn, bound-session guard).
// The real router and installer run in-process with a synthetic binding.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AUTH_UNIT_CLOSE, isAuthUnitClose } from '../authProtocol';
import { installAuthUnit } from '../authUnit';
import { createSharedAuthClient, loadSharedAuthRealm } from '../authWorkerPort';
import type { RustWebAuthBinding } from '../authWorkerRuntime';
import { createSharedCoreClient, registerSharedRustCore, whenSharedRustCore, type SharedWorkerEndpoint } from '../../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../../host/sharedWorkerProtocol';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';
const challenge = JSON.stringify({ method: 'POST', path: '/v1/auth/password-v2/challenge', headers: [], body: null });

function binding(): RustWebAuthBinding & { freed: number } {
	const state = { freed: 0 };
	return Object.assign(state, {
		WebAuthPasswordLogin: {
			start: () => ({
				request: () => challenge,
				reply: () => true,
				finish: async () => ({ kind: 'unlocked', status: 200, data: '{}' }),
				free: () => { state.freed++; },
			}),
		},
		WebAuthRecoveryLogin: { start: () => ({ request: () => undefined, finish: async () => ({}) }) },
		web_auth_session_request: (_signals: string, sessionId: string) =>
			JSON.stringify({ method: 'POST', path: '/v1/auth/session', headers: [], body: sessionId }),
		web_auth_classify_session: (status: number) => JSON.stringify({ kind: 'unreachable', status }),
		web_auth_missing_key_plan: () => '{}',
		web_auth_logout_server_step: () => '{"kind":"none"}',
		web_auth_logout_may_delete_cookies: () => true,
		web_auth_logout_frame: (tab: string) => tab,
		web_auth_accept_logout_frame: () => false,
	});
}

/** In-process shared Worker running the real router with the real auth installer. */
function sharedCore(rust: RustWebAuthBinding) {
	const workers: { terminated: boolean; posted: Record<string, unknown>[] }[] = [];
	const core = createSharedCoreClient(() => {
		const listeners: ((event: Event) => void)[] = [];
		const router = createSharedWorkerRouter({
			installers: { auth: installAuthUnit },
			loadBinding: async () => rust,
			reply: (reply) => queueMicrotask(() => { for (const listener of listeners) listener({ data: reply } as MessageEvent); }),
		});
		const state = { terminated: false, posted: [] as Record<string, unknown>[] };
		workers.push(state);
		const endpoint: SharedWorkerEndpoint = {
			postMessage(message, transfer) { state.posted.push(message as Record<string, unknown>); void router.handle(message, transfer as MessagePort[]); },
			addEventListener(type, listener) { if (type === 'message') listeners.push(listener); },
			terminate() { state.terminated = true; },
		};
		return endpoint;
	});
	return { core, workers, unregister: registerSharedRustCore(core) };
}

let cleanup: (() => void) | null = null;
afterEach(() => { cleanup?.(); cleanup = null; vi.useRealTimers(); });

describe('auth unit on the shared Rust core Worker', () => {
	it('accepts only the exact close frame', () => {
		expect(isAuthUnitClose(AUTH_UNIT_CLOSE)).toBe(true);
		expect(isAuthUnitClose({ v: 1, authUnitClose: true, id: 1 })).toBe(false);
		expect(isAuthUnitClose({ v: 1, id: 1, op: 'logout_frame', tabId: 't' })).toBe(false);
	});

	it('refuses to install without the Rust auth exports or with extra ports', () => {
		const { port1, port2 } = new MessageChannel();
		const context = { ports: [port1], generation: null, principal: null, signal: new AbortController().signal };
		expect(() => installAuthUnit({ ...context, binding: {} })).toThrow('unavailable');
		expect(() => installAuthUnit({ ...context, ports: [port1, port2], binding: binding() })).toThrow('unavailable');
		port1.close();
		port2.close();
	});

	it('opens unbound, runs calls and survives unbind of the bound generation', async () => {
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		await shared.core.bind(PRINCIPAL);
		const onClosed = vi.fn();
		const client = await createSharedAuthClient(async () => ({ status: 200, body: null }), onClosed);
		const open = shared.workers[0].posted.find((message) => message.type === 'open');
		expect(open).toMatchObject({ ns: 'auth', generation: null });
		await expect(client.call({ op: 'session_request', signals: '[]', sessionId: 'sid' }))
			.resolves.toMatchObject({ path: '/v1/auth/session', body: 'sid' });
		await shared.core.unbind();
		await expect(client.call({ op: 'classify_session', status: 503, body: null })).resolves.toEqual({ kind: 'unreachable', status: 503 });
		client.close();
		expect(onClosed).toHaveBeenCalledTimes(1);
		expect(shared.workers[0].terminated).toBe(false);
	});

	it('closing the client frees a login waiting for the page reply', async () => {
		const rust = binding();
		const shared = sharedCore(rust);
		cleanup = shared.unregister;
		let requested!: () => void;
		const sawRequest = new Promise<void>((resolve) => { requested = resolve; });
		const client = await createSharedAuthClient(() => { requested(); return new Promise(() => undefined); }, () => undefined);
		const login = client.call({ op: 'password_login', password: 'pw', tfa: null,
			input: { email: 'a@example.com', sessionId: 's', userEmailSalt: 'x', emailEncryptionKey: null, stayLoggedIn: false, codeType: null } });
		await sawRequest;
		client.close();
		await expect(login).rejects.toMatchObject({ code: 'cancelled' });
		await vi.waitFor(() => expect(rust.freed).toBe(1));
	});

	it('retirement terminates and respawns an unbound realm and ends open clients', async () => {
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		const onClosed = vi.fn();
		const client = await createSharedAuthClient(async () => ({ status: 200, body: null }), onClosed);
		(await loadSharedAuthRealm()).retire({ force: false });
		expect(shared.workers[0].terminated).toBe(true);
		expect(onClosed).toHaveBeenCalledTimes(1);
		await expect(client.call({ op: 'logout_frame', tabId: 't' })).rejects.toMatchObject({ code: 'rust_core_unavailable' });
		expect(shared.workers).toHaveLength(2);
		await vi.waitFor(() => expect(shared.workers[1].posted.map((message) => message.type)).toEqual(['prewarm']));
		const next = await createSharedAuthClient(async () => ({ status: 200, body: null }), () => undefined);
		await expect(next.call({ op: 'logout_frame', tabId: 't' })).resolves.toBe('t');
		next.close();
	});

	it('defers idle retirement while a bind is pending and never kills it', async () => {
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		const binding_ = shared.core.bind(PRINCIPAL);
		expect(shared.core.busy).toBe(true);
		(await loadSharedAuthRealm()).retire({ force: false });
		expect(shared.workers[0].terminated).toBe(false);
		await expect(binding_).resolves.toBe(1);
		await new Promise((resolve) => setTimeout(resolve, 10));
		expect(shared.workers[0].terminated).toBe(false);
		expect(shared.core.generation).toBe(1);
	});

	it('lets a crypto call in flight complete before the idle retirement', async () => {
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		await shared.core.prewarm();
		const release = shared.core.hold();
		(await loadSharedAuthRealm()).retire({ force: false });
		expect(shared.workers[0].terminated).toBe(false);
		release();
		await vi.waitFor(() => expect(shared.workers[0].terminated).toBe(true));
		expect(shared.workers).toHaveLength(2);
	});

	it('retires immediately when the realm is truly idle, and a forced retire ignores work', async () => {
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		await shared.core.prewarm();
		expect(shared.core.busy).toBe(false);
		(await loadSharedAuthRealm()).retire({ force: false });
		expect(shared.workers[0].terminated).toBe(true);
		shared.core.hold();
		(await loadSharedAuthRealm()).retire({ force: true });
		expect(shared.workers[1].terminated).toBe(true);
	});

	it('keeps a bound realm unless forced (logout)', async () => {
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		await shared.core.bind(PRINCIPAL);
		const crashed = vi.fn();
		shared.core.onCrash(crashed);
		(await loadSharedAuthRealm()).retire({ force: false });
		expect(shared.workers[0].terminated).toBe(false);
		(await loadSharedAuthRealm()).retire({ force: true });
		expect(shared.workers[0].terminated).toBe(true);
		expect(crashed).toHaveBeenCalledTimes(1);
		expect(shared.core.generation).toBeNull();
	});

	it('waits for a late registration and times out with a fixed code', async () => {
		const waiting = whenSharedRustCore();
		const shared = sharedCore(binding());
		cleanup = shared.unregister;
		await expect(waiting).resolves.toBe(shared.core);
		shared.unregister();
		cleanup = null;
		vi.useFakeTimers();
		const late = whenSharedRustCore({ timeoutMs: 10 });
		vi.advanceTimersByTime(20);
		await expect(late).rejects.toMatchObject({ code: 'shared_core_timeout' });
	});
});
