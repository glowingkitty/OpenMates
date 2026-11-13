/**
 * Chat-list view decisions for Chats.svelte: shared sub-chat metadata and the
 * selection guards. Flag-off (default) callers use the TypeScript helpers
 * directly; with the opt-in shared Rust core (build-time VITE_OPENMATES_RUST_CORE
 * === '1') the chatState unit decides and there is no TypeScript fallback. The
 * Rust adapter is loaded lazily so default builds never bundle it.
 */
import type { Chat as ChatType } from '../../../types/chat';
import type { SharedSubChatRow } from '../../../services/sharedChatDetailsService';
import { sharedSubChatToChat } from './sharedSubChatChat';
import type { GlobalSelectedFacts, GlobalSelectedPlan } from './chatSelectionPlan';

export const RUST_CHAT_VIEW: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1'
	&& !(typeof localStorage !== 'undefined' && localStorage.getItem('openmates_rust_core_chatstate') === 'ts');

/** Chat for a shared sub-chat row (`sharedSubChatToChat`). */
export async function sharedSubChatForList(row: SharedSubChatRow, parent: ChatType): Promise<ChatType> {
	if (RUST_CHAT_VIEW) {
		const { chatStateCall } = await import('../../../services/rustCore/chatState/chatListUnitClient');
		return await chatStateCall('metadataSharedSubChat', {
			row: row as unknown as Record<string, unknown>,
			parent: { chatId: parent.chat_id, sharePii: parent.share_pii, shareHighlights: parent.share_highlights },
		}) as unknown as ChatType;
	}
	return sharedSubChatToChat(row, parent);
}

/** Rust plan for a `globalChatSelected` event (flag-on only; flag-off uses `planGlobalSelected`). */
export async function rustGlobalSelectedPlan(facts: GlobalSelectedFacts): Promise<GlobalSelectedPlan> {
	const { chatStateCall } = await import('../../../services/rustCore/chatState/chatListUnitClient');
	return chatStateCall('selectionGlobalSelected', facts);
}

/** Rust verdict for a stale persisted-draft activation (flag-on only; flag-off uses `skipDraftActivation`). */
export async function rustSkipDraftActivation(selected: string | null, persisted: string): Promise<boolean> {
	const { chatStateCall } = await import('../../../services/rustCore/chatState/chatListUnitClient');
	return (await chatStateCall('selectionDraftActivation', { selected, persisted })).skip;
}
