/**
 * Page-side calls into the shared Rust core for the decision parts of the login,
 * session-restore and logout actions (spec: specifications/features/auth#auth.session.lifecycle).
 * Rust decides; the stores and IO stay in `stores/auth*Actions.ts`. Every function
 * here is awaited by an async caller behind `rustAuthEnabled()`, so the
 * flag-off paths keep their original synchronous shape. A failed Worker call
 * throws (no TypeScript recomputation), except the missing-master-key plan,
 * which fails closed to the most restrictive outcome.
 */
import { rustAuthFlow, rustMissingKeyPlan, type RustMissingKeyContext, type RustMissingKeyPlan } from '../authOperation';
import type { LoginResult } from '../../../stores/authTypes';

/** Rust verdict on the login reply; `success` tells the page to run the store updates. */
export type RustLoginVerdict =
	| { kind: 'rate_limited' | 'error' | 'tfa_invalid' | 'failed'; tfaRequired: boolean; message: string }
	| { kind: 'tfa_required'; tfaAppName: string | null }
	| { kind: 'success'; lastOpened: string | null; backupCodeUsed: unknown; remainingBackupCodes: number | null };

/** Classifies a login reply (status plus raw body text) in Rust. */
export function rustLoginVerdict(status: number, body: string | null, tfaCodeGiven: boolean): Promise<RustLoginVerdict> {
	return rustAuthFlow<RustLoginVerdict>('login_verdict', { status, body, tfaCodeGiven });
}

/** The non-success verdicts as the `LoginResult` the login form already consumes. */
export function loginResultForVerdict(verdict: Exclude<RustLoginVerdict, { kind: 'success' }>): LoginResult {
	if (verdict.kind === 'tfa_required') return { success: true, tfa_required: true, tfa_app_name: verdict.tfaAppName ?? undefined };
	return { success: false, tfa_required: verdict.tfaRequired, message: verdict.message };
}

/** Resumes or drops the stored `debug_session` record of a non-admin user as Rust decides. */
export async function resumeDebugSessionRust(startDebugSession: (debuggingId: string) => void): Promise<void> {
	const stored = localStorage.getItem('debug_session');
	if (!stored) return;
	const parsed = JSON.parse(stored);
	const expiresAtMs = parsed.expires_at ? new Date(parsed.expires_at).getTime() : null;
	const plan = await rustAuthFlow<{ action: 'start' | 'remove'; debuggingId?: string }>('debug_session_resume', {
		hasExpiry: Boolean(parsed.expires_at),
		expiresAtMs: Number.isNaN(expiresAtMs) ? null : expiresAtMs,
		debuggingId: parsed.debugging_id ?? null,
		nowMs: Date.now(),
	});
	if (plan.action === 'start' && plan.debuggingId) startDebugSession(plan.debuggingId);
	else localStorage.removeItem('debug_session');
}

/** Rust decision for the local-versus-account language of a restored session. */
export interface RustLanguageReconcile { pushLocal: boolean; applyAccount: string | null; effectiveIsLocal: boolean }

export function rustLanguageReconcile(serverLanguage: string | null | undefined, defaultLanguage: string, localPreferred: string | null): Promise<RustLanguageReconcile> {
	return rustAuthFlow<RustLanguageReconcile>('language_reconcile', {
		serverLanguage: serverLanguage ?? null, defaultLanguage, localPreferred,
	});
}

/**
 * Most restrictive plan, used only when the Worker cannot answer for an
 * authenticated session without a master key: log out destructively, clear the
 * active chat and cookies, show no notice.
 */
export const FAIL_CLOSED_MISSING_KEY_PLAN: RustMissingKeyPlan = {
	setForced: true, clearActiveChat: true, notify: null, destructiveLogout: true, deleteCookies: true,
};

/** Forced-logout plan from Rust; fails closed when the Worker errors. */
export async function missingKeyPlanFailClosed(context: RustMissingKeyContext): Promise<RustMissingKeyPlan> {
	try {
		return await rustMissingKeyPlan(context);
	} catch (error) {
		console.warn('[RustAuthFlow] missing_key_plan failed, failing closed:', error instanceof Error ? error.message : String(error));
		return FAIL_CLOSED_MISSING_KEY_PLAN;
	}
}
