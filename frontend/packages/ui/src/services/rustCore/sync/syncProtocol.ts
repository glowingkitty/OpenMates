/**
 * `sync` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Every operation is a pure decision of the shared Rust web chat-sync policy
 * (packages/openmates-rust/src/web_sync). The page keeps WebSocket IO,
 * IndexedDB IO, chat-key unwrapping, stores and the DOM, and sends only the
 * records a decision needs; the unit answers small JSON outcomes.
 */
import type { UnitProtocol } from '../host/unitPort';
import { INBOUND_OPS, type InboundProtocol } from './inboundProtocol';
import { RECOVERY_OPS, type RecoveryBinding, type RecoveryProtocol } from './recoveryOps';

type JsonRecord = Record<string, unknown>;

export type SyncKeyMismatchPlan = { kind: 'decided'; mismatch: boolean } | { kind: 'direct' } | { kind: 'master' };
export type SyncMergeOutcome = { kind: 'merged'; chat: JsonRecord } | { kind: 'compareKeys'; plan: SyncKeyMismatchPlan };
export type SyncRetryStep =
	| { kind: 'ignore' }
	| { kind: 'pending' }
	| { kind: 'exhausted'; maxAttempts: number }
	| { kind: 'schedule'; attempt: number; delayMs: number; maxAttempts: number };
export type SyncMetadataChatOutcome = { kind: 'skip' } | { kind: 'chat'; chat: JsonRecord };
export type SyncThinkingFields = { ok: true; keys: string[] } | { ok: false; code: 'content' | 'flag' | 'count' };
export interface SyncDeletionStep { chatId: string; explicit: boolean }
export interface SyncMessageKeyGroup { chatId?: string; indices: number[]; needsKey: boolean; sample: string | null }

export interface SyncMergeInput {
	server: JsonRecord;
	/** Own keys of the server record whose value is `undefined` (JSON drops them). */
	serverUndefined: string[];
	local: JsonRecord | null;
	keyMismatch: boolean | null;
	now: number;
	currentUserId?: string | null;
}

export interface SyncUnitProtocol extends UnitProtocol, InboundProtocol, RecoveryProtocol {
	merge: { request: SyncMergeInput; response: SyncMergeOutcome };
	keyMismatch: { request: { server: JsonRecord; local: JsonRecord | null }; response: SyncKeyMismatchPlan };
	retry: { request: { retryable?: unknown; timerPending: boolean; attempt: number; retryAfterMs?: unknown }; response: SyncRetryStep };
	admission: { request: { chatId: string; server: JsonRecord; local: JsonRecord | null }; response: { skip: boolean } };
	metadataChat: { request: { chatId: string; server: JsonRecord; local: JsonRecord | null; now: number }; response: SyncMetadataChatOutcome };
	deletionPlan: { request: { deleted?: unknown; explicit?: unknown }; response: SyncDeletionStep[] };
	messageKeyPlan: { request: { messages: JsonRecord[] }; response: SyncMessageKeyGroup[] };
	messagePreview: { request: { content?: string | null }; response: { units: number[] } };
	thinkingFields: { request: { payload: JsonRecord }; response: SyncThinkingFields };
}

/** Worker module exports (JSON text in, JSON text out) of browser_sync.rs. */
export interface SyncBinding extends RecoveryBinding {
	sync_merge_chat(input: string): string;
	sync_key_mismatch(input: string): string;
	sync_retry_step(input: string): string;
	sync_chat_admission(input: string): string;
	sync_metadata_chat(input: string): string;
	sync_deletion_plan(input: string): string;
	sync_message_key_plan(input: string): string;
	sync_message_preview(input: string): string;
	sync_thinking_fields(input: string): string;
	sync_draft_shell(input: string): string;
	sync_update_frame(input: string): string;
	sync_draft_apply(input: string): string;
}

/** Operation to binding export. */
export const SYNC_OPS: Readonly<Record<keyof SyncUnitProtocol & string, keyof SyncBinding>> = Object.freeze({
	merge: 'sync_merge_chat',
	keyMismatch: 'sync_key_mismatch',
	retry: 'sync_retry_step',
	admission: 'sync_chat_admission',
	metadataChat: 'sync_metadata_chat',
	deletionPlan: 'sync_deletion_plan',
	messageKeyPlan: 'sync_message_key_plan',
	messagePreview: 'sync_message_preview',
	thinkingFields: 'sync_thinking_fields',
	...INBOUND_OPS,
	...RECOVERY_OPS,
});

export function isSyncBinding(value: unknown): value is SyncBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return Object.values(SYNC_OPS).every((name) => typeof binding[name] === 'function');
}
