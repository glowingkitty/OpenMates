// Parity vectors for the shared Rust web WebSocket lifecycle policy.
// The committed JSON (packages/openmates-rust/src/web_ws/ts_vectors.json) holds
// inputs plus the decisions of the existing TypeScript service (flag off). This
// test drives the real websocketService.ts with a fake WebSocket and fake timers
// and fails if its observable behaviour (scheduled reconnect delay, attempt and
// abnormal-closure counters, events, status, socket close, connect calls) drifts
// from the vectors; web_ws/tests.rs replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

// navigator.connection must exist before the service is constructed: it registers its
// network-type `change` listener once, at import time.
const mocks = vi.hoisted(() => {
	const connection = new EventTarget();
	Object.defineProperty(navigator, 'connection', { value: connection, configurable: true });
	return { sessionValid: true, connection };
});

// A store whose `set` does not notify subscribers: the service's own auth subscription
// (connect on login, disconnect on logout) must not interfere with the driven scenarios.
vi.mock('../../../stores/authState', () => {
	let value = { isAuthenticated: true, isInitialized: true };
	return { authStore: { subscribe: (run: (v: typeof value) => void) => { run(value); return () => undefined; }, set: (next: typeof value) => { value = next; } } };
});
vi.mock('../../../utils/cookies', () => ({ getWebSocketToken: () => 'vector-token' }));
vi.mock('../../../stores/authSessionActions', () => ({ checkAuth: async () => mocks.sessionValid }));

import { get } from 'svelte/store';
import { webSocketService } from '../../websocketService';
import { authStore } from '../../../stores/authState';
import { websocketStatus } from '../../../stores/websocketStatusStore';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_ws/ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

class FakeWebSocket {
	static OPEN = 1;
	static last: FakeWebSocket | null = null;
	readyState = 1;
	onopen: unknown = null;
	onmessage: unknown = null;
	onerror: unknown = null;
	onclose: ((event: { code: number; reason?: string; wasClean: boolean }) => Promise<void>) | null = null;
	closed: Array<[number, string]> = [];
	sent: string[] = [];
	constructor(public url: string) { FakeWebSocket.last = this; }
	send(data: string) { this.sent.push(data); }
	close(code: number, reason: string) { this.closed.push([code, reason]); }
}

type Internals = {
	ws: FakeWebSocket | null; reconnectAttempts: number; consecutiveAbnormalClosures: number; connectionPromise: Promise<void> | null;
	preparationPromise: Promise<void> | null; sessionRefreshPromise: Promise<boolean> | null; connectionGeneration: number; lastActivityTimestamp: number; periodicRetryIntervalId: unknown;
	connectAttempt(generation: number): Promise<void>; startPing(): void; stopPing(): void; startPeriodicRetry(): void;
	stopPeriodicRetry(): void; handlePageResume(source: string): void; connect(): Promise<void>; addEventListener: EventTarget['addEventListener'];
};
const svc = webSocketService as unknown as Internals;
const EVENTS = ['reAuthRequired', 'authError', 'connection_failed_reconnect'];

beforeAll(() => {
	// The import-time login connect opened a real (jsdom) socket: detach it so its late close is ignored.
	const stray = svc.ws as unknown as { onopen: unknown; onclose: unknown; onerror: unknown; onmessage: unknown; close(): void } | null;
	if (stray) {
		stray.onopen = stray.onclose = stray.onerror = stray.onmessage = null;
		stray.close();
	}
	svc.ws = null;
	svc.connectionPromise = null;
	svc.preparationPromise = null;
});

const warns: string[] = [];
let events: Array<[string, unknown]> = [];
let timeouts: number[] = [];
let connectCalls = 0;

function reset(authenticated: boolean, attempts: number, consecutive: number) {
	vi.clearAllTimers();
	svc.stopPing();
	svc.stopPeriodicRetry();
	svc.ws = null;
	svc.connectionPromise = null;
	svc.preparationPromise = null;
	// An unauthenticated refresh returns before its `finally` runs and would leave a stale promise behind.
	svc.sessionRefreshPromise = null;
	svc.reconnectAttempts = attempts;
	svc.consecutiveAbnormalClosures = consecutive;
	svc.lastActivityTimestamp = 0;
	websocketStatus.reset();
	authStore.set({ isAuthenticated: authenticated, isInitialized: true } as never);
	events = [];
	timeouts = [];
}

for (const name of EVENTS) svc.addEventListener(name, (event) => events.push([name, (event as CustomEvent).detail ?? null]));

beforeEach(() => {
	vi.useFakeTimers();
	vi.setSystemTime(1_700_000_000_000);
	vi.stubGlobal('WebSocket', FakeWebSocket);
	vi.spyOn(console, 'info').mockImplementation((...args: unknown[]) => { warns.push(args.map(String).join(' ').slice(0, 160)); });
	vi.spyOn(console, 'warn').mockImplementation((...args: unknown[]) => { warns.push(args.map(String).join(' ').slice(0, 160)); });
	vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => { warns.push(args.map(String).join(' ').slice(0, 160)); });
	vi.spyOn(console, 'debug').mockImplementation(() => undefined);
	vi.spyOn(console, 'log').mockImplementation(() => undefined);
	const realSetTimeout = globalThis.setTimeout;
	vi.spyOn(globalThis, 'setTimeout').mockImplementation(((fn: () => void, delay?: number, ...rest: unknown[]) => {
		timeouts.push(delay ?? 0);
		return realSetTimeout(fn, delay, ...rest);
	}) as typeof setTimeout);
	vi.spyOn(svc, 'connect').mockImplementation(async () => { connectCalls++; });
});
afterEach(() => {
	reset(true, 0, 0);
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	vi.useRealTimers();
});

async function flush() { for (let i = 0; i < 6; i++) await vi.advanceTimersByTimeAsync(0); }

/** A fresh socket whose close handlers were installed by the real connectAttempt. */
async function openSocket(authenticated: boolean, attempts: number, consecutive: number): Promise<FakeWebSocket> {
	reset(true, attempts, consecutive);
	FakeWebSocket.last = null;
	mocks.sessionValid = true;
	svc.connectAttempt(svc.connectionGeneration).catch(() => undefined);
	for (let i = 0; i < 20 && !FakeWebSocket.last; i++) await vi.advanceTimersByTimeAsync(0);
	const socket = FakeWebSocket.last!;
	authStore.set({ isAuthenticated: authenticated, isInitialized: true } as never);
	timeouts = [];
	events = [];
	return socket;
}

/** Observable effect of a reconnect-shaped decision on the service. */
function expectReconnectOutcome(out: Record<string, unknown>, label: string) {
	const state = get(websocketStatus);
	if (out.kind === 'reconnect') {
		expect(svc.reconnectAttempts, label).toBe(out.attempt);
		expect(timeouts, label).toEqual([out.delayMs]);
		expect(state.status, label).toBe('reconnecting');
	} else if (out.kind === 'exhausted') {
		expect(events.map(([name]) => name), label).toEqual(['connection_failed_reconnect']);
		expect(svc.periodicRetryIntervalId, label).not.toBeNull();
		expect(state.status, label).toBe('error');
	} else {
		expect(out.kind, label).toBe('loggedOut');
		expect(state.status, label).toBe('disconnected');
	}
	expect(svc.consecutiveAbnormalClosures, label).toBe(out.consecutive);
}

describe.skipIf(import.meta.env.VITE_OPENMATES_RUST_CORE === '1')('web WebSocket lifecycle parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('close events behave as the committed close and session vectors', async () => {
		for (const c of vectors.close) {
			const label = JSON.stringify(c.in);
			const sessionRuns: boolean[] = c.out.kind === 'sessionCheck' ? [true, false] : [true];
			for (const valid of sessionRuns) {
				const socket = await openSocket(c.in.authenticated, c.in.reconnectAttempts, c.in.consecutive);
				mocks.sessionValid = valid;
				warns.length = 0;
				await socket.onclose!({ code: c.in.code, reason: c.in.reason, wasClean: c.in.wasClean });
				await flush();
				const note = `${label} sessionValid=${valid} warns=${JSON.stringify(warns.slice(-6))}`;
				if (c.out.kind === 'policyViolation') {
					expect(events.map(([name, detail]) => (name === 'reAuthRequired' ? `${name}:${(detail as { type: string }).type}` : name)), note)
						.toEqual([c.out.reAuth ? `reAuthRequired:${c.out.reAuth}` : 'authError']);
					expect(svc.consecutiveAbnormalClosures, note).toBe(0);
					expect(timeouts, note).toEqual([]);
				} else if (c.out.kind === 'sessionCheck') {
					const session = vectors.session.find((s: { in: { sessionValid: boolean; authenticated: boolean } }) =>
						s.in.sessionValid === (valid && c.in.authenticated) && s.in.authenticated === c.in.authenticated).out;
					if (session.kind === 'authError') {
						expect(events.map(([name]) => name), note).toEqual(['authError']);
						expect(svc.consecutiveAbnormalClosures, note).toBe(0);
						expect(timeouts, note).toEqual([]);
					} else {
						expectReconnectOutcome(session, note);
					}
				} else {
					expectReconnectOutcome(c.out, note);
				}
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('reconnect backoff matches the committed vectors', async () => {
		for (const c of vectors.reconnect) {
			const socket = await openSocket(c.in.authenticated, c.in.reconnectAttempts, 0);
			await socket.onclose!({ code: 1001, reason: '', wasClean: true });
			await flush();
			expectReconnectOutcome({ ...c.out, consecutive: 0 }, JSON.stringify(c.in));
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('pong timeouts behave as the committed vectors', async () => {
		for (const c of vectors.pong) {
			const socket = await openSocket(true, c.in.reconnectAttempts, 0);
			svc.ws = socket;
			svc.startPing();
			await vi.advanceTimersByTimeAsync(25000);
			authStore.set({ isAuthenticated: c.in.authenticated, isInitialized: true } as never);
			if (!c.in.hasSocket) svc.ws = null;
			svc.lastActivityTimestamp = Date.now() + 10000 - c.in.sinceActivityMs;
			timeouts = [];
			socket.closed = [];
			await vi.advanceTimersByTimeAsync(10000);
			await flush();
			const label = JSON.stringify(c.in);
			if (c.out.kind === 'skip') {
				expect(socket.closed, label).toEqual([]);
				expect(timeouts, label).toEqual([]);
			} else if (c.out.kind === 'closeSocket') {
				expect(socket.closed, label).toEqual([[1000, 'Pong timeout - client initiated close']]);
			} else if (c.out.kind === 'none') {
				expect(socket.closed, label).toEqual([]);
				expect(timeouts, label).toEqual([]);
			} else {
				expectReconnectOutcome({ ...c.out, consecutive: 0 }, label);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('online, connection change, resume and periodic retry behave as the committed vectors', async () => {
		for (const c of vectors.lifecycle) {
			reset(c.in.authenticated, 4, 0);
			connectCalls = 0;
			svc.ws = c.in.connected ? ({ readyState: 1, send: vi.fn() } as unknown as FakeWebSocket) : null;
			svc.connectionPromise = c.in.connecting ? new Promise<void>(() => undefined) : null;
			const ping = vi.spyOn(webSocketService, 'sendMessage').mockResolvedValue(undefined);
			if (c.in.source === 'online') window.dispatchEvent(new Event('online'));
			else if (c.in.source === 'connectionChange') mocks.connection.dispatchEvent(new Event('change'));
			else svc.handlePageResume('vector');
			await flush();
			const label = JSON.stringify(c.in);
			expect(connectCalls, label).toBe(c.out.kind === 'connect' ? 1 : 0);
			expect(ping.mock.calls.length, label).toBe(c.out.kind === 'ping' ? 1 : 0);
			if (c.out.kind === 'connect') expect(svc.reconnectAttempts, label).toBe(0);
			ping.mockRestore();
		}
		for (const c of vectors.periodic) {
			reset(true, 4, 0);
			connectCalls = 0;
			svc.ws = c.in.connected ? ({ readyState: 1, send: vi.fn() } as unknown as FakeWebSocket) : null;
			svc.connectionPromise = c.in.connecting ? new Promise<void>(() => undefined) : null;
			svc.startPeriodicRetry();
			authStore.set({ isAuthenticated: c.in.authenticated, isInitialized: true } as never);
			await vi.advanceTimersByTimeAsync(30000);
			await flush();
			const label = JSON.stringify(c.in);
			expect(connectCalls, label).toBe(c.out.kind === 'connect' ? 1 : 0);
			expect(svc.periodicRetryIntervalId === null, label).toBe(c.out.kind === 'stop');
		}
	});
});
