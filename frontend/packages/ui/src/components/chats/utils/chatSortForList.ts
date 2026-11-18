import type { Chat as ChatType } from '../../../types/chat';
import { buildSortInput } from './chatListInput';

/**
 * `sortChats` for async callers. The shared Rust chatState unit decides the
 * order; there is no TypeScript fallback. The Rust adapter is loaded lazily.
 */
export async function sortChatsForList(chats: ChatType[], serverOrder: string[]): Promise<ChatType[]> {
	const rust = await import('../../../services/rustCore/chatState/rustChatList');
	return rust.rustSortChats(chats, buildSortInput(chats, serverOrder));
}
