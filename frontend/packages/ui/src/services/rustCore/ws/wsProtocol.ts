/**
 * `ws` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Every operation is a pure decision of the shared Rust web WebSocket lifecycle
 * policy (packages/openmates-rust/src/web_ws): close-code handling incl. 1008 and
 * repeated-1006 auth detection, reconnect backoff, pong timeout, online/resume
 * liveness and periodic retry. The page keeps the WebSocket object, timers, DOM
 * events, stores and the REST session refresh.
 */
import type { UnitProtocol } from '../host/unitPort';

export type WsReconnectPlan =
	| { kind: 'reconnect'; attempt: number; delayMs: number }
	| { kind: 'exhausted' }
	| { kind: 'loggedOut' };

export type WsClosePlan = (
	| { kind: 'policyViolation'; reAuth: '2fa' | 'passkey' | null }
	| { kind: 'sessionCheck'; authRelated: boolean }
	| WsReconnectPlan
) & { consecutive: number };

export type WsSessionResult = ({ kind: 'authError' } | WsReconnectPlan) & { consecutive: number };
export type WsPongPlan = { kind: 'skip' } | { kind: 'closeSocket' } | { kind: 'none' } | Exclude<WsReconnectPlan, { kind: 'loggedOut' }>;
export type WsLifecycleSource = 'online' | 'connectionChange' | 'resume';

export interface WsUnitProtocol extends UnitProtocol {
	closePlan: {
		request: { code: number; reason?: string; wasClean: boolean; consecutive: number; authenticated: boolean; reconnectAttempts: number };
		response: WsClosePlan;
	};
	sessionResult: { request: { sessionValid: boolean; authenticated: boolean }; response: WsSessionResult };
	reconnectPlan: { request: { authenticated: boolean; reconnectAttempts: number }; response: WsReconnectPlan };
	pongTimeout: {
		request: { sinceActivityMs: number; hasSocket: boolean; authenticated: boolean; reconnectAttempts: number };
		response: WsPongPlan;
	};
	lifecycle: {
		request: { source: WsLifecycleSource; authenticated: boolean; connected: boolean; connecting: boolean };
		response: { kind: 'connect' | 'ping' | 'none' };
	};
	periodicRetry: {
		request: { authenticated: boolean; connected: boolean; connecting: boolean };
		response: { kind: 'connect' | 'stop' | 'wait' };
	};
}

/** Worker module exports (JSON text in, JSON text out) of browser_ws.rs. */
export interface WsBinding {
	ws_close_plan(input: string): string;
	ws_session_result(input: string): string;
	ws_reconnect_plan(input: string): string;
	ws_pong_timeout(input: string): string;
	ws_lifecycle(input: string): string;
	ws_periodic_retry(input: string): string;
}

/** Operation to binding export. */
export const WS_OPS: Readonly<Record<keyof WsUnitProtocol & string, keyof WsBinding>> = Object.freeze({
	closePlan: 'ws_close_plan',
	sessionResult: 'ws_session_result',
	reconnectPlan: 'ws_reconnect_plan',
	pongTimeout: 'ws_pong_timeout',
	lifecycle: 'ws_lifecycle',
	periodicRetry: 'ws_periodic_retry',
});

export function isWsBinding(value: unknown): value is WsBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return Object.values(WS_OPS).every((name) => typeof binding[name] === 'function');
}
