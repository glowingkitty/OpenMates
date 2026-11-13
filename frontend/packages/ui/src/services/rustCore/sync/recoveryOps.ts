/**
 * Stateless reply-recovery operations of the shared Rust `sync` unit.
 *
 * Types and the op-to-export table for the recovery decisions implemented by
 * packages/openmates-rust/src/web_stream (recovery.rs, recovery_text.rs). The
 * page keeps fetch, IndexedDB, TOON decoding and events and sends only the
 * records a decision needs. Merged into SYNC_OPS by syncProtocol.ts.
 */
import type { UnitProtocol } from '../host/unitPort';

/** The three chat fields a recovered terminal ACK may raise. */
export interface RecoveryChatFence {
	messages_v?: number;
	last_edited_overall_timestamp?: number;
	updated_at?: number;
}
export type RecoveryApplyOutcome = { keep: true } | ({ keep: false } & RecoveryChatFence);
export type RecoveryCatalogOutcome = { kind: 'none' } | { kind: 'invalid' } | { kind: 'context'; app_id: string; skill_id: string };
export type RecoveryHistorySourceOutcome =
	| { kind: 'source'; source: string }
	| { kind: 'json_model'; field: 'docx_model' | 'notebook' }
	| { kind: 'error'; code: 'mismatch' | 'mail_fields' | 'document_body' | 'format' };
export type RecoveryContextFrameOutcome = { kind: 'ok' } | { kind: 'error'; code: 'undecryptable' | 'invalid' | 'identity' };
export interface RecoveryProtocol extends UnitProtocol {
	recoveryApply: { request: { latest: RecoveryChatFence; committedVersion: number; now: number }; response: RecoveryApplyOutcome };
	recoveryWindowVersion: { request: { chatId: string; result: unknown }; response: { version: number | null } };
	recoveryAssistantVersion: {
		request: { chatId: string; assistantMessageId: string; userMessageId: string; result: unknown };
		response: { version: number | null };
	};
	recoveryInitialDiff: { request: { status: number; detail: unknown; version: number }; response: { unwritten: boolean } };
	recoveryCatalog: { request: { producerApp?: unknown; producerSkill?: unknown; fields?: unknown }; response: RecoveryCatalogOutcome };
	recoveryContextFrame: {
		request: { plaintext: string | null; identity: Record<string, unknown>; phase: string };
		response: RecoveryContextFrameOutcome;
	};
	recoveryHistorySource: { request: { type: string; decoded: unknown }; response: RecoveryHistorySourceOutcome };
}

/** Worker module exports (JSON text in, JSON text out) of browser_stream.rs. */
export interface RecoveryBinding {
	stream_recovery_apply(input: string): string;
	stream_recovery_window_version(input: string): string;
	stream_recovery_assistant_version(input: string): string;
	stream_recovery_initial_diff(input: string): string;
	stream_recovery_catalog(input: string): string;
	stream_recovery_context_frame(input: string): string;
	stream_recovery_history_source(input: string): string;
}

/** Operation to binding export. */
export const RECOVERY_OPS: Readonly<Record<keyof RecoveryProtocol & string, keyof RecoveryBinding>> = /* @__PURE__ */ Object.freeze({
	recoveryApply: 'stream_recovery_apply',
	recoveryWindowVersion: 'stream_recovery_window_version',
	recoveryAssistantVersion: 'stream_recovery_assistant_version',
	recoveryInitialDiff: 'stream_recovery_initial_diff',
	recoveryCatalog: 'stream_recovery_catalog',
	recoveryContextFrame: 'stream_recovery_context_frame',
	recoveryHistorySource: 'stream_recovery_history_source',
});
