/**
 * Web login, session restore and logout through the shared Rust core.
 *
 * Default builds keep the existing TypeScript auth path (the flag folds to false
 * and the Worker is never bundled). VITE_OPENMATES_RUST_CORE builds run the
 * account logic in Rust (`openmates_sdk::web_auth` in a Worker); this module is
 * the thin browser adapter: it executes the exact requests Rust describes with
 * the page's credentialed Fetch (same URL, headers, body and cookies as the TS
 * path), and carries cross-tab frames over BroadcastChannel. Forms, stores,
 * IndexedDB/CryptoKey persistence and navigator.credentials stay in TS.
 *
 * Flag-on builds accept `localStorage.openmates_rust_auth = "ts"` to select the
 * TypeScript path in the same build, so E2E can compare both against one stack.
 */
import { getApiEndpoint } from '../../config/api';
import type { RustAuthClient } from './auth/authClient';
import { authFlowActive, primeSignupPath, RUST_AUTH_SELECT_KEY as SELECT_KEY } from './auth/flowPush';
import { PAGE_ORIGIN_PLACEHOLDER, type AuthHttpReply, type AuthHttpRequest, type PasswordLoginResult } from './auth/authProtocol';

export const RUST_AUTH_SELECT_KEY = SELECT_KEY;
const LOGOUT_CHANNEL = 'openmates-auth-v1';

let testClient: RustAuthClient | null = null;
let testEnabled: boolean | null = null;
let client: Promise<RustAuthClient> | null = null;

/** True when this page runs auth through the Rust core. */
export function rustAuthEnabled(): boolean {
	if (testEnabled !== null) return testEnabled;
	return authFlowActive();
}

/** Test seam: inject a synthetic client and force the routing decision. */
export function setRustAuthClientForTesting(next: RustAuthClient | null, forceEnabled: boolean | null = null): void {
	testClient = next;
	testEnabled = forceEnabled;
	client = null;
	sharedLogoutChannel?.close();
	sharedLogoutChannel = null;
}

/** Executes one Rust-described request exactly like the deployed TS fetch calls. */
export async function executeAuthRequest(request: AuthHttpRequest, signal?: AbortSignal): Promise<AuthHttpReply> {
	const headers: Record<string, string> = {};
	for (const [name, value] of request.headers) headers[name] = value === PAGE_ORIGIN_PLACEHOLDER ? window.location.origin : value;
	const init: RequestInit = { method: request.method, headers, credentials: 'include' };
	if (request.body !== null) init.body = request.body;
	if (signal) init.signal = signal;
	const response = await fetch(getApiEndpoint(request.path), init);
	return { status: response.status, body: await response.text() };
}

let users = 0;
let idleTimer: ReturnType<typeof setTimeout> | null = null;
/**
 * Idle time before an unused Worker is closed. Chrome writes the compiled WASM
 * to its code cache only after the module has been alive for ~2 s; a Worker
 * closed sooner makes every page load recompile the module from scratch.
 */
const WORKER_IDLE_MS = 4000;
/** Flag builds: a login derived keys in the shared realm since it was last retired. */
let keysDerived = false;
/** Flag builds: longest wait for other auth calls before a retirement proceeds. */
const DRAIN_LIMIT_MS = 5000;
/** Flag builds: resolved whenever an auth operation ends (see `retireWhenDrained`). */
let drainWaiters: (() => void)[] = [];

/**
 * Flag builds: terminate the shared Rust core Worker and respawn it unbound, so
 * key material a login derived in its WASM memory does not outlive the login
 * (`force`: also while a principal is bound, i.e. on logout). Waits until at
 * most `own` auth operations (the caller's) are running, at most
 * DRAIN_LIMIT_MS, then terminates synchronously, so other auth calls are not
 * cut off by the retirement and a hung call cannot keep the realm alive.
 */
async function retireWhenDrained(force: boolean, own: number): Promise<void> {
	if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1') {
		const { loadSharedAuthRealm } = await import('./auth/authWorkerPort');
		const realm = await loadSharedAuthRealm();
		const deadline = Date.now() + DRAIN_LIMIT_MS;
		while (users > own && Date.now() < deadline) {
			await new Promise<void>((resolve) => {
				const timer = setTimeout(resolve, deadline - Date.now());
				drainWaiters.push(() => { clearTimeout(timer); resolve(); });
			});
		}
		keysDerived = false;
		realm.retire({ force });
	}
}

/** Each operation holds the Worker; the last one to finish releases it. */
function core(): Promise<RustAuthClient> {
	users++;
	if (idleTimer !== null) { clearTimeout(idleTimer); idleTimer = null; }
	if (testClient) return Promise.resolve(testClient);
	if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1') {
		if (!client) {
			// A closed client (idle close, protocol failure, shared Worker crash or
			// retirement) is dropped, so the next operation opens a fresh unit port.
			const opening: Promise<RustAuthClient> = import('./auth/authWorkerPort').then(({ createSharedAuthClient }) =>
				createSharedAuthClient((request) => executeAuthRequest(request), () => { if (client === opening) client = null; }));
			opening.catch(() => { if (client === opening) client = null; });
			client = opening;
		}
		return client;
	}
	return Promise.reject(new Error('rust_core_not_enabled'));
}

/** Release the Worker (and its WASM memory, e.g. the 64 MiB Argon2 arena) once idle. */
function retire(): void {
	users = Math.max(0, users - 1);
	if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && drainWaiters.length > 0) {
		const waiting = drainWaiters;
		drainWaiters = [];
		for (const resolve of waiting) resolve();
	}
	if (users > 0 || testClient || !client || idleTimer !== null) return;
	idleTimer = setTimeout(() => {
		idleTimer = null;
		if (users > 0 || !client) return;
		const closing = client;
		client = null;
		void closing.then((active) => active.close(), () => undefined);
		if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && keysDerived) {
			void retireWhenDrained(false, 0).catch((error: unknown) => console.warn('[RustAuth] shared core retirement failed:', error instanceof Error ? error.message : 'unknown'));
		}
	}, WORKER_IDLE_MS);
}

/** Start the Worker early so the first auth call does not pay WASM start-up. */
export function prewarmRustAuth(): void {
	if (!rustAuthEnabled()) return;
	// A #signup/... deep link is routed with synchronous reads later; have Rust answer for it now.
	if (window.location.hash.startsWith('#signup/')) void primeSignupPath(window.location.hash.substring(1));
	void core().catch(() => undefined);
	retire(); // Warm-up does not hold the Worker: it closes after the idle time unless an operation starts.
}

// ------------------------------------------------------------------ login ---

export interface RustPasswordLoginInput {
	email: string;
	password: string;
	sessionId: string;
	userEmailSalt: string;
	emailEncryptionKey: string | null;
	stayLoggedIn: boolean;
	tfa: { code: string; type: 'otp' | 'backup' } | null;
}
export interface RustPasswordLoginOutcome {
	kind: PasswordLoginResult['kind'];
	status: number;
	ok: boolean;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any -- login responses contain method-specific user fields, as in passwordV2.ts.
	data: Record<string, any>;
	key: CryptoKey | null;
	credentialVersion: number | null;
	code: string | null;
}

function toOutcome(result: PasswordLoginResult): RustPasswordLoginOutcome {
	return {
		kind: result.kind, status: result.status, ok: result.status >= 200 && result.status < 300,
		data: JSON.parse(result.data) ?? {}, key: result.key ?? null,
		credentialVersion: result.credentialVersion ?? null, code: result.code ?? null,
	};
}

/**
 * Flag builds: a login derived keys in the shared realm. It is retired once auth
 * is idle unless the page bound a principal meanwhile (the realm then belongs
 * to that session and is terminated on logout or account switch). Retiring it
 * right after a successful login would cut off the crypto and core units the
 * page starts for the new session and recompile the WASM on the hot path.
 */
function afterKeyDerivingLogin(): void {
	if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1') keysDerived = true;
}

/** Password (+ optional OTP/backup code) step: challenge, proof, v2/v1 login and key unwrap in Rust. */
export async function rustPasswordLogin(input: RustPasswordLoginInput): Promise<RustPasswordLoginOutcome> {
	try {
		const result = await (await core()).call<PasswordLoginResult>({
			op: 'password_login',
			input: { email: input.email, sessionId: input.sessionId, userEmailSalt: input.userEmailSalt,
				emailEncryptionKey: input.emailEncryptionKey, stayLoggedIn: input.stayLoggedIn, codeType: input.tfa?.type ?? null },
			password: input.password,
			tfa: input.tfa?.code ?? null,
		});
		if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && !testClient) afterKeyDerivingLogin();
		return toOutcome(result);
	} finally {
		retire();
	}
}

export interface RustRecoveryLoginInput {
	email: string;
	recoveryKey: string;
	sessionId: string;
	userEmailSalt: string;
	emailEncryptionKey: string | null;
	stayLoggedIn: boolean;
}
/** Recovery-key login: lookup hash, the login request and the PBKDF2 unwrap in Rust. */
export async function rustRecoveryKeyLogin(input: RustRecoveryLoginInput): Promise<RustPasswordLoginOutcome> {
	try {
		const result = await (await core()).call<PasswordLoginResult>({
			op: 'recovery_login',
			input: { email: input.email, sessionId: input.sessionId, userEmailSalt: input.userEmailSalt,
				emailEncryptionKey: input.emailEncryptionKey, stayLoggedIn: input.stayLoggedIn },
			recoveryKey: input.recoveryKey,
		});
		if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && !testClient) afterKeyDerivingLogin();
		return toOutcome(result);
	} finally {
		retire();
	}
}

// ---------------------------------------------------------------- session ---

export type RustSessionDecision =
	| { kind: 'unreachable'; status: number }
	// eslint-disable-next-line @typescript-eslint/no-explicit-any -- the session payload is the existing SessionCheckResult shape.
	| { kind: 'expired' | 'authenticated' | 'unauthenticated'; data: Record<string, any> }
	| { kind: 'device_verification'; verification: '2fa' | 'passkey'; reason: string; password_fallback_available: boolean;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any -- as above.
		password_credential_version: number | null; data: Record<string, any> };

/** `POST /v1/auth/session` built and classified by Rust, executed by the page. */
export async function rustSessionCheck(input: {
	deviceSignals: Record<string, string | null>; sessionId: string; signal: AbortSignal;
}): Promise<RustSessionDecision> {
	try {
		const auth = await core();
		const request = await auth.call<AuthHttpRequest>({ op: 'session_request', signals: JSON.stringify(Object.entries(input.deviceSignals)), sessionId: input.sessionId });
		const reply = await executeAuthRequest(request, input.signal);
		return await auth.call<RustSessionDecision>({ op: 'classify_session', status: reply.status, body: reply.body });
	} finally {
		retire();
	}
}

export interface RustMissingKeyContext {
	alreadyForced: boolean; sharedChatSession: boolean; pairLoginPending: boolean;
	ogImageMode: boolean; hadLocalSession: boolean; storageEvicted: boolean;
}
export interface RustMissingKeyPlan {
	setForced: boolean; clearActiveChat: boolean; notify: 'storage_evicted' | 'session_ended' | null;
	destructiveLogout: boolean; deleteCookies: boolean;
}
/** Forced-logout policy for an authenticated session without a local master key. */
export async function rustMissingKeyPlan(context: RustMissingKeyContext): Promise<RustMissingKeyPlan> {
	try {
		return await (await core()).call<RustMissingKeyPlan>({ op: 'missing_key_plan', context: JSON.stringify(context) });
	} finally {
		retire();
	}
}

// ----------------------------------------------------------------- logout ---

const tabId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : '';

type LogoutServerStep = { kind: 'skip_newer_login' } | { kind: 'none' } | { kind: 'request'; request: AuthHttpRequest; broadcast: boolean };
export type RustLogoutServerResult = { kind: 'skip_newer_login' | 'none' } | { kind: 'sent'; ok: boolean; status: number };

type LogoutInput = { captured: number; current: () => number; skipServerLogout: boolean; policyViolation: boolean };

async function logoutStep(auth: RustAuthClient, input: LogoutInput): Promise<LogoutServerStep> {
	return auth.call<LogoutServerStep>({ op: 'logout_server_step', captured: input.captured, current: input.current(),
		skipServerLogout: input.skipServerLogout, policyViolation: input.policyViolation });
}

/**
 * Tells peer tabs to drop their local session as soon as this tab's local
 * logout ran (Rust decides whether this logout revokes the shared session).
 * Peers then close their databases, so this tab's IndexedDB deletion, which
 * precedes the server request, is not blocked by their open connections.
 */
export async function rustAnnounceLogout(input: LogoutInput): Promise<boolean> {
	if (!tabId || typeof BroadcastChannel === 'undefined') return false;
	try {
		const auth = await core();
		const step = await logoutStep(auth, input);
		if (step.kind !== 'request' || !step.broadcast) return false;
		logoutChannel().postMessage(await auth.call<string>({ op: 'logout_frame', tabId }));
		return true;
	} finally {
		retire();
	}
}

/** Server half of logout: Rust decides (generation guard, plain/policy request); the page sends it. */
export async function rustLogoutServer(input: LogoutInput & { signal: AbortSignal }): Promise<RustLogoutServerResult> {
	try {
		const step = await logoutStep(await core(), input);
		if (step.kind !== 'request') return step;
		const reply = await executeAuthRequest(step.request, input.signal);
		return { kind: 'sent', ok: reply.status >= 200 && reply.status < 300, status: reply.status };
	} finally {
		retire();
		// Flag builds: logout ends the account's shared realm (no newer login started meanwhile).
		if (import.meta.env.VITE_OPENMATES_RUST_CORE === '1' && !testClient && input.current() === input.captured) {
			await retireWhenDrained(true, Number.POSITIVE_INFINITY);
		}
	}
}

export async function rustLogoutMayDeleteCookies(captured: number, current: number): Promise<boolean> {
	try {
		return await (await core()).call<boolean>({ op: 'logout_may_delete_cookies', captured, current });
	} finally {
		retire();
	}
}

// One long-lived channel per tab: posting and closing a fresh channel at once
// can drop the frame before it leaves this tab.
let sharedLogoutChannel: BroadcastChannel | null = null;
function logoutChannel(): BroadcastChannel {
	sharedLogoutChannel ??= new BroadcastChannel(LOGOUT_CHANNEL);
	return sharedLogoutChannel;
}

let crossTabInstalled = false;
/** Peer-tab logout: a Rust-accepted frame runs the local logout without a second server request. */
export function installRustCrossTabLogout(onPeerLogout: () => void): void {
	if (crossTabInstalled || !rustAuthEnabled() || typeof BroadcastChannel === 'undefined' || !tabId) return;
	crossTabInstalled = true;
	logoutChannel().addEventListener('message', (event: MessageEvent<unknown>) => {
		if (typeof event.data !== 'string' || event.data.length > 512) return;
		const frame = event.data;
		void core()
			.then((auth) => auth.call<boolean>({ op: 'accept_logout_frame', frame, ownTabId: tabId }))
			.then((accepted) => { if (accepted) onPeerLogout(); })
			.catch((error: unknown) => console.warn('[RustAuth] peer logout frame refused:', error instanceof Error ? error.message : 'unknown'))
			.finally(retire);
	});
}

// ------------------------------------------------------------- flow policy ---

/**
 * Signup step routing, pair-session policy and the recovery-key print page,
 * evaluated by shared Rust (`web_auth_flow`) on the shared Worker. Flag builds
 * only: callers branch on `rustAuthEnabled()` and never fall back to TS here.
 */
export async function rustAuthFlow<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
	try {
		return await (await core()).call<T>({ op: 'flow', name, args: JSON.stringify(args) });
	} finally {
		retire();
	}
}
