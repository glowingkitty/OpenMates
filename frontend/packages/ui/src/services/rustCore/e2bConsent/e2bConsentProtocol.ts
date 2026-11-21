/**
 * `e2bConsent` unit protocol of the shared Rust core Worker (account-level E2B
 * upload consent; VITE_OPENMATES_RUST_CORE builds only). The core
 * (browser_e2b_consent.rs, `Client::e2b_consent_get/set`) owns the settings
 * route and its refusals; this unit only marshals. Failures arrive as stable codes.
 * Specification: assertion code-run.e2b.upload-consent.
 */

export type E2bDecision = 'allowed' | 'declined';

export interface E2bConsentRecord {
	/** null while the account has not decided for this wording version. */
	decision: E2bDecision | null;
	decidedAt: number | null;
	version: number;
}

export type E2bConsentChoiceWire = 'allow' | 'own_machine' | 'not_now';

/** One frame the page must send on its main WebSocket, in order. */
export interface E2bConsentFrame { name: string; payload: Record<string, unknown> }

/** Core step: frames to send plus the already-encrypted system message to store. */
export interface E2bConsentStep {
	frames: E2bConsentFrame[];
	message: {
		message_id: string; chat_id: string; role: 'system'; content: string;
		encrypted_content: string; created_at: number; user_message_id: string;
	};
}

export type E2bConsentProtocol = {
	requestStep: { request: { frame: Record<string, unknown>; chatKey: Uint8Array }; response: E2bConsentStep };
	answerStep: {
		request: { chatId: string; requestId: string; choice: E2bConsentChoiceWire; chatKey: Uint8Array };
		response: E2bConsentStep;
	};
	/** The core's answered check: the choice that answers requestId, or null. */
	answer: { request: { systemContents: string[]; requestId: string }; response: E2bConsentChoiceWire | null };
	get: { request: Record<string, never>; response: E2bConsentRecord };
	set: { request: { decision: E2bDecision }; response: E2bConsentRecord };
};

export const E2B_CONSENT_UNIT_CLOSE = Object.freeze({ v: 1, type: 'e2b_consent_close' });
export function isE2bConsentUnitClose(value: unknown): boolean {
	const data = value as { v?: unknown; type?: unknown } | null;
	return data?.v === 1 && data.type === 'e2b_consent_close';
}
