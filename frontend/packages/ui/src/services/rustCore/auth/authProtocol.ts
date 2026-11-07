/**
 * Message protocol between the page and the Rust auth Worker. The Worker owns
 * the account logic (shared Rust `web_auth`); the page executes the HTTP
 * requests Rust describes with its own credentialed Fetch, so the requests and
 * cookies are exactly those of the deployed TypeScript path.
 */
export const AUTH_PROTOCOL_VERSION = 1;
/** Header value Rust uses for the page origin (`web_auth::PAGE_ORIGIN`). */
export const PAGE_ORIGIN_PLACEHOLDER = '{page_origin}';

export interface AuthHttpRequest {
	method: 'POST';
	path: string;
	headers: [string, string][];
	body: string | null;
}
export interface AuthHttpReply { status: number; body: string | null }

export interface PasswordLoginInput {
	email: string;
	sessionId: string;
	/** Base64 email salt from the email-step lookup. */
	userEmailSalt: string;
	emailEncryptionKey: string | null;
	stayLoggedIn: boolean;
	codeType: 'otp' | 'backup' | null;
}

export type RecoveryLoginInput = Omit<PasswordLoginInput, 'codeType'>;

export type AuthCall =
	| { op: 'password_login'; input: PasswordLoginInput; password: string; tfa: string | null }
	| { op: 'recovery_login'; input: RecoveryLoginInput; recoveryKey: string }
	| { op: 'session_request'; signals: string; sessionId: string }
	| { op: 'classify_session'; status: number; body: string | null }
	| { op: 'missing_key_plan'; context: string }
	| { op: 'logout_server_step'; captured: number; current: number; skipServerLogout: boolean; policyViolation: boolean }
	| { op: 'logout_may_delete_cookies'; captured: number; current: number }
	| { op: 'logout_frame'; tabId: string }
	| { op: 'accept_logout_frame'; frame: string; ownTabId: string }
	| { op: 'flow'; name: string; args: string };

/** page → worker */
export type AuthToWorker =
	| ({ v: 1; id: number } & AuthCall)
	| { v: 1; id: number; reply: AuthHttpReply }
	| { v: 1; id: number; replyFailed: true };
/** worker → page */
export type AuthFromWorker =
	| { v: 1; ready: boolean }
	| { v: 1; id: number; http: AuthHttpRequest }
	| { v: 1; id: number; ok: true; value: unknown }
	| { v: 1; id: number; ok: false; code: string };

export interface PasswordLoginResult {
	kind: 'response' | 'unlocked' | 'unlock_failed';
	status: number;
	/** Server login response JSON text. */
	data: string;
	credentialVersion?: number;
	key?: CryptoKey;
	code?: string;
}

function record(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}
export function isAuthHttpRequest(value: unknown): value is AuthHttpRequest {
	return record(value) && value.method === 'POST' && typeof value.path === 'string' && value.path.startsWith('/v1/auth/')
		&& Array.isArray(value.headers) && value.headers.every((pair) => Array.isArray(pair) && pair.length === 2
			&& typeof pair[0] === 'string' && typeof pair[1] === 'string')
		&& (value.body === null || typeof value.body === 'string');
}
export function isAuthFromWorker(value: unknown): value is AuthFromWorker {
	if (!record(value) || value.v !== AUTH_PROTOCOL_VERSION) return false;
	if ('ready' in value) return typeof value.ready === 'boolean';
	if (!Number.isSafeInteger(value.id)) return false;
	if ('http' in value) return isAuthHttpRequest(value.http);
	return value.ok === true ? 'value' in value : value.ok === false && typeof value.code === 'string';
}

/** page → auth unit: release this unit port only; the shared Worker keeps running. Never a valid call. */
export const AUTH_UNIT_CLOSE = /* @__PURE__ */ Object.freeze({ v: AUTH_PROTOCOL_VERSION, authUnitClose: true as const });
/** True only for the exact `AUTH_UNIT_CLOSE` frame shape. */
export function isAuthUnitClose(value: unknown): boolean {
	return record(value) && Object.getPrototypeOf(value) === Object.prototype && Object.keys(value).length === 2
		&& value.v === AUTH_PROTOCOL_VERSION && value.authUnitClose === true;
}
