/**
 * `persist` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * IndexedDB stays the store; the row decisions of the `messages` store run in
 * shared Rust (packages/openmates-rust/src/web_persist/, port of
 * db/messageRowPolicy.ts). The page keeps the schema, transactions, encryption
 * and every read/write: it sends stored/incoming rows and gets decisions back.
 * Only a malformed payload refuses, with the fixed code `protocol`.
 *
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */
import type { UnitProtocol } from '../host/unitPort';
import type { Message } from '../../../types/chat';
import type * as cache from '../../db/cacheTypes';
import type * as chatRows from '../../db/chatRowPolicy';

export interface PersistUnitProtocol extends UnitProtocol {
	/** `shouldUpdateMessage` for each stored/incoming pair, in order. */
	messageShouldUpdate: {
		request: { pairs: Array<{ existing: Message; incoming: Message }> };
		response: { results: boolean[] };
	};
	/** The two checks of `saveMessage` against the stored row. */
	messageSaveDecision: {
		request: { existing: Message; incoming: Message; incomingEncrypted: Message };
		response: { shouldUpdate: boolean; fillsEncrypted: boolean };
	};
	/** `findContentDuplicate`: index of the first candidate that duplicates `message`, or null. */
	messageContentDuplicate: {
		request: { candidates: Message[]; message: Message };
		response: { index: number | null };
	};
	/** `isSafeToEvictMessage` per stored row (`null` is a missing row). */
	messageSafeToEvict: {
		request: { messages: Array<Message | null> };
		response: { results: boolean[] };
	};
	/** `planDuplicateCleanup`: message ids whose stored copy is deleted, in order. */
	duplicateCleanup: {
		request: { messages: Array<{ chat_id: string; message_id: string }> };
		response: { deleteIds: string[] };
	};
	/** Window read plan (db/cachePolicy.ts planMessageWindow). */
	windowPlan: { request: cache.WindowPlanInput; response: cache.WindowPlan };
	windowResultMeta: { request: cache.WindowResultMetaInput; response: cache.WindowResultMeta };
	windowPageRecord: { request: cache.WindowPageRecordInput; response: cache.WindowPageRecord };
	evictPlan: { request: cache.EvictPlanInput; response: { deleteCount: number; candidates: string[] } };
	evictDeletePlan: {
		request: { pages: cache.CachePage[]; deletingPageIds: string[]; protectedMessageIds?: string[] | null };
		response: { plan: Array<{ pageId: string; messageIds: string[] }> };
	};
	/** Every stored message of a cached page is safe to evict (`null` is a missing row). */
	pageConfirmed: { request: { messages: Array<Message | null> }; response: { confirmed: boolean } };
	budgetThrottle: { request: { force: boolean; now: number; lastCheckAt: number }; response: { throttled: boolean } };
	budgetTarget: {
		request: { force: boolean; configuredBytes: number; quota?: number | null; usage?: number | null };
		response: { target: number; trim: boolean };
	};
	budgetCandidates: { request: { pages: cache.CachePage[] }; response: { pages: Array<{ id: string; chat_id: string }> } };
	budgetChatStep: {
		request: { normalPageCount: number };
		response: { skip: boolean; maxPagesPerChat: number };
	};
	budgetAfter: {
		request: { force: boolean; removed: number; target: number; usage?: number | null };
		response: { action: cache.BudgetAfterAction };
	};
	quotaStep: {
		request: { stage: 'write' | 'retry'; canRetry: boolean; errorName: string | null };
		response: { action: cache.QuotaAction };
	};
	chatsPageSize: { request: { limit: number }; response: { size: number } };
	chatDefaults: {
		request: { chat: Parameters<typeof chatRows.chatRowDefaults>[0]; now: number };
		response: ReturnType<typeof chatRows.chatRowDefaults>;
	};
	keylessDraftOnly: {
		request: { chat: Record<string, unknown>; existing: Record<string, unknown> | null };
		response: { expected: boolean };
	};
	candidateKeys: { request: { existing?: string[] | null; blob: string }; response: { updated: string[] | null } };
	draftMerge: {
		request: {
			chatId: string; current: chatRows.DraftMergeRow | null; fields: chatRows.DraftFieldsInput;
			missingRow: chatRows.DraftMergeRow | null; undefinedKeys: string[];
		};
		response: { action: chatRows.DraftMergeAction; patch: Record<string, unknown>; undefinedKeys: string[] };
	};
	teamDraftIntent: {
		request: {
			chat: chatRows.TeamDraftRow | null; teamId: string; pending?: 'update' | 'delete';
			expected?: chatRows.TeamDraftExpectation;
		};
		response: { apply: boolean; patch: Record<string, unknown>; undefinedKeys: string[] };
	};
}

/** Worker module exports (snake_case, JSON text) of browser_persist.rs. */
export interface PersistBinding {
	persist_message_should_update(input: string): string;
	persist_message_save_decision(input: string): string;
	persist_message_content_duplicate(input: string): string;
	persist_message_safe_to_evict(input: string): string;
	persist_message_duplicate_cleanup(input: string): string;
	persist_window_plan(input: string): string;
	persist_window_result_meta(input: string): string;
	persist_window_page_record(input: string): string;
	persist_evict_plan(input: string): string;
	persist_evict_delete_plan(input: string): string;
	persist_page_confirmed(input: string): string;
	persist_budget_throttle(input: string): string;
	persist_budget_target(input: string): string;
	persist_budget_candidates(input: string): string;
	persist_budget_chat_step(input: string): string;
	persist_budget_after(input: string): string;
	persist_quota_step(input: string): string;
	persist_chats_page_size(input: string): string;
	persist_chat_defaults(input: string): string;
	persist_keyless_draft_only(input: string): string;
	persist_candidate_keys(input: string): string;
	persist_draft_merge(input: string): string;
	persist_team_draft_intent(input: string): string;
}

/** Op name -> binding export; the unit installs one handler per entry. */
export const PERSIST_OPS: Readonly<Record<keyof PersistUnitProtocol & string, keyof PersistBinding>> = {
	messageShouldUpdate: 'persist_message_should_update',
	messageSaveDecision: 'persist_message_save_decision',
	messageContentDuplicate: 'persist_message_content_duplicate',
	messageSafeToEvict: 'persist_message_safe_to_evict',
	duplicateCleanup: 'persist_message_duplicate_cleanup',
	windowPlan: 'persist_window_plan',
	windowResultMeta: 'persist_window_result_meta',
	windowPageRecord: 'persist_window_page_record',
	evictPlan: 'persist_evict_plan',
	evictDeletePlan: 'persist_evict_delete_plan',
	pageConfirmed: 'persist_page_confirmed',
	budgetThrottle: 'persist_budget_throttle',
	budgetTarget: 'persist_budget_target',
	budgetCandidates: 'persist_budget_candidates',
	budgetChatStep: 'persist_budget_chat_step',
	budgetAfter: 'persist_budget_after',
	quotaStep: 'persist_quota_step',
	chatsPageSize: 'persist_chats_page_size',
	chatDefaults: 'persist_chat_defaults',
	keylessDraftOnly: 'persist_keyless_draft_only',
	candidateKeys: 'persist_candidate_keys',
	draftMerge: 'persist_draft_merge',
	teamDraftIntent: 'persist_team_draft_intent',
};

export function isPersistBinding(value: unknown): value is PersistBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return Object.values(PERSIST_OPS).every((name) => typeof binding[name] === 'function');
}
