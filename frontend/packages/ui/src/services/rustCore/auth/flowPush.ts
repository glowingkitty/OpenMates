/**
 * Push adapters for the shared Rust signup / pair / 2FA-app policy
 * (spec: specifications/features/auth#auth.signup.current-flow and
 * #auth.pair-login.lifecycle). Several TypeScript callers are synchronous
 * (store reads, path helpers, config constants), but the Rust core runs in the
 * shared Worker. Decision: the Worker computes, and the answer is pushed into
 * a page-side cache or store when it arrives; a synchronous read returns the
 * last pushed value, or a neutral default (no restriction, not expired, not a
 * signup path, no 2FA apps) before the first answer. Async callers can await
 * `primeSignupPath` to make the next synchronous read exact.
 *
 * Flag builds only: callers guard with `import.meta.env.VITE_OPENMATES_RUST_CORE`
 * and `authFlowActive()`. A failed Worker call keeps the last pushed value and
 * logs; there is no TypeScript recomputation.
 */
import type { PairSessionData, PairSessionState } from '../../../stores/pairSessionStore';

const RUST_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';
/** localStorage key that selects the TypeScript path inside a flag build (E2E comparison). */
export const RUST_AUTH_SELECT_KEY = 'openmates_rust_auth';
const CACHE_LIMIT = 64;

/** True when this page runs the auth policy through the Rust core. */
export function authFlowActive(): boolean {
	if (!RUST_BUILD || typeof window === 'undefined') return false;
	return window.localStorage?.getItem(RUST_AUTH_SELECT_KEY) !== 'ts';
}

let operations: Promise<typeof import('../authOperation')> | null = null;

async function flow<T>(name: string, args: Record<string, unknown>): Promise<T> {
	// One shared import: concurrent pushes (step and verdict of one path) must not each start their own.
	operations ??= import('../authOperation');
	const { rustAuthFlow } = await operations;
	return rustAuthFlow<T>(name, args);
}

function warn(name: string, error: unknown): void {
	console.warn(`[RustAuthFlow] ${name} failed:`, error instanceof Error ? error.message : String(error));
}

/** Bounded insertion-ordered cache; the oldest entry leaves first. */
function remember<T>(cache: Map<string, T>, key: string, value: T): void {
	cache.delete(key);
	cache.set(key, value);
	if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value as string);
}

// ------------------------------------------------------------------- pair ---

let pairSeq = 0;

/** Neutral pair view: an unrestricted session. */
export const NEUTRAL_PAIR_STATE: PairSessionState = {
	isPairSession: false, authorizerDeviceName: null, autoLogoutAt: null, autoLogoutWarning: false, remainingSeconds: null,
};

/** Restricted view used until Rust answers for a stored or just-activated pair session (fail closed). */
export const FAIL_CLOSED_PAIR_STATE: PairSessionState = {
	isPairSession: true, authorizerDeviceName: null, autoLogoutAt: null, autoLogoutWarning: false, remainingSeconds: null,
};

/** Computes the restricted-session view in Rust and pushes it; stale answers are dropped. */
export function pushPairView(data: PairSessionData | null, nowMs: number, set: (value: PairSessionState) => void): void {
	const seq = ++pairSeq;
	flow<PairSessionState>('pair_view', { data, nowMs })
		.then((view) => { if (seq === pairSeq) set(view); })
		.catch((error: unknown) => warn('pair_view', error));
}

/** Builds the stored record for a completed pairing in Rust. */
export function pairActivate(input: Record<string, unknown>, nowMs: number): Promise<PairSessionData> {
	return flow<PairSessionData>('pair_activate', { input, nowMs });
}

/** Rust decision for the auto-logout deadline (timer tick and reload). */
export function pairAutoLogoutDue(data: PairSessionData | null, nowMs: number): Promise<boolean> {
	return flow<boolean>('pair_auto_logout_due', { data, nowMs });
}

const expiredCache = new Map<string, boolean>();

/**
 * Last pushed `pair_expired` answer for this deadline (neutral: not expired).
 * Every read refreshes the answer, so the next poll sees a lapsed deadline.
 */
export function pairExpiredPushed(expiresAt: number): boolean {
	const key = String(expiresAt);
	flow<boolean>('pair_expired', { expiresAt: Number.isFinite(expiresAt) ? expiresAt : null, nowMs: Date.now() })
		.then((expired) => remember(expiredCache, key, expired))
		.catch((error: unknown) => warn('pair_expired', error));
	return expiredCache.get(key) ?? false;
}

// ----------------------------------------------------------------- signup ---

const stepCache = new Map<string, string>();
const signupPathCache = new Map<string, boolean>();
const NEUTRAL_STEP = 'basics';

async function resolveSignup(path: string): Promise<void> {
	const [step, isSignup] = await Promise.all([
		flow<string>('signup_step_from_path', { path }),
		flow<boolean>('signup_is_signup_path', { path }),
	]);
	remember(stepCache, path, step);
	remember(signupPathCache, path, isSignup);
}

/** Awaitable warm-up: after it resolves, the synchronous reads for `path` are exact. */
export function primeSignupPath(path: string | null | undefined): Promise<void> {
	return resolveSignup(path ?? '').catch((error: unknown) => warn('signup_path', error));
}

/** Last pushed signup step for a stored location (neutral: `basics`). */
export function signupStepPushed(path: string): string {
	if (!stepCache.has(path)) void primeSignupPath(path);
	return stepCache.get(path) ?? NEUTRAL_STEP;
}

/** Last pushed signup-location verdict (neutral: false). */
export function isSignupPathPushed(path: string | null | undefined): boolean {
	const key = path ?? '';
	if (!signupPathCache.has(key)) void primeSignupPath(key);
	return signupPathCache.get(key) ?? false;
}

const pathCache = new Map<string, string>();
const settingsStepCache = new Map<string, boolean>();
const NEUTRAL_PATH = '#signup/basics';

/** Awaitable warm-up: after it resolves, `pathFromStepPushed` and `isSettingsStepPushed` are exact for `step`. */
export async function primeSignupStep(step: string): Promise<void> {
	try {
		const [path, settings] = await Promise.all([
			flow<string>('signup_path_from_step', { step }),
			flow<boolean>('signup_is_settings_step', { step }),
		]);
		remember(pathCache, step, path);
		remember(settingsStepCache, step, settings);
	} catch (error) {
		warn('signup_step', error);
	}
}

/** Last pushed hash location for a step (neutral: `#signup/basics`). Async callers prime the step first. */
export function pathFromStepPushed(step: string): string {
	if (!pathCache.has(step)) void primeSignupStep(step);
	return pathCache.get(step) ?? NEUTRAL_PATH;
}

/** Last pushed settings-layout verdict for a step (neutral: false). */
export function isSettingsStepPushed(step: string): boolean {
	if (!settingsStepCache.has(step)) void primeSignupStep(step);
	return settingsStepCache.get(step) ?? false;
}

// -------------------------------------------------------------------- 2FA ---

/** Fills the shared 2FA app lists in place from Rust (`apps` is a reactive array); resolves once pushed. */
export async function loadTfaApps(apps: string[], icons: Record<string, string>): Promise<void> {
	try {
		const list = await flow<{ name: string; icon: string }[]>('tfa_apps', {});
		// Icons first: the app list is reactive and renders icons as soon as it changes.
		for (const app of list) icons[app.name] = app.icon;
		apps.splice(0, apps.length, ...list.map((app) => app.name));
	} catch (error) {
		warn('tfa_apps', error);
	}
}
