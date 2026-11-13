// `ws` unit of the shared Rust core Worker: the real router and installer over a
// binding that answers the committed outcomes (web_ws/ts_vectors.json; the Rust
// decisions themselves are proven by web_ws/tests.rs), and the page
// executors (rustWsPolicy.ts) applying those decisions to a recording host, with
// no TypeScript fallback.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installWsUnit } from '../ws/wsUnit';
import { rustWsStats } from '../ws/wsUnitClient';
import type { WsBinding } from '../ws/wsProtocol';
import * as rust from '../ws/rustWsPolicy';

const vectors = JSON.parse(readFileSync(resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_ws/ts_vectors.json'), 'utf8'));
const canon = (value: unknown): string => JSON.stringify(value, (_k, v) => (v && typeof v === 'object' && !Array.isArray(v)
	? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1))) : v));

function answer(section: string, input: string): string {
	const wanted = canon(JSON.parse(input));
	const found = vectors[section].find((c: { in: unknown }) => canon(c.in) === wanted);
	if (!found) throw new Error('protocol');
	return JSON.stringify(found.out);
}
const binding: WsBinding = {
	ws_close_plan: (input) => answer('close', input),
	ws_session_result: (input) => answer('session', input),
	ws_reconnect_plan: (input) => answer('reconnect', input),
	ws_pong_timeout: (input) => answer('pong', input),
	ws_lifecycle: (input) => answer('lifecycle', input),
	ws_periodic_retry: (input) => answer('periodic', input),
};

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { ws: installWsUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {},
	};
	return endpoint;
}

type Close = { code: number; reason?: string; wasClean: boolean };
function recordingHost(state: { authenticated: boolean; connected: boolean; connecting: boolean; hasSocket: boolean; attempts: number; consecutive: number; sessionValid: boolean; idleMs: number }) {
	const effects: unknown[][] = [];
	const host: rust.RustWsHost = {
		isAuthenticated: () => state.authenticated,
		isConnected: () => state.connected,
		hasConnectionPromise: () => state.connecting,
		hasSocket: () => state.hasSocket,
		get consecutive() { return state.consecutive; },
		set consecutive(value: number) { state.consecutive = value; },
		get reconnectAttempts() { return state.attempts; },
		set reconnectAttempts(value: number) { state.attempts = value; },
		msSinceActivity: () => state.idleMs,
		setStatus: (status) => effects.push(['status', status]),
		setError: (message) => effects.push(['error', message]),
		dispatch: (name, detail) => effects.push(['event', name, detail ?? null]),
		rejectIfIdle: (reason) => effects.push(['reject', reason instanceof Error ? reason.message : reason]),
		clearIdlePromise: () => effects.push(['clearIdle']),
		clearConnectionPromise: () => effects.push(['clearPromise']),
		scheduleConnect: (delay) => effects.push(['schedule', delay]),
		connectNow: () => effects.push(['connect']),
		closeSocket: (code, reason) => effects.push(['close', code, reason]),
		clearPongTimeout: () => effects.push(['clearPong']),
		startPeriodicRetry: () => effects.push(['periodic', 'start']),
		stopPeriodicRetry: () => effects.push(['periodic', 'stop']),
		refreshSession: async () => state.sessionValid,
		sendLivenessPing: () => effects.push(['ping']),
	};
	return { host, effects };
}
const baseState = (over: Partial<Parameters<typeof recordingHost>[0]> = {}) =>
	({ authenticated: true, connected: false, connecting: false, hasSocket: false, attempts: 0, consecutive: 0, sessionValid: true, idleMs: 0, ...over });

let unregister: (() => void) | null = null;
beforeEach(() => { unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker)); });
afterEach(() => { unregister?.(); });

describe('shared ws unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a binding without the ws exports', () => {
		const channel = new MessageChannel();
		expect(() => installWsUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('applies every close vector to the host as the TypeScript onclose does', async () => {
		for (const c of vectors.close.filter((v: { out: { kind: string } }) => v.out.kind !== 'sessionCheck')) {
			const state = baseState({ authenticated: c.in.authenticated, attempts: c.in.reconnectAttempts, consecutive: c.in.consecutive });
			const { host, effects } = recordingHost(state);
			await rust.handleClose(host, { code: c.in.code, reason: c.in.reason, wasClean: c.in.wasClean } as Close);
			const label = JSON.stringify(c.in);
			expect(state.consecutive, label).toBe(c.out.consecutive);
			if (c.out.kind === 'policyViolation') {
				expect(effects[0], label).toEqual(['error', c.in.reason || 'Connection closed due to policy violation.']);
				expect(effects[1], label).toEqual(c.out.reAuth ? ['event', 'reAuthRequired', { type: c.out.reAuth }] : ['event', 'authError', null]);
			} else if (c.out.kind === 'reconnect') {
				expect(state.attempts, label).toBe(c.out.attempt);
				expect(effects[effects.length - 1], label).toEqual(['schedule', c.out.delayMs]);
			} else if (c.out.kind === 'exhausted') {
				expect(effects, label).toContainEqual(['periodic', 'start']);
			} else {
				expect(effects[0], label).toEqual(['status', 'disconnected']);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('checks the REST session on repeated 1006 closures and ends in an auth error or a fresh reconnect', async () => {
		const close: Close = { code: 1006, reason: 'network down', wasClean: false };
		const invalid = recordingHost(baseState({ consecutive: 3, sessionValid: false }));
		await rust.handleClose(invalid.host, close);
		expect(invalid.effects).toContainEqual(['event', 'authError', { reason: 'Session expired or invalid token' }]);
		const valid = recordingHost(baseState({ consecutive: 3, attempts: 3, sessionValid: true }));
		await rust.handleClose(valid.host, close);
		expect(valid.effects[valid.effects.length - 1]).toEqual(['schedule', 1000]);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('applies pong, lifecycle and periodic vectors', async () => {
		for (const c of vectors.pong) {
			const { host, effects } = recordingHost(baseState({ authenticated: c.in.authenticated, hasSocket: c.in.hasSocket, attempts: c.in.reconnectAttempts, idleMs: c.in.sinceActivityMs }));
			await rust.handlePongTimeout(host);
			const label = JSON.stringify(c.in);
			if (c.out.kind === 'skip') expect(effects, label).toEqual([['clearPong']]);
			else if (c.out.kind === 'closeSocket') expect(effects, label).toEqual([['close', 1000, 'Pong timeout - client initiated close']]);
			else if (c.out.kind === 'none') expect(effects, label).toEqual([]);
			else if (c.out.kind === 'reconnect') expect(effects[effects.length - 1], label).toEqual(['schedule', c.out.delayMs]);
			else expect(effects, label).toContainEqual(['periodic', 'start']);
		}
		for (const c of vectors.lifecycle) {
			const { host, effects } = recordingHost(baseState({ authenticated: c.in.authenticated, connected: c.in.connected, connecting: c.in.connecting, attempts: 5 }));
			await rust.handleLifecycle(host, c.in.source);
			expect(effects, JSON.stringify(c.in)).toEqual(c.out.kind === 'connect' ? [['connect']] : c.out.kind === 'ping' ? [['ping']] : []);
		}
		for (const c of vectors.periodic) {
			const { host, effects } = recordingHost(baseState({ authenticated: c.in.authenticated, connected: c.in.connected, connecting: c.in.connecting }));
			await rust.handlePeriodicRetry(host);
			expect(effects, JSON.stringify(c.in)).toEqual(c.out.kind === 'connect' ? [['connect']] : c.out.kind === 'stop' ? [['periodic', 'stop']] : []);
		}
		expect(rustWsStats.ops.closePlan).toBeGreaterThan(0);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('rejects with the fixed protocol code instead of falling back to TypeScript', async () => {
		const before = rustWsStats.failures;
		const { host } = recordingHost(baseState({ attempts: 99 }));
		await expect(rust.handlePongTimeout(host)).rejects.toMatchObject({ code: 'protocol' });
		expect(rustWsStats.failures).toBe(before + 1);
	});
});
