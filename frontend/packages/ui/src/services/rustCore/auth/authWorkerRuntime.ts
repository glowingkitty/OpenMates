/**
 * Worker-side dispatcher for the Rust web auth exports, installed on the shared
 * Rust core Worker's `auth` unit port (authUnit.ts). Environment-free so it can
 * be unit tested with a synthetic binding. Rust error values are fixed codes;
 * arbitrary exception text never crosses back to the page.
 */
import { runFlowOp } from './flowOps';
import { AUTH_PROTOCOL_VERSION, isAuthHttpRequest, type AuthCall, type AuthHttpReply, type AuthToWorker } from './authProtocol';

export interface RustPasswordLogin {
	request(): string | undefined;
	reply(status: number, body?: string): boolean;
	finish(): Promise<unknown>;
	free?(): void;
}
export interface RustRecoveryLogin {
	request(): string | undefined;
	finish(status: number, body?: string): Promise<unknown>;
	free?(): void;
}
export interface RustWebAuthBinding {
	WebAuthPasswordLogin: { start(input: string, password: string, tfa?: string): RustPasswordLogin };
	WebAuthRecoveryLogin: { start(input: string, recoveryKey: string): RustRecoveryLogin };
	web_auth_session_request(signals: string, sessionId: string): string;
	web_auth_classify_session(status: number, body?: string): string;
	web_auth_missing_key_plan(context: string): string;
	web_auth_logout_server_step(captured: number, current: number, skip: boolean, policy: boolean): string;
	web_auth_logout_may_delete_cookies(captured: number, current: number): boolean;
	web_auth_logout_frame(tabId: string): string;
	web_auth_accept_logout_frame(frame: string, ownTabId: string): boolean;
}
export interface AuthWorkerScope {
	postMessage(message: unknown): void;
	addEventListener(type: 'message', listener: (event: MessageEvent<unknown>) => void): void;
	close(): void;
}

export function isRustWebAuthBinding(value: unknown): value is RustWebAuthBinding {
	const binding = value as Partial<RustWebAuthBinding> | null;
	return !!binding && typeof binding.WebAuthPasswordLogin?.start === 'function' && typeof binding.WebAuthRecoveryLogin?.start === 'function'
		&& typeof binding.web_auth_session_request === 'function' && typeof binding.web_auth_classify_session === 'function'
		&& typeof binding.web_auth_missing_key_plan === 'function' && typeof binding.web_auth_logout_server_step === 'function'
		&& typeof binding.web_auth_logout_may_delete_cookies === 'function' && typeof binding.web_auth_logout_frame === 'function'
		&& typeof binding.web_auth_accept_logout_frame === 'function';
}

function refusal(error: unknown): string {
	return typeof error === 'string' && /^[a-z_]{1,48}$/.test(error) ? error : 'rust_auth_failed';
}

/**
 * Serves the auth protocol on `scope`. The returned dispose rejects every login
 * still waiting for a page reply (`cancelled`), so its derived keys are freed
 * now, and ignores later traffic. It does not close the scope.
 */
export function installAuthWorker(scope: AuthWorkerScope, binding: RustWebAuthBinding): () => void {
	let disposed = false;
	const replies = new Map<number, { resolve(reply: AuthHttpReply): void; reject(error: string): void }>();
	const post = (message: Record<string, unknown>) => scope.postMessage({ v: AUTH_PROTOCOL_VERSION, ...message });

	const fetchViaPage = (id: number, encoded: string): Promise<AuthHttpReply> => {
		const http: unknown = JSON.parse(encoded);
		if (!isAuthHttpRequest(http)) return Promise.reject('protocol');
		if (disposed) return Promise.reject('cancelled');
		return new Promise((resolve, reject) => { replies.set(id, { resolve, reject }); post({ id, http }); });
	};

	async function passwordLogin(id: number, call: Extract<AuthCall, { op: 'password_login' }>): Promise<unknown> {
		const login = binding.WebAuthPasswordLogin.start(JSON.stringify(call.input), call.password, call.tfa ?? undefined);
		try {
			for (let request = login.request(); request !== undefined; request = login.request()) {
				const reply = await fetchViaPage(id, request);
				if (login.reply(reply.status, reply.body ?? undefined)) break;
			}
		} catch (error) {
			login.free?.(); // Drop the derived keys now instead of at GC.
			throw error;
		}
		// finish() consumes the Rust value (wasm-bindgen frees it).
		return login.finish();
	}

	async function recoveryLogin(id: number, call: Extract<AuthCall, { op: 'recovery_login' }>): Promise<unknown> {
		const login = binding.WebAuthRecoveryLogin.start(JSON.stringify(call.input), call.recoveryKey);
		const request = login.request();
		if (request === undefined) { login.free?.(); throw 'protocol'; }
		let reply: AuthHttpReply;
		try {
			reply = await fetchViaPage(id, request);
		} catch (error) {
			login.free?.();
			throw error;
		}
		// finish() consumes the Rust value (wasm-bindgen frees it).
		return login.finish(reply.status, reply.body ?? undefined);
	}

	function run(id: number, call: AuthCall): Promise<unknown> | unknown {
		switch (call.op) {
			case 'password_login': return passwordLogin(id, call);
			case 'recovery_login': return recoveryLogin(id, call);
			case 'session_request': return JSON.parse(binding.web_auth_session_request(call.signals, call.sessionId));
			case 'classify_session': return JSON.parse(binding.web_auth_classify_session(call.status, call.body ?? undefined));
			case 'missing_key_plan': return JSON.parse(binding.web_auth_missing_key_plan(call.context));
			case 'logout_server_step': return JSON.parse(binding.web_auth_logout_server_step(call.captured, call.current, call.skipServerLogout, call.policyViolation));
			case 'logout_may_delete_cookies': return binding.web_auth_logout_may_delete_cookies(call.captured, call.current);
			case 'logout_frame': return binding.web_auth_logout_frame(call.tabId);
			case 'accept_logout_frame': return binding.web_auth_accept_logout_frame(call.frame, call.ownTabId);
				case 'flow': return runFlowOp(binding, call.name, call.args);
		}
	}

	scope.addEventListener('message', (event) => {
		if (disposed) return;
		const data = event.data as AuthToWorker | null;
		if (!data || data.v !== AUTH_PROTOCOL_VERSION || !Number.isSafeInteger(data.id)) { scope.close(); return; }
		if ('reply' in data || 'replyFailed' in data) {
			const waiting = replies.get(data.id);
			replies.delete(data.id);
			if (!waiting) { scope.close(); return; }
			if ('reply' in data) waiting.resolve(data.reply); else waiting.reject('network');
			return;
		}
		const id = data.id;
		Promise.resolve().then(() => run(id, data)).then(
			(value) => { if (!disposed) post({ id, ok: true, value }); },
			(error: unknown) => { if (!disposed) post({ id, ok: false, code: refusal(error) }); },
		);
	});
	post({ ready: true });
	return () => {
		if (disposed) return;
		disposed = true;
		for (const waiting of replies.values()) waiting.reject('cancelled');
		replies.clear();
	};
}
