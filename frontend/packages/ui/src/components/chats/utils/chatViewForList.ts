/**
 * Chat-list view decisions for Chats.svelte: shared sub-chat metadata and the
 * selection guards. The shared Rust chatState unit decides; there is no
 * TypeScript fallback. The Rust adapter is loaded lazily.
 */
import type { Chat as ChatType } from '../../../types/chat';
import type { SharedSubChatRow } from '../../../services/sharedChatDetailsService';
import type { GlobalSelectedFacts, GlobalSelectedPlan } from './chatSelectionPlan';

/** Chat for a shared sub-chat row (`sharedSubChatToChat`). */
export async function sharedSubChatForList(row: SharedSubChatRow, parent: ChatType): Promise<ChatType> {
	const { chatStateCall } = await import('../../../services/rustCore/chatState/chatListUnitClient');
	return await chatStateCall('metadataSharedSubChat', {
		row: row as unknown as Record<string, unknown>,
		parent: { chatId: parent.chat_id, sharePii: parent.share_pii, shareHighlights: parent.share_highlights },
	}) as unknown as ChatType;
}

/** Rust plan for a `globalChatSelected` event. */
export async function rustGlobalSelectedPlan(facts: GlobalSelectedFacts): Promise<GlobalSelectedPlan> {
	const { chatStateCall } = await import('../../../services/rustCore/chatState/chatListUnitClient');
	return chatStateCall('selectionGlobalSelected', facts);
}

/** Rust verdict for a stale persisted-draft activation. */
export async function rustSkipDraftActivation(selected: string | null, persisted: string): Promise<boolean> {
	const { chatStateCall } = await import('../../../services/rustCore/chatState/chatListUnitClient');
	return (await chatStateCall('selectionDraftActivation', { selected, persisted })).skip;
}
