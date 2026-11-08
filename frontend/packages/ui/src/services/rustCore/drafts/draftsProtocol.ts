/**
 * Unit protocol of the shared Rust core Worker's `drafts` namespace (unitPort v1
 * envelope, one port per bound generation).
 *
 * The page sends editor markdown and its rendered chat-list preview; Rust (on the
 * history admission's client) encrypts, versions, stores the row and the durable
 * encrypted intent in the existing chats_db, and returns only the version plus
 * the ciphertext `update_draft` payload for the page's existing socket. After
 * that socket's receipt the page asks Rust to remove the intent.
 *
 * Refusal codes (UnitRefusal):
 * - routing, decided before any draft write (page uses its TS writer):
 *   `not_admitted`, `local_session` (history client is local-only), `core_busy`, `existing_chat_required` (no chats_db row), `browser_draft_existing_personal_required`,
 *   `browser_draft_forbidden`, `invalid_request`;
 * - failures (the editor stays unsaved; never a TS rewrite): `draft_effect_<plan>`,
 *   `draft_prepare_<code>_after_<last plan|none>`, `draft_result_<code>`, `draft_payload_<code|shape>`, `draft_write_failed` (cancelled),
 *   `draft_resource_unknown`, `draft_ack_failed`.
 */
import { MAX_DRAFT_MARKDOWN_BYTES } from '../browserDraftProtocol';

export const MAX_DRAFT_PREVIEW_BYTES = 4 * 1024;
export const DRAFT_ROUTING_CODES = /* @__PURE__ */ Object.freeze(['not_admitted', 'local_session', 'core_busy', 'existing_chat_required', 'browser_draft_existing_personal_required',
	'browser_draft_forbidden', 'invalid_request'] as const);
export type DraftRoutingCode = (typeof DRAFT_ROUTING_CODES)[number];

export interface DraftScope { lifecycleGeneration: number; workspaceEpoch: number }
/** Exact ciphertext payload of the server `update_draft` message. */
export interface DraftRemotePayload { chat_id: string; encrypted_draft_md: string; encrypted_draft_preview: string; draft_v: number }

/**
 * Worker-side stage durations of one save (ms, performance.now()), for the page's
 * `openmates:rust:draft-timing` mark. Numbers only: no content, ids or keys.
 * `effectMs` sums the IndexedDB plan executions by plan kind; `prepareMs` is the
 * whole Rust prepare call including them. `borrowBusy` counts the refused borrow
 * attempts (20 ms apart) by the history dispatcher state that was busy.
 */
export interface DraftSaveTiming { borrowWaitMs: number; borrowBusy: Record<string, number>; prepareMs: number; effectMs: Record<string, number> }

export type DraftsProtocol = {
	save: {
		request: { chatId: string; markdown: Uint8Array; preview: string; scope: DraftScope; nowSeconds: number };
		response: { resourceId: string; version: number; payload: DraftRemotePayload; timing: DraftSaveTiming };
	};
	acknowledge: { request: { resourceId: string }; response: { version: number; remoteSynced: true } };
	release: { request: { resourceId: string }; response: { released: boolean } };
};

const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
// Structured clones arrive from another realm, so tags are checked instead of prototypes.
const tag = (v: unknown) => Object.prototype.toString.call(v);
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && tag(v) === '[object Object]' && !Array.isArray(v);
const bytes = (v: unknown): v is Uint8Array => ArrayBuffer.isView(v) && tag(v) === '[object Uint8Array]';
const exact = (v: Record<string, unknown>, keys: readonly string[]) => Object.keys(v).length === keys.length && keys.every((k) => Object.hasOwn(v, k));
const counter = (v: unknown, min: number): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min;

export function isDraftRoutingCode(code: string): code is DraftRoutingCode {
	return (DRAFT_ROUTING_CODES as readonly string[]).includes(code);
}

export function validDraftSaveRequest(v: unknown): v is DraftsProtocol['save']['request'] {
	if (!record(v) || !exact(v, ['chatId', 'markdown', 'preview', 'scope', 'nowSeconds'])) return false;
	const scope = v.scope;
	return typeof v.chatId === 'string' && UUID.test(v.chatId) && bytes(v.markdown)
		&& v.markdown.byteLength > 0 && v.markdown.byteLength <= MAX_DRAFT_MARKDOWN_BYTES
		&& typeof v.preview === 'string' && v.preview.trim() !== '' && new TextEncoder().encode(v.preview).byteLength <= MAX_DRAFT_PREVIEW_BYTES
		&& record(scope) && exact(scope, ['lifecycleGeneration', 'workspaceEpoch'])
		&& counter(scope.lifecycleGeneration, 1) && counter(scope.workspaceEpoch, 0) && counter(v.nowSeconds, 0);
}

export function validDraftResourceRequest(v: unknown): v is { resourceId: string } {
	return record(v) && exact(v, ['resourceId']) && typeof v.resourceId === 'string' && UUID.test(v.resourceId);
}

export function validDraftRemotePayload(v: unknown, chatId: string): v is DraftRemotePayload {
	return record(v) && exact(v, ['chat_id', 'encrypted_draft_md', 'encrypted_draft_preview', 'draft_v']) && v.chat_id === chatId
		&& typeof v.encrypted_draft_md === 'string' && v.encrypted_draft_md !== ''
		&& typeof v.encrypted_draft_preview === 'string' && v.encrypted_draft_preview !== '' && counter(v.draft_v, 1);
}

const duration = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const PLAN_KIND = /^[a-z_]{1,32}$/;

function validDraftSaveTiming(v: unknown): v is DraftSaveTiming {
	if (!record(v) || !exact(v, ['borrowWaitMs', 'borrowBusy', 'prepareMs', 'effectMs']) || !duration(v.borrowWaitMs) || !duration(v.prepareMs)) return false;
	const named = (counts: unknown) => record(counts) && Object.keys(counts).length <= 12
		&& Object.entries(counts).every(([name, value]) => PLAN_KIND.test(name) && duration(value));
	return named(v.effectMs) && named(v.borrowBusy);
}

export function validDraftSaveResponse(v: unknown, chatId: string): v is DraftsProtocol['save']['response'] {
	return record(v) && exact(v, ['resourceId', 'version', 'payload', 'timing']) && validDraftSaveTiming(v.timing)
		&& typeof v.resourceId === 'string' && UUID.test(v.resourceId)
		&& counter(v.version, 1) && validDraftRemotePayload(v.payload, chatId) && v.payload.draft_v === v.version;
}
