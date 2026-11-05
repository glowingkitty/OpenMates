// contract-test-file: tooling
// Rust web auth adapter: closed protocol, Worker client/runtime request loop,
// fixed refusal codes and the page-side operations (session check, logout
// broadcast, peer frames). Synthetic binding only; the Rust policy itself is
// covered by packages/openmates-rust/src/web_auth_tests.rs.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAuthClient, RustAuthError, type AuthEndpoint, type AuthHttpExecutor } from '../authClient';
import { isAuthFromWorker, isAuthHttpRequest, type AuthHttpRequest } from '../authProtocol';
import { installAuthWorker, isRustWebAuthBinding, type RustWebAuthBinding } from '../authWorkerRuntime';
import {
	executeAuthRequest, installRustCrossTabLogout, rustAnnounceLogout, rustLogoutServer, rustPasswordLogin, rustRecoveryKeyLogin, rustSessionCheck, setRustAuthClientForTesting,
} from '../../authOperation';

type Listener = (event: MessageEvent<unknown>) => void;

function channel(binding: RustWebAuthBinding | null) {
	const page: Record<string, Listener[]> = {};
	const worker: Listener[] = [];
	let terminated = false;
	const deliver = (listeners: () => Listener[] | undefined, data: unknown) => {
		const cloned = structuredClone(data);
		setTimeout(() => listeners()?.forEach((listener) => listener({ data: cloned } as MessageEvent<unknown>)), 0);
	};
	const scope = {
		postMessage: (message: unknown) => deliver(() => page.message, message),
		addEventListener: (_type: 'message', listener: Listener) => { worker.push(listener); },
		close: () => { terminated = true; },
	};
	const endpoint: AuthEndpoint = {
		postMessage(message) { deliver(() => worker, message); },
		addEventListener(type, listener) { (page[type] ??= []).push(listener); },
		terminate() { terminated = true; },
	};
	if (binding) installAuthWorker(scope, binding);
	else scope.postMessage({ v: 1, ready: false });
	return { endpoint, get terminated() { return terminated; } };
}

const challenge = JSON.stringify({ method: 'POST', path: '/v1/auth/password-v2/challenge', headers: [['Content-Type', 'application/json']], body: '{"a":1}' });
const login = JSON.stringify({ method: 'POST', path: '/v1/auth/login', headers: [['Origin', '{page_origin}']], body: '{"b":2}' });

function syntheticBinding(options: { failReply?: boolean } = {}): RustWebAuthBinding & { freed: number } {
	const state = { freed: 0 };
	return Object.assign(state, {
		WebAuthPasswordLogin: {
			start(input: string, password: string, tfa?: string) {
				const parsed = JSON.parse(input) as { codeType: string | null };
				if (password === 'bad') throw 'password_login_input';
				const queue = [challenge, login];
				const seen: number[] = [];
				return {
					request: () => queue.shift(),
					reply(status: number) {
						if (options.failReply) throw new Error('secret detail must not leak');
						seen.push(status);
						return queue.length === 0;
					},
					finish: async () => ({ kind: 'unlocked', status: 200, data: JSON.stringify({ success: true, seen, tfa, type: parsed.codeType }), credentialVersion: 2 }),
					free: () => { state.freed++; },
				};
			},
		},
		WebAuthRecoveryLogin: {
			start(input: string, recoveryKey: string) {
				const parsed = JSON.parse(input) as { stayLoggedIn: boolean };
				let pending: string | undefined = login;
				return {
					request: () => { const next = pending; pending = undefined; return next; },
					finish: async (status: number, body?: string) => ({ kind: status === 200 ? 'unlocked' : 'response', status,
						data: JSON.stringify({ recoveryKey, stay: parsed.stayLoggedIn, body: JSON.parse(body ?? 'null') }), credentialVersion: 1 }),
					free: () => { state.freed++; },
				};
			},
		},
		web_auth_session_request: (signals: string, sessionId: string) =>
			JSON.stringify({ method: 'POST', path: '/v1/auth/session', headers: [], body: JSON.stringify({ deviceSignals: Object.fromEntries(JSON.parse(signals)), session_id: sessionId }) }),
		web_auth_classify_session: (status: number, body?: string) =>
			status === 503 ? JSON.stringify({ kind: 'unreachable', status }) : JSON.stringify({ kind: 'authenticated', data: JSON.parse(body ?? 'null') }),
		web_auth_missing_key_plan: () => '{}',
		web_auth_logout_server_step: (captured: number, current: number, skip: boolean) =>
			captured !== current ? '{"kind":"skip_newer_login"}' : skip ? '{"kind":"none"}'
				: JSON.stringify({ kind: 'request', request: { method: 'POST', path: '/v1/auth/logout', headers: [['Content-Type', 'application/json']], body: null }, broadcast: true }),
		web_auth_logout_may_delete_cookies: (captured: number, current: number) => captured === current,
		web_auth_logout_frame: (tab: string) => JSON.stringify({ v: 1, type: 'logout', tab }),
		web_auth_accept_logout_frame: (frame: string, own: string) => (JSON.parse(frame) as { tab: string }).tab !== own,
	});
}

afterEach(() => {
	setRustAuthClientForTesting(null);
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

describe('auth protocol', () => {
	it('accepts only auth-scoped POST requests and closed worker messages', () => {
		expect(isAuthHttpRequest(JSON.parse(challenge))).toBe(true);
		expect(isAuthHttpRequest({ method: 'POST', path: '/v1/chats', headers: [], body: null })).toBe(false);
		expect(isAuthHttpRequest({ method: 'GET', path: '/v1/auth/session', headers: [], body: null })).toBe(false);
		expect(isAuthHttpRequest({ method: 'POST', path: '/v1/auth/x', headers: [['a']], body: null })).toBe(false);
		expect(isAuthFromWorker({ v: 1, ready: true })).toBe(true);
		expect(isAuthFromWorker({ v: 1, id: 1, ok: false, code: 'x' })).toBe(true);
		expect(isAuthFromWorker({ v: 2, ready: true })).toBe(false);
		expect(isAuthFromWorker({ v: 1, id: 1, http: { method: 'POST', path: 'https://evil/v1/auth/', headers: [], body: null } })).toBe(false);
		expect(isRustWebAuthBinding(syntheticBinding())).toBe(true);
		expect(isRustWebAuthBinding({})).toBe(false);
	});
});

describe('auth worker client', () => {
	it('runs the password request loop through the page executor in order', async () => {
		const executed: AuthHttpRequest[] = [];
		const execute: AuthHttpExecutor = async (request) => { executed.push(request); return { status: 200, body: '{}' }; };
		const { endpoint } = channel(syntheticBinding());
		const client = createAuthClient(endpoint, execute);
		const result = await client.call<{ data: string }>({
			op: 'password_login', password: 'pw', tfa: '123456',
			input: { email: 'a@example.com', sessionId: 's', userEmailSalt: 'x', emailEncryptionKey: null, stayLoggedIn: false, codeType: 'otp' },
		});
		expect(executed.map((request) => request.path)).toEqual(['/v1/auth/password-v2/challenge', '/v1/auth/login']);
		expect(JSON.parse(result.data)).toEqual({ success: true, seen: [200, 200], tfa: '123456', type: 'otp' });
		client.close();
	});

	it('returns fixed refusal codes and frees the login on failure', async () => {
		const binding = syntheticBinding({ failReply: true });
		const client = createAuthClient(channel(binding).endpoint, async () => ({ status: 200, body: '{}' }));
		const input = { email: 'a@example.com', sessionId: 's', userEmailSalt: 'x', emailEncryptionKey: null, stayLoggedIn: false, codeType: null };
		await expect(client.call({ op: 'password_login', password: 'pw', tfa: null, input })).rejects.toMatchObject({ code: 'rust_auth_failed' });
		expect(binding.freed).toBe(1);
		await expect(client.call({ op: 'password_login', password: 'bad', tfa: null, input })).rejects.toMatchObject({ code: 'password_login_input' });
		client.close();
	});

	it('maps a failed page fetch to a network refusal', async () => {
		const client = createAuthClient(channel(syntheticBinding()).endpoint, async () => { throw new TypeError('offline'); });
		const input = { email: 'a@example.com', sessionId: 's', userEmailSalt: 'x', emailEncryptionKey: null, stayLoggedIn: true, codeType: null };
		await expect(client.call({ op: 'password_login', password: 'pw', tfa: null, input })).rejects.toMatchObject({ code: 'network' });
		client.close();
	});

	it('rejects every call when the worker cannot load Rust', async () => {
		const pair = channel(null);
		const client = createAuthClient(pair.endpoint, async () => ({ status: 200, body: null }));
		await expect(client.call({ op: 'logout_frame', tabId: 't' })).rejects.toBeInstanceOf(RustAuthError);
		expect(pair.terminated).toBe(true);
	});
});

describe('auth operations', () => {
	function installSynthetic() {
		const client = createAuthClient(channel(syntheticBinding()).endpoint, (request) => executeAuthRequest(request));
		setRustAuthClientForTesting(client, true);
		return client;
	}

	it('executes Rust requests with the page origin and credentials', async () => {
		const fetchMock = vi.fn(async () => new Response('{"success":true,"user":{"id":"u"}}', { status: 200 }));
		vi.stubGlobal('fetch', fetchMock);
		installSynthetic();
		const decision = await rustSessionCheck({ deviceSignals: { a: '1', b: null }, sessionId: 'sid', signal: new AbortController().signal });
		expect(decision).toEqual({ kind: 'authenticated', data: { success: true, user: { id: 'u' } } });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/v1/auth/session')).toBe(true);
		expect(init.credentials).toBe('include');
		expect(init.body).toBe('{"deviceSignals":{"a":"1","b":null},"session_id":"sid"}');

		const loginReply = await executeAuthRequest(JSON.parse(login) as AuthHttpRequest);
		expect(loginReply.status).toBe(200);
		const [, loginInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
		expect(loginInit.headers).toEqual({ Origin: window.location.origin });
	});

	it('reports an unreachable session check without a decision', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('busy', { status: 503 })));
		installSynthetic();
		await expect(rustSessionCheck({ deviceSignals: {}, sessionId: 's', signal: new AbortController().signal }))
			.resolves.toEqual({ kind: 'unreachable', status: 503 });
	});

	it('password login exposes ok/data and keeps the TS response shape', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
		installSynthetic();
		const outcome = await rustPasswordLogin({
			email: 'a@example.com', password: 'pw', sessionId: 's', userEmailSalt: 'x', emailEncryptionKey: null, stayLoggedIn: false,
			tfa: { code: '12345678', type: 'backup' },
		});
		expect(outcome).toMatchObject({ kind: 'unlocked', status: 200, ok: true, credentialVersion: 2, data: { tfa: '12345678', type: 'backup' } });
	});

	it('recovery-key login sends one request and returns the Rust unlock', async () => {
		const fetchMock = vi.fn(async () => new Response('{"success":true}', { status: 200 }));
		vi.stubGlobal('fetch', fetchMock);
		installSynthetic();
		const outcome = await rustRecoveryKeyLogin({
			email: 'a@example.com', recoveryKey: 'RK-1', sessionId: 's', userEmailSalt: 'x', emailEncryptionKey: null, stayLoggedIn: true,
		});
		expect(fetchMock).toHaveBeenCalledTimes(1);
		expect(outcome).toMatchObject({ kind: 'unlocked', ok: true, credentialVersion: 1, data: { recoveryKey: 'RK-1', stay: true, body: { success: true } } });
	});

	it('logout tells peer tabs first, then sends one request; skipped logouts do neither', async () => {
		const order: string[] = [];
		vi.stubGlobal('fetch', vi.fn(async () => { order.push('fetch'); return new Response(null, { status: 200 }); }));
		const posted: unknown[] = [];
		class FakeChannel {
			postMessage(frame: unknown) { order.push('broadcast'); posted.push(frame); }
			close() {}
			addEventListener() {}
		}
		vi.stubGlobal('BroadcastChannel', FakeChannel);
		installSynthetic();
		const signal = new AbortController().signal;
		const newer = { captured: 1, current: () => 2, skipServerLogout: false, policyViolation: false };
		await expect(rustAnnounceLogout(newer)).resolves.toBe(false);
		await expect(rustLogoutServer({ ...newer, signal })).resolves.toEqual({ kind: 'skip_newer_login' });
		const peerTriggered = { captured: 2, current: () => 2, skipServerLogout: true, policyViolation: false };
		await expect(rustAnnounceLogout(peerTriggered)).resolves.toBe(false);
		await expect(rustLogoutServer({ ...peerTriggered, signal })).resolves.toEqual({ kind: 'none' });
		expect(order).toEqual([]);
		const user = { captured: 3, current: () => 3, skipServerLogout: false, policyViolation: false };
		await expect(rustAnnounceLogout(user)).resolves.toBe(true);
		await expect(rustLogoutServer({ ...user, signal })).resolves.toEqual({ kind: 'sent', ok: true, status: 200 });
		expect(order).toEqual(['broadcast', 'fetch']);
		expect(JSON.parse(posted[0] as string)).toMatchObject({ v: 1, type: 'logout' });
	});

	it('peer frames run the local logout once; own and malformed frames do not', async () => {
		let listener: Listener | null = null;
		class FakeChannel {
			postMessage() {}
			close() {}
			addEventListener(_type: string, next: Listener) { listener = next; }
		}
		vi.stubGlobal('BroadcastChannel', FakeChannel);
		installSynthetic();
		const onPeerLogout = vi.fn();
		installRustCrossTabLogout(onPeerLogout);
		expect(listener).not.toBeNull();
		const emit = (data: unknown) => (listener as unknown as Listener)({ data } as MessageEvent<unknown>);
		emit(JSON.stringify({ v: 1, type: 'logout', tab: 'peer-tab' }));
		emit({ not: 'a string' });
		emit('x'.repeat(600));
		await vi.waitFor(() => expect(onPeerLogout).toHaveBeenCalledTimes(1));
	});
});
