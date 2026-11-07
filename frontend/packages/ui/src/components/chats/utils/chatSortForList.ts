import type { Chat as ChatType } from '../../../types/chat';
import { buildSortInput } from './chatListInput';
import { sortChats } from './chatSortUtils';

// Measurement-only opt-out (`openmates_rust_core_chatstate` = 'ts'), read once per page load.
const RUST_CHAT_LIST: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1'
  && !(typeof localStorage !== 'undefined' && localStorage.getItem('openmates_rust_core_chatstate') === 'ts');
/**
 * `sortChats` for async callers. With the opt-in shared Rust core
 * (build-time VITE_OPENMATES_RUST_CORE === '1') the chatState unit decides the
 * order and there is no TypeScript fallback; default builds run `sortChats`
 * unchanged and never bundle the Rust adapter.
 */
export async function sortChatsForList(chats: ChatType[], serverOrder: string[]): Promise<ChatType[]> {
	if (RUST_CHAT_LIST) {
		const rust = await import('../../../services/rustCore/chatState/rustChatList');
		return rust.rustSortChats(chats, buildSortInput(chats, serverOrder));
	}
	return sortChats(chats, serverOrder);
}
