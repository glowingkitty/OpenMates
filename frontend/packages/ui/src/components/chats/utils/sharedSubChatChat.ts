/**
 * Metadata derivation of a shared sub-chat row (extracted from Chats.svelte
 * `sharedSubChatToChat`). Flag-off path; with VITE_OPENMATES_RUST_CORE the chatState
 * unit derives it (packages/openmates-rust/src/web_chat_state/metadata.rs).
 */
import type { Chat as ChatType } from '../../../types/chat';
import type { SharedSubChatRow } from '../../../services/sharedChatDetailsService';

export function sharedSubChatToChat(row: SharedSubChatRow, parent: ChatType): ChatType {
	const createdAt = row.created_at;
	return {
		chat_id: row.id,
		encrypted_title: row.encrypted_title ?? null,
		messages_v: row.messages_v ?? 0,
		title_v: row.title_v ?? 0,
		metadata_v: row.metadata_v,
		last_edited_overall_timestamp: row.last_edited_overall_timestamp ?? row.updated_at ?? createdAt,
		unread_count: row.unread_count ?? 0,
		created_at: createdAt,
		updated_at: row.updated_at ?? createdAt,
		encrypted_chat_summary: row.encrypted_chat_summary ?? null,
		encrypted_icon: row.encrypted_icon ?? null,
		encrypted_category: row.encrypted_category ?? null,
		parent_id: parent.chat_id,
		is_sub_chat: true,
		is_shared_by_others: true,
		share_pii: parent.share_pii ?? false,
		share_highlights: parent.share_highlights ?? true,
		group_key: 'shared_by_others',
		budget_limit: row.budget_limit ?? null,
		budget_spent: row.budget_spent ?? 0
	};
}
