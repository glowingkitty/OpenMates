/**
 * `chatState` unit protocol: private message bookmarks and message highlights
 * (unitPort.ts wire v1). Rust (packages/openmates-rust/src/chat_state/{bookmarks,
 * highlights}.rs) decides every state transition and does the master-key / chat-key
 * crypto inside the Worker; the page keeps the account-settings HTTP post, the
 * owner/epoch/ciphertext scope fences, localStorage, IndexedDB, the highlight
 * stores and the WebSocket send.
 * spec: specifications/architecture/sync#sync.client.shared-rust-policy
 */
import type { MessageHighlight } from '../../../types/chat';

/** `{chat_id: [message_id]}` in JavaScript object order. */
export type BookmarkIndexReply = Record<string, string[]>;

/** Stable refusal codes; the page maps them back to the web error messages of messageBookmarks.ts. */
export type BookmarkCode = 'bookmark_unavailable' | 'bookmark_limit' | 'bookmark_identity';

export interface HighlightWriteReply { type: string; payload: Record<string, unknown>; record: MessageHighlight | null }
export type HighlightInboundReply =
	| { store: MessageHighlight }
	| { drop: 'undecryptable' | 'missing_anchor' | 'missing_embed' | 'unknown_kind' };

// A type alias (not an interface) so the operation names stay literal keys of `UnitHandlers`.
export type BookmarkHighlightUnitProtocol = {
	bookmarkIdentity: { request: { values: string[] }; response: { valid: boolean } };
	bookmarkReadAccount: {
		request: { masterKey: CryptoKey; encryptedSettings: string | null };
		response: { index: BookmarkIndexReply };
	};
	bookmarkToggleAccount: {
		request: { masterKey: CryptoKey; encryptedSettings: string | null; chatId: string; messageId: string; legacyIds: string[] };
		response: { encryptedSettings: string; index: BookmarkIndexReply };
	};
	bookmarkDecodeDevice: { request: { stored: string | null }; response: { ids: string[] } };
	bookmarkToggleDevice: {
		request: { stored: string | null; chatId: string; messageId: string; legacyIds: string[] };
		response: { stored: string };
	};
	highlightAdd: { request: { record: MessageHighlight; chatKey: Uint8Array }; response: HighlightWriteReply };
	highlightUpdate: { request: { record: MessageHighlight; chatKey: Uint8Array; nowSeconds: number }; response: HighlightWriteReply };
	highlightRemove: { request: { chatId: string; messageId: string; id: string }; response: HighlightWriteReply };
	highlightDecodeAdded: { request: { payload: unknown; chatKey: Uint8Array }; response: HighlightInboundReply };
	highlightDecodeUpdated: {
		request: { payload: unknown; chatKey: Uint8Array; cached: MessageHighlight | null };
		response: HighlightInboundReply;
	};
};
