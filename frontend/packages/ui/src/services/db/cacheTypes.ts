// frontend/packages/ui/src/services/db/cacheTypes.ts
// Types of the IndexedDB cache decisions answered by the Worker persist unit (no logic).

export const MESSAGE_WINDOW_PAGE_CACHE_GENERATION = 1;

export type WindowDirection = "latest" | "before" | "after" | "around";

export type WindowPageKind = "normal" | "forgotten";

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

export type BudgetAfterAction = "stop_max" | "need_usage" | "continue" | "stop_under_target";

export type QuotaAction = "rethrow" | "trim_retry" | "notify_throw";
