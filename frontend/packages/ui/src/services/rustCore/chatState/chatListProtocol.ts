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
import type { HiddenForkUnitProtocol } from './hiddenForkProtocol';
import type { BookmarkHighlightUnitProtocol } from './bookmarkHighlightProtocol';
import type { ProjectStateUnitProtocol } from './projectStateOps';
import { TRANSITION_OPS, type TransitionBinding, type TransitionUnitProtocol } from './transitionProtocol';
import type { GroupChatsInput, SortChatsInput } from '../../../components/chats/utils/chatListInput';
import { CHAT_VIEW_OPS, type ChatViewBinding, type ChatViewOps } from './chatViewProtocol';

/** Chat-list ordering and grouping, selection, unread and metadata operations plus message-list transitions and indicators. */
export interface ChatListUnitProtocol extends UnitProtocol, ChatViewOps, TransitionUnitProtocol {
	sort: { request: SortChatsInput; response: number[] };
	group: { request: GroupChatsInput; response: [string, number[]][] };
}

/** Every operation of the `chatState` unit: list policy, hidden chats, forks, bookmarks, highlights and Project decisions. */
export interface ChatStateUnitProtocol
	extends ChatListUnitProtocol, HiddenForkUnitProtocol, BookmarkHighlightUnitProtocol, ProjectStateUnitProtocol {}

/** Worker module exports (JSON text in, JSON text out) of browser_chat_state_list.rs. */
export interface ChatListBinding extends ChatViewBinding, TransitionBinding {
	chat_state_sort(input: string): string;
	chat_state_group(input: string): string;
}

/** Operation to binding export. */
export const CHAT_STATE_OPS: Readonly<Record<keyof ChatListUnitProtocol & string, keyof ChatListBinding>> = Object.freeze({
	sort: 'chat_state_sort',
	group: 'chat_state_group',
	...CHAT_VIEW_OPS,
	...TRANSITION_OPS,
});

export function isChatListBinding(value: unknown): value is ChatListBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return Object.values(CHAT_STATE_OPS).every((name) => typeof binding[name] === 'function');
}
