/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) cache decisions: the page adapter over the
 * shared Rust core Worker `persist` unit for the message-window cache, the
 * offline cache budget and quota recovery. Loaded only through
 * db/cacheDecisions.ts, so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_persist/cache_policy.rs) decides; the page
 * keeps every IndexedDB read and write and sends only the fields a decision reads.
 * There is no TypeScript fallback: a refused call rejects with its fixed code.
 *
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */
import type { Message } from '../../../types/chat';
import type { CacheDecisions } from '../../db/cacheDecisions';
import type { CachePage } from '../../db/cachePolicy';
import { persistCall } from './persistUnitClient';
import { pickFields } from './rustMessageRowPolicy';

const EVICT_FIELDS = [
	'status', 'pending_turn_preflight_v1', 'pending_encrypted_turn_preflight_v1', 'pending_encrypted_embed_bundle_v1',
] as const;

function pagesPayload(pages: CachePage[]): CachePage[] {
	return pages.map((page) => ({
		id: page.id, chat_id: page.chat_id, page_kind: page.page_kind,
		last_accessed_at: page.last_accessed_at, message_ids: page.message_ids,
		cache_generation: page.cache_generation,
	}));
}

const rows = (messages: Array<Message | undefined>): Array<Message | null> =>
	messages.map((message) => (message ? pickFields(message, EVICT_FIELDS) : null));

export const rustCacheDecisions: CacheDecisions = {
	deferred: true,
	windowPlan: (input) => persistCall('windowPlan', input),
	windowResultMeta: (input) => persistCall('windowResultMeta', input),
	windowPageRecord: (input) => persistCall('windowPageRecord', input),
	evictPlan: (input) => persistCall('evictPlan', { ...input, pages: pagesPayload(input.pages) }),
	evictDeletePlan: async (input) => (await persistCall('evictDeletePlan', { ...input, pages: pagesPayload(input.pages) })).plan,
	pageConfirmed: async (messages) => (await persistCall('pageConfirmed', { messages: rows(messages) })).confirmed,
	isSafeToEvict: async (message) => (await persistCall('messageSafeToEvict', { messages: rows([message]) })).results[0],
	budgetThrottled: async (input) => (await persistCall('budgetThrottle', input)).throttled,
	budgetTarget: (input) => persistCall('budgetTarget', input),
	budgetCandidates: async (pages) => (await persistCall('budgetCandidates', { pages: pagesPayload(pages) })).pages,
	budgetChatStep: (normalPageCount) => persistCall('budgetChatStep', { normalPageCount }),
	budgetAfter: async (input) => (await persistCall('budgetAfter', input)).action,
	quotaStep: async (input) => (await persistCall('quotaStep', input)).action,
	chatsPageSize: async (limit) => (await persistCall('chatsPageSize', { limit })).size,
};
