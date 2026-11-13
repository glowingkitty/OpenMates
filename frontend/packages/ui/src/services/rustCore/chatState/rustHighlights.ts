/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) message highlights: the page adapter over the
 * shared Rust core Worker `chatState` highlight operations. Loaded only by the
 * guarded branches of sendersMessageHighlights.ts and handlersMessageHighlights.ts,
 * so default builds never bundle it. Rust (packages/openmates-rust/src/chat_state/
 * highlights.rs) builds and encrypts the semantic payload with the chat key, stamps
 * `updated_at`, and decodes inbound frames into a row or a drop reason; the page
 * keeps the chat key lookup, the optimistic store/IndexedDB writes and the socket
 * send. There is no TypeScript fallback: a refused call rejects.
 */
import type { MessageHighlight } from '../../../types/chat';
import { chatStateCall } from './chatListUnitClient';
import type { HighlightInboundReply, HighlightWriteReply } from './bookmarkHighlightProtocol';

export type { HighlightInboundReply, HighlightWriteReply };

/**
 * Rows built by Svelte components can be `$state` proxies, which `postMessage` cannot clone
 * (DataCloneError). The unit JSON-serializes every row anyway, so a JSON round trip here loses nothing.
 */
const plain = <T>(value: T): T => (value === null || value === undefined ? value : JSON.parse(JSON.stringify(value)) as T);

/** `add_message_highlight` frame and the row to store optimistically. */
export const rustAddHighlight = (record: MessageHighlight, chatKey: Uint8Array): Promise<HighlightWriteReply> =>
	chatStateCall('highlightAdd', { record: plain(record), chatKey });

/** `update_message_highlight` frame (`updated_at` = now, seconds) and the merged row. */
export const rustUpdateHighlight = (record: MessageHighlight, chatKey: Uint8Array, nowSeconds: number): Promise<HighlightWriteReply> =>
	chatStateCall('highlightUpdate', { record: plain(record), chatKey, nowSeconds });

/** `remove_message_highlight` frame. */
export const rustRemoveHighlight = (chatId: string, messageId: string, id: string): Promise<HighlightWriteReply> =>
	chatStateCall('highlightRemove', { chatId, messageId, id });

/** Inbound `message_highlight_added`: the row to store or the drop reason. */
export const rustDecodeHighlightAdded = (payload: unknown, chatKey: Uint8Array): Promise<HighlightInboundReply> =>
	chatStateCall('highlightDecodeAdded', { payload: plain(payload), chatKey });

/** Inbound `message_highlight_updated`; author, creation time and key version come from the cached row. */
export const rustDecodeHighlightUpdated = (payload: unknown, chatKey: Uint8Array, cached: MessageHighlight | null): Promise<HighlightInboundReply> =>
	chatStateCall('highlightDecodeUpdated', { payload: plain(payload), chatKey, cached: plain(cached) });
