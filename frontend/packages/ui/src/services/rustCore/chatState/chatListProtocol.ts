/**
 * `chatState` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Every operation is a pure decision of the shared Rust chat-list policy
 * (packages/openmates-rust/src/web_chat_state). The page keeps IndexedDB IO,
 * stores, the local calendar lookup and the DOM, and sends only the normalised
 * records a decision needs (components/chats/utils/chatListInput.ts); the unit
 * answers index lists into the request.
 */
import type { UnitProtocol } from '../host/unitPort';
import type { GroupChatsInput, SortChatsInput } from '../../../components/chats/utils/chatListInput';

export interface ChatStateUnitProtocol extends UnitProtocol {
	sort: { request: SortChatsInput; response: number[] };
	group: { request: GroupChatsInput; response: [string, number[]][] };
}

/** Worker module exports (JSON text in, JSON text out) of browser_chat_state_list.rs. */
export interface ChatListBinding {
	chat_state_sort(input: string): string;
	chat_state_group(input: string): string;
}

/** Operation to binding export. */
export const CHAT_STATE_OPS: Readonly<Record<keyof ChatStateUnitProtocol & string, keyof ChatListBinding>> = Object.freeze({
	sort: 'chat_state_sort',
	group: 'chat_state_group',
});

export function isChatListBinding(value: unknown): value is ChatListBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return Object.values(CHAT_STATE_OPS).every((name) => typeof binding[name] === 'function');
}
