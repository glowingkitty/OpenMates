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
import type { EmbedKeyWrapperRow, EncryptedDiffRow, PreparedEmbedWrite, StreamCompletionInput } from '../embedWriteAdapter';

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
};

/** What crosses back after a Rust-prepared write was persisted in the Worker. */
export type PersistedEmbedWrite = Omit<PreparedEmbedWrite, 'local_key_wrappers'>;

export type EmbedWriteProtocol = {
	init: { request: { masterKey: CryptoKey }; response: null };
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
	forgetChat: { request: { chatId: string }; response: null };
	clear: { request: null; response: null };
};
