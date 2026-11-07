/**
 * `chatState` unit op group for active-chat selection, unread bookkeeping and
 * chat metadata derivation (packages/openmates-rust/src/web_chat_state/{selection,
 * unread,metadata}.rs). Every op is a pure decision over facts the page sends;
 * the page keeps window.location, stores and the DOM.
 */
import type { UrlPlan, UrlPlanFacts } from '../../../stores/activeChatUrlPlan';
import type { GlobalSelectedFacts, GlobalSelectedPlan } from '../../../components/chats/utils/chatSelectionPlan';
import type { UnreadEvent, UnreadState, UnreadQuery } from '../../../stores/unreadReducer';
import type { ReadGateFacts } from '../../readGate';

export interface ChatViewOps {
	selectionUrlPlan: { request: UrlPlanFacts; response: UrlPlan };
	selectionGlobalSelected: { request: GlobalSelectedFacts; response: GlobalSelectedPlan };
	selectionDraftActivation: { request: { selected: string | null; persisted: string }; response: { skip: boolean } };
	unreadReduce: { request: { state: UnreadState; event: UnreadEvent }; response: UnreadState };
	unreadQuery: { request: { state: UnreadState; chat: string; persisted: number | null }; response: UnreadQuery };
	unreadReadGate: { request: ReadGateFacts; response: { proceed: boolean } };
	metadataSharedSubChat: { request: { row: Record<string, unknown>; parent: { chatId: string; sharePii?: boolean; shareHighlights?: boolean } }; response: Record<string, unknown> };
}

/** Worker module exports of browser_chat_state_view.rs. */
export interface ChatViewBinding {
	chat_state_selection_url_plan(input: string): string;
	chat_state_selection_global_selected(input: string): string;
	chat_state_selection_draft_activation(input: string): string;
	chat_state_unread_reduce(input: string): string;
	chat_state_unread_query(input: string): string;
	chat_state_unread_read_gate(input: string): string;
	chat_state_metadata_shared_sub_chat(input: string): string;
}

/** Operation to binding export. */
export const CHAT_VIEW_OPS: Readonly<Record<keyof ChatViewOps & string, keyof ChatViewBinding>> = Object.freeze({
	selectionUrlPlan: 'chat_state_selection_url_plan',
	selectionGlobalSelected: 'chat_state_selection_global_selected',
	selectionDraftActivation: 'chat_state_selection_draft_activation',
	unreadReduce: 'chat_state_unread_reduce',
	unreadQuery: 'chat_state_unread_query',
	unreadReadGate: 'chat_state_unread_read_gate',
	metadataSharedSubChat: 'chat_state_metadata_shared_sub_chat',
});
