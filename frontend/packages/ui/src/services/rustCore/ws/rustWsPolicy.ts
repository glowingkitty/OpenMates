/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) WebSocket lifecycle decisions: the page
 * adapter over the shared Rust core Worker `ws` unit. Loaded only by the guarded
 * branches of websocketService.ts, so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_ws) decides: what a close event means
 * (1008 policy violation with 2FA/passkey hints, repeated or auth-worded 1006
 * closures that need a REST session check), the capped reconnect backoff, the
 * pong-timeout reaction, and the online/resume/periodic-retry reactions. The page
 * keeps IO only: the WebSocket object, timers, DOM events, stores and the REST
 * session refresh, all reached through `RustWsHost`. There is no TypeScript
 * fallback: a refused or failed unit call rejects.
 */
import { wsCall } from './wsUnitClient';
import type { WsLifecycleSource, WsReconnectPlan } from './wsProtocol';

/** The slice of WebSocketService state and effects the executors need. */
export interface RustWsHost {
	isAuthenticated(): boolean;
	isConnected(): boolean;
	hasConnectionPromise(): boolean;
	hasSocket(): boolean;
	consecutive: number;
	reconnectAttempts: number;
	msSinceActivity(): number;
	setStatus(status: 'reconnecting' | 'disconnected'): void;
	setError(message: string): void;
	dispatch(name: string, detail?: unknown): void;
	/** Rejects and clears the pending connection promise when it belongs to a closed, socket-less attempt. */
	rejectIfIdle(reason: string | Error): void;
	/** Drops a pending promise of a closed attempt without rejecting it. */
	clearIdlePromise(): void;
	clearConnectionPromise(): void;
	scheduleConnect(delayMs: number): void;
	connectNow(): void;
	closeSocket(code: number, reason: string): void;
	clearPongTimeout(): void;
	startPeriodicRetry(): void;
	stopPeriodicRetry(): void;
	refreshSession(reason: string): Promise<boolean>;
	sendLivenessPing(): void;
}

function applyReconnectPlan(host: RustWsHost, plan: WsReconnectPlan, code: number | null, exhaustedMessage: string): void {
	if (plan.kind === 'reconnect') {
		host.setStatus('reconnecting');
		host.reconnectAttempts = plan.attempt;
		if (code !== null) host.rejectIfIdle(new Error(`Connection closed (code ${code}), attempting reconnect.`));
		if (code !== null) host.clearIdlePromise();
		host.scheduleConnect(plan.delayMs);
	} else if (plan.kind === 'exhausted') {
		host.setError(exhaustedMessage);
		host.dispatch('connection_failed_reconnect');
		host.startPeriodicRetry();
		if (code !== null) host.rejectIfIdle('Max reconnect attempts reached');
	} else if (code !== null) {
		host.setStatus('disconnected');
		host.rejectIfIdle('User logged out during connection attempt.');
		host.clearConnectionPromise();
	}
}

/** Reacts to the close event of the active socket (the `onclose` policy). */
export async function handleClose(host: RustWsHost, event: { code: number; reason?: string; wasClean: boolean }): Promise<void> {
	const plan = await wsCall('closePlan', {
		code: event.code,
		reason: typeof event.reason === 'string' ? event.reason : undefined,
		wasClean: event.wasClean,
		consecutive: host.consecutive,
		authenticated: host.isAuthenticated(),
		reconnectAttempts: host.reconnectAttempts,
	});
	host.consecutive = plan.consecutive;
	if (plan.kind === 'policyViolation') {
		host.setError(event.reason || 'Connection closed due to policy violation.');
		if (plan.reAuth) host.dispatch('reAuthRequired', { type: plan.reAuth });
		else host.dispatch('authError');
		host.rejectIfIdle(`Connection closed: ${event.reason}`);
		return;
	}
	if (plan.kind === 'sessionCheck') {
		const sessionValid = await host.refreshSession(plan.authRelated ? 'auth-related close reason' : 'repeated abnormal closures');
		const result = await wsCall('sessionResult', { sessionValid, authenticated: host.isAuthenticated() });
		host.consecutive = result.consecutive;
		if (result.kind === 'authError') {
			host.setError('Authentication failed. Please log in again.');
			host.dispatch('authError', { reason: 'Session expired or invalid token' });
			host.rejectIfIdle('Authentication failed');
				return;
		}
		host.reconnectAttempts = 0;
		applyReconnectPlan(host, result, event.code, 'Max reconnect attempts reached. Will keep retrying.');
		return;
	}
	applyReconnectPlan(host, plan, event.code, 'Max reconnect attempts reached. Will keep retrying.');
}

/** Reacts to an unanswered ping (the pong-timeout callback). */
export async function handlePongTimeout(host: RustWsHost): Promise<void> {
	const plan = await wsCall('pongTimeout', {
		sinceActivityMs: Math.max(0, Math.floor(host.msSinceActivity())),
		hasSocket: host.hasSocket(),
		authenticated: host.isAuthenticated(),
		reconnectAttempts: host.reconnectAttempts,
	});
	if (plan.kind === 'skip') host.clearPongTimeout();
	else if (plan.kind === 'closeSocket') host.closeSocket(1000, 'Pong timeout - client initiated close');
	else if (plan.kind === 'reconnect') applyReconnectPlan(host, plan, null, '');
	else if (plan.kind === 'exhausted') applyReconnectPlan(host, plan, null, 'Max reconnect attempts reached after pong timeout. Will keep retrying.');
}

/** Reacts to an online / connection-type-change / page-resume signal. */
export async function handleLifecycle(host: RustWsHost, source: WsLifecycleSource): Promise<void> {
	const plan = await wsCall('lifecycle', {
		source,
		authenticated: host.isAuthenticated(),
		connected: host.isConnected(),
		connecting: host.hasConnectionPromise(),
	});
	if (plan.kind === 'connect') {
		host.reconnectAttempts = 0;
		host.connectNow();
	} else if (plan.kind === 'ping') {
		host.sendLivenessPing();
	}
}

/** Reacts to one tick of the 30 s periodic retry interval. */
export async function handlePeriodicRetry(host: RustWsHost): Promise<void> {
	const plan = await wsCall('periodicRetry', {
		authenticated: host.isAuthenticated(),
		connected: host.isConnected(),
		connecting: host.hasConnectionPromise(),
	});
	if (plan.kind === 'connect') {
		host.reconnectAttempts = 0;
		host.connectNow();
	} else if (plan.kind === 'stop') {
		host.stopPeriodicRetry();
	}
}
