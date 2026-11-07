// frontend/packages/ui/src/services/db/cachePolicy.ts
// Pure decisions of the message-window cache, the offline cache budget and the
// quota-recovery retry flow. No IndexedDB, no browser globals: callers pass facts
// in and act on the answer. This is the flag-off implementation and the source
// of the TS-generated parity vectors of packages/openmates-rust/src/web_persist/
// cache_policy.rs, which serves the same decisions on the shared Worker
// `persist` unit when VITE_OPENMATES_RUST_CORE is on.

export type WindowDirection = "latest" | "before" | "after" | "around";
export type WindowPageKind = "normal" | "forgotten";

export const DEFAULT_MESSAGE_WINDOW_LIMIT = 30;
export const MAX_MESSAGE_WINDOW_LIMIT = 100;
export const MESSAGE_WINDOW_PAGE_CACHE_GENERATION = 1;
export const DEFAULT_MESSAGE_WINDOW_PAGE_CACHE_LIMIT = 12;
export const MAX_BUDGET_EVICTIONS = 32;
export const BUDGET_CHECK_INTERVAL_MS = 30_000;

export function clampWindowLimit(limit?: number | null): number {
  if (!Number.isFinite(limit) || !limit || limit < 1) {
    return DEFAULT_MESSAGE_WINDOW_LIMIT;
  }
  return Math.min(Math.floor(limit), MAX_MESSAGE_WINDOW_LIMIT);
}

export interface WindowPlanInput {
  chatId: string;
  direction?: WindowDirection | null;
  limit?: number | null;
  anchorMessageId?: string | null;
  anchorCreatedAt?: number | null;
  beforeTimestamp?: number | null;
  afterTimestamp?: number | null;
  compressedUpToTimestamp?: number | null;
  /** The stored anchor row (only its chat and time matter), when it was read. */
  anchorRecord?: { chat_id: string; created_at?: number | null } | null;
}

export interface WindowPlan {
  limit: number;
  direction: WindowDirection;
  /** The page must read the anchor row, then plan again with `anchorRecord`. */
  needsAnchorRead: boolean;
  /** The request names no usable cursor: answer an empty, anchor-less window. */
  empty: boolean;
  /** The anchor row belongs to this chat and is part of an `around` window. */
  keepAnchor: boolean;
  anchorCreatedAt: number | null;
  beforeLimit: number;
  afterLimit: number;
  /** Cursor timestamp of a `before`/`after` window. */
  timestamp: number | null;
  /** Lower range bound; null is -Infinity. */
  lowerBound: number | null;
  lowerOpen: boolean;
  anchorFound: boolean;
}

const orNull = (value: number | null | undefined): number | null => value ?? null;

export function planMessageWindow(input: WindowPlanInput): WindowPlan {
  const limit = clampWindowLimit(input.limit);
  const direction = input.direction ?? "latest";
  const needsAnchorRead = direction === "around" && !!input.anchorMessageId;
  const anchorRecord = input.anchorRecord && input.anchorRecord.chat_id === input.chatId
    ? input.anchorRecord : null;
  const lowerBound = orNull(input.compressedUpToTimestamp);
  const lowerOpen = !!input.compressedUpToTimestamp;
  const plan: WindowPlan = {
    limit, direction, needsAnchorRead, empty: false, keepAnchor: false,
    anchorCreatedAt: null, beforeLimit: 0, afterLimit: 0, timestamp: null,
    lowerBound, lowerOpen, anchorFound: true,
  };
  if (direction === "around") {
    const anchorCreatedAt = anchorRecord?.created_at ?? input.anchorCreatedAt;
    if (!anchorCreatedAt) return { ...plan, empty: true, anchorFound: false };
    const beforeLimit = Math.floor((limit - 1) / 2);
    return {
      ...plan,
      keepAnchor: !!anchorRecord,
      anchorCreatedAt,
      beforeLimit,
      afterLimit: limit - 1 - beforeLimit,
      anchorFound: !!anchorRecord || !!input.anchorCreatedAt,
    };
  }
  if (direction === "before") {
    const timestamp = input.beforeTimestamp ?? input.anchorCreatedAt;
    if (!timestamp) return { ...plan, empty: true, anchorFound: false };
    return { ...plan, timestamp };
  }
  if (direction === "after") {
    const timestamp = input.afterTimestamp ?? input.anchorCreatedAt;
    if (!timestamp) return { ...plan, empty: true, anchorFound: false };
    return { ...plan, timestamp };
  }
  return plan;
}

export interface WindowCursorMessage {
  created_at?: number | null;
  message_id?: string | null;
}

export interface WindowResultMetaInput {
  direction: WindowDirection;
  /** `hasMore` of a before/after/latest window. */
  hasMore: boolean;
  beforeHasMore: boolean;
  afterHasMore: boolean;
  anchorFound: boolean;
  first: WindowCursorMessage | null;
  last: WindowCursorMessage | null;
}

export interface WindowResultMeta {
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  startCursor: number | null;
  startCursorMessageId: string | null;
  endCursor: number | null;
  endCursorMessageId: string | null;
  anchorFound: boolean;
}

export function windowResultMeta(input: WindowResultMetaInput): WindowResultMeta {
  let hasMoreBefore: boolean;
  let hasMoreAfter: boolean;
  if (input.direction === "around") {
    hasMoreBefore = input.beforeHasMore;
    hasMoreAfter = input.afterHasMore;
  } else if (input.direction === "before") {
    hasMoreBefore = input.hasMore;
    hasMoreAfter = true;
  } else if (input.direction === "after") {
    hasMoreBefore = true;
    hasMoreAfter = input.hasMore;
  } else {
    hasMoreBefore = input.hasMore;
    hasMoreAfter = false;
  }
  return {
    hasMoreBefore,
    hasMoreAfter,
    startCursor: input.first?.created_at ?? null,
    startCursorMessageId: input.first?.message_id ?? null,
    endCursor: input.last?.created_at ?? null,
    endCursorMessageId: input.last?.message_id ?? null,
    anchorFound: input.anchorFound,
  };
}

export interface WindowPageRecordInput {
  chatId: string;
  pageKind: WindowPageKind;
  direction: WindowDirection;
  result: {
    startCursor: number | null;
    startCursorMessageId: string | null;
    endCursor: number | null;
    endCursorMessageId: string | null;
    hasMoreBefore: boolean;
    hasMoreAfter: boolean;
  };
  messageIds: string[];
  existingCachedAt: number | null;
  now: number;
}

export interface WindowPageRecord {
  id: string;
  chat_id: string;
  page_kind: WindowPageKind;
  direction: WindowDirection;
  start_cursor: number | null;
  start_cursor_message_id: string | null;
  end_cursor: number | null;
  end_cursor_message_id: string | null;
  has_more_before: boolean;
  has_more_after: boolean;
  message_ids: string[];
  cached_at: number;
  last_accessed_at: number;
  cache_generation: number;
}

export function buildWindowPageRecord(input: WindowPageRecordInput): WindowPageRecord {
  const { result } = input;
  const id = [
    input.chatId,
    input.pageKind,
    input.direction,
    result.startCursor ?? "start",
    result.startCursorMessageId ?? "start-id",
    result.endCursor ?? "end",
    result.endCursorMessageId ?? "end-id",
    MESSAGE_WINDOW_PAGE_CACHE_GENERATION,
  ].join("|");
  return {
    id,
    chat_id: input.chatId,
    page_kind: input.pageKind,
    direction: input.direction,
    start_cursor: result.startCursor,
    start_cursor_message_id: result.startCursorMessageId,
    end_cursor: result.endCursor,
    end_cursor_message_id: result.endCursorMessageId,
    has_more_before: result.hasMoreBefore,
    has_more_after: result.hasMoreAfter,
    message_ids: input.messageIds,
    cached_at: input.existingCachedAt ?? input.now,
    last_accessed_at: input.now,
    cache_generation: MESSAGE_WINDOW_PAGE_CACHE_GENERATION,
  };
}

/** The page fields the eviction and budget decisions read. */
export interface CachePage {
  id: string;
  chat_id: string;
  page_kind: WindowPageKind;
  last_accessed_at: number;
  message_ids: string[];
  cache_generation?: number;
}

export interface EvictPlanInput {
  pages: CachePage[];
  maxPagesPerChat?: number | null;
  protectedPageIds?: string[] | null;
  protectedMessageIds?: string[] | null;
}

/**
 * Which normal pages may be evicted, oldest access first, and how many must go.
 * Candidates holding a protected message are skipped; the caller still has to
 * confirm that every message of a candidate is safe to evict.
 */
export function planPageEviction(input: EvictPlanInput): { deleteCount: number; candidates: string[] } {
  const maxPagesPerChat = Math.max(1, Math.floor(input.maxPagesPerChat ?? DEFAULT_MESSAGE_WINDOW_PAGE_CACHE_LIMIT));
  const protectedPageIds = new Set(input.protectedPageIds ?? []);
  const protectedMessageIds = new Set(input.protectedMessageIds ?? []);
  const normalPages = input.pages
    .filter((page) => page.page_kind === "normal" && !protectedPageIds.has(page.id))
    .sort((a, b) => a.last_accessed_at - b.last_accessed_at);
  const deleteCount = Math.max(0, input.pages.filter((page) => page.page_kind === "normal").length - maxPagesPerChat);
  const candidates = normalPages
    .filter((page) => !page.message_ids.some((id) => protectedMessageIds.has(id)))
    .map((page) => page.id);
  return { deleteCount, candidates };
}

/** Messages to attempt deleting per evicted page; retained and protected ones stay. */
export function planPageDeletion(input: {
  pages: CachePage[];
  deletingPageIds: string[];
  protectedMessageIds?: string[] | null;
}): Array<{ pageId: string; messageIds: string[] }> {
  const deleting = new Set(input.deletingPageIds);
  const protectedMessageIds = new Set(input.protectedMessageIds ?? []);
  const retained = new Set<string>();
  for (const page of input.pages) {
    if (deleting.has(page.id)) continue;
    for (const messageId of page.message_ids) retained.add(messageId);
  }
  return input.deletingPageIds.map((pageId) => {
    const page = input.pages.find((candidate) => candidate.id === pageId);
    return {
      pageId,
      messageIds: (page?.message_ids ?? []).filter((id) => !retained.has(id) && !protectedMessageIds.has(id)),
    };
  });
}

/** True when the 30 s budget check interval has not elapsed (and the check is not forced). */
export function budgetCheckThrottled(input: { force: boolean; now: number; lastCheckAt: number }): boolean {
  return !input.force && input.now - input.lastCheckAt < BUDGET_CHECK_INTERVAL_MS;
}

export function offlineCacheTargetBytes(configuredBytes: number, quota?: number | null): number {
  return quota && Number.isFinite(quota) && quota > 0
    ? Math.min(configuredBytes, Math.floor(quota / 2))
    : configuredBytes;
}

/** Target bytes and whether the usage estimate calls for trimming. */
export function budgetTarget(input: {
  force: boolean;
  configuredBytes: number;
  quota?: number | null;
  usage?: number | null;
}): { target: number; trim: boolean } {
  const target = offlineCacheTargetBytes(input.configuredBytes, input.quota);
  const skip = !input.force && (input.usage === undefined || input.usage === null || input.usage <= target);
  return { target, trim: !skip };
}

/** Pages the budget trim visits: current-generation normal pages, oldest first. */
export function budgetCandidates(pages: CachePage[]): Array<{ id: string; chat_id: string }> {
  return pages
    .filter((page) => page.page_kind === "normal" &&
      page.cache_generation === MESSAGE_WINDOW_PAGE_CACHE_GENERATION)
    .sort((a, b) => a.last_accessed_at - b.last_accessed_at)
    .map((page) => ({ id: page.id, chat_id: page.chat_id }));
}

/** Whether the chat has surplus normal pages, and how many it may keep. */
export function budgetChatStep(input: { normalPageCount: number }): { skip: boolean; maxPagesPerChat: number } {
  return { skip: input.normalPageCount <= 1, maxPagesPerChat: input.normalPageCount - 1 };
}

export type BudgetAfterAction = "stop_max" | "need_usage" | "continue" | "stop_under_target";

/** After an eviction: stop at the cap, ask for a usage estimate, or go on. */
export function budgetAfterEviction(input: {
  force: boolean;
  removed: number;
  usage?: number | null;
  target: number;
}): BudgetAfterAction {
  if (input.removed >= MAX_BUDGET_EVICTIONS) return "stop_max";
  if (input.force || input.removed % 4 !== 0) return "continue";
  if (input.usage === undefined) return "need_usage";
  return input.usage !== null && input.usage <= input.target ? "stop_under_target" : "continue";
}

export type QuotaAction = "rethrow" | "trim_retry" | "notify_throw";

/** Next step of the quota-recovery retry flow after a failed write. */
export function quotaStep(input: {
  stage: "write" | "retry";
  canRetry: boolean;
  errorName: string | null;
}): QuotaAction {
  if (input.errorName !== "QuotaExceededError") return "rethrow";
  return input.stage === "write" && input.canRetry ? "trim_retry" : "notify_throw";
}

export function chatsPageSize(limit: number): number {
  return Math.min(Math.max(limit, 1), 50);
}
