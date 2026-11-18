/**
 * Unit protocols of the shared Rust core Worker's embed namespaces.
 *
 * Both namespaces speak the generic unit port wire (host/unitPort.ts:
 * `{v:1,id,type:'request',op,payload}` / `{v:1,id,type:'result',ok,...}`).
 * `EMBED_UNIT_CLOSE` (never a valid unit request) disposes the Worker-side unit
 * and closes its port without touching the shared Worker.
 *
 * - `embedData` (pre-bind, stateless): opens the encrypted fields of stored
 *   `embeds` rows with the embed key the page resolved, in Rust
 *   (`embed_write::read`) on the Worker's WebCrypto. Only the render-ready
 *   decrypted fields cross back.
 * - `embedWrite` (bound to a generation): the Rust embed write session
 *   (`BrowserEmbedWriter`) next to the Worker-side IndexedDB rows it writes.
 */
import type { EmbedReadProtocol } from './readOps';
import type { EmbedKeyWrapperRow, EncryptedDiffRow, PreparedEmbedWrite, StreamCompletionInput } from '../embedWriteAdapter';
import type { ChildRevisionProtocol } from './childRevisionProtocol';

export const EMBED_UNIT_CLOSE = /* @__PURE__ */ Object.freeze({ embedUnitClose: 1 as const });

export function isEmbedUnitClose(value: unknown): boolean {
	return typeof value === 'object' && value !== null && Object.getPrototypeOf(value) === Object.prototype
		&& Object.keys(value).length === 1 && (value as Record<string, unknown>).embedUnitClose === 1;
}

/** Rows per `openFields` request; a larger page batch is refused, never truncated. */
export const EMBED_DATA_MAX_ITEMS = 256;

/** Ciphertext fields of one stored `embeds` row plus the embed key that opens them. */
export interface EmbedFieldsRequest {
	key: Uint8Array;
	encrypted_content: string | null;
	encrypted_type: string | null;
	encrypted_text_preview: string | null;
}

/** Rust `OpenedEmbedFields`: decrypted strings or null; `content_failed` when content did not open. */
export interface OpenedEmbedFields {
	content: string | null;
	content_failed: boolean;
	type: string | null;
	text_preview: string | null;
}

/** Per-row result: the opened fields, or a fixed Rust rejection code for that row only. */
export type EmbedFieldsResult = { ok: true; fields: OpenedEmbedFields } | { ok: false; code: string };

export type EmbedDataProtocol = {
	openFields: { request: { items: EmbedFieldsRequest[] }; response: EmbedFieldsResult[] };
	/** Rust TOON decode (non-strict, as `@toon-format/toon` `decode(text, {strict:false})`):
	 * JSON text per input, or null where TOON refused it (`toon_decode_failed`). */
	decodeToon: { request: { texts: string[] }; response: (string | null)[] };
} & EmbedReadProtocol;

/** One stored `embeds` row whose key the Worker resolves itself (embedKeyResolution.ts). */
export interface StoredRowRequest {
	embedId: string;
	hashedChatId: string | null;
	encrypted_content: string | null;
	encrypted_type: string | null;
	encrypted_text_preview: string | null;
}

/** Opened fields, or a per-row code plus wrapper chats whose validated chat key would unlock it. */
export type StoredRowResult = { ok: true; fields: OpenedEmbedFields } | { ok: false; code: string; pendingChatHashes: string[] };

/** What crosses back after a Rust-prepared write was persisted in the Worker. */
export type PersistedEmbedWrite = Omit<PreparedEmbedWrite, 'local_key_wrappers'>;

export type EmbedWriteProtocol = {
	/** Account sessions send the non-extractable master key; a signed-out guest session sends `localOnly` (no key). */
	init: { request: { masterKey: CryptoKey } | { localOnly: true }; response: null };
	adoptChatKey: { request: { chatId: string; encryptedChatKey: string }; response: null };
	adoptEmbedKeyWrapper: { request: { embedId: string; chatId: string; row: EmbedKeyWrapperRow }; response: null };
	adoptChildEmbedKey: { request: { childId: string; parentId: string; wrappedByParent: string }; response: null };
	hasKeys: { request: { chatId: string | null; embedId: string | null }; response: { chat: boolean; embed: boolean } };
	/** Finalized `send_embed_data`; `normalizedType` is the registry form of `payload.type`. */
	prepareStreamCompletion: { request: { payload: StreamCompletionInput; normalizedType: string }; response: PersistedEmbedWrite };
	/** processing->finished `embed_update`. */
	prepareProcessingUpdate: {
		request: { existing: Record<string, unknown>; chatId: string; userId: string | null; messageId: string | null; normalizedType: string };
		response: PersistedEmbedWrite;
	};
	/** Sealed root revision: stores reconciled rows locally (never sent). */
	reconcileSealedHistory: { request: { embedId: string; rows: unknown[]; declaredVersion: number }; response: number };
	/** Ordinary path: stores the encrypted local row; returns the server payload, null when skipped. */
	encryptHistoryRow: { request: { embedId: string; row: Record<string, unknown>; hashedUserId: string }; response: Record<string, unknown> | null };
	adoptCanonicalRow: { request: { embedId: string; page: unknown; row: Record<string, unknown> }; response: EncryptedDiffRow };
	verifyCanonicalHead: { request: { embedId: string; page: unknown; rows: unknown[] }; response: number };
	reconstructVersions: { request: { embedId: string }; response: string };
	/** Rust history policy: a canonical bounded-v1 read is `absent` or `present`. */
	classifyCanonicalRead: { request: { status: number; body: unknown; version: number; durableHead: boolean }; response: string };
	/** Rust history policy: highest streamed version of `embedId`, null when none. */
	historyHeadVersion: { request: { embedId: string; rows: unknown[] }; response: number | null };
	/** Chat key the page's write guard validated (zeroed after install; never returned). */
	adoptPageChatKey: { request: { chatId: string; key: Uint8Array }; response: null };
	/** Early HKDF key of a processing parent; false when the chat key is not installed. */
	deriveEarlyKey: { request: { embedId: string; chatId: string }; response: boolean };
	/** Resolves each row's embed key in the Worker (TS getEmbedKey order) and opens its fields. */
	openStoredRows: { request: { rows: StoredRowRequest[] }; response: StoredRowResult[] };
	forgetChat: { request: { chatId: string }; response: null };
	clear: { request: null; response: null };
} & ChildRevisionProtocol;
