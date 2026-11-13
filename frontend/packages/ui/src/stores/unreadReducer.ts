/**
 * Wire types of the shared Rust unread bookkeeping (packages/openmates-rust/src/
 * web_chat_state/unread.rs). With VITE_OPENMATES_RUST_CORE the unread store keeps
 * this state value and applies every mutation through the chatState unit; the
 * flag-off store keeps its own closures. Counts keep Map insertion order.
 */
export interface UnreadState {
	counts: [chatId: string, count: number][];
	/** Reply ids already counted per chat, oldest first (capped at 50 by Rust). */
	counted: [chatId: string, messageIds: string[]][];
	/** Chats the user explicitly marked unread. */
	manual: string[];
}

export type UnreadEvent =
	| { type: 'increment'; chat: string; messageId?: string }
	| { type: 'set'; chat: string; count: number; messageId?: string }
	| { type: 'clear'; chat: string }
	| { type: 'mark_manual'; chat: string }
	| { type: 'release_manual'; chat: string }
	| { type: 'clear_all' };

export interface UnreadQuery {
	count: number;
	manual: boolean;
	hasUnread: boolean;
}

export const EMPTY_UNREAD_STATE: UnreadState = { counts: [], counted: [], manual: [] };
