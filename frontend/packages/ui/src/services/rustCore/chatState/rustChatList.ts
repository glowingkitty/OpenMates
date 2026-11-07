/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) chat-list ordering and grouping: the page
 * adapter over the shared Rust core Worker `chatState` unit. Loaded only by the
 * guarded branches of Chats.svelte, ActiveChat.svelte and SearchResults.svelte,
 * so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_chat_state) decides the display order
 * (`sortChats`) and the time/explicit grouping (`groupChats`); the page keeps
 * the chat objects, the local calendar lookup and rendering. There is no
 * TypeScript fallback: a refused or failed call rejects with its fixed code.
 */
import type { Chat as ChatType } from '../../../types/chat';
import type { GroupChatsInput, SortChatsInput } from '../../../components/chats/utils/chatListInput';
import { chatStateCall } from './chatListUnitClient';

/** Rust display order of `chats` for a request built by `buildSortInput` (same array, same moment). */
export async function rustSortChats(chats: readonly ChatType[], input: SortChatsInput): Promise<ChatType[]> {
	const order = await chatStateCall('sort', input);
	return order.map((index) => chats[index]);
}

/** Rust grouping of `chats` for a request built by `buildGroupInput`; key order is Rust's first-seen order. */
export async function rustGroupChats(chats: readonly ChatType[], input: GroupChatsInput): Promise<Record<string, ChatType[]>> {
	const groups = await chatStateCall('group', input);
	const result: Record<string, ChatType[]> = {};
	for (const [key, indices] of groups) result[key] = indices.map((index) => chats[index]);
	return result;
}
