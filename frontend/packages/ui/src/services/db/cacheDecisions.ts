// frontend/packages/ui/src/services/db/cacheDecisions.ts
// Async decision interface of the IndexedDB cache layer. Every decision (window,
// eviction, budget, quota, page size) is answered by the shared Rust core Worker
// `persist` unit; there is no TypeScript policy, flag or opt-out. IndexedDB reads,
// writes and encryption stay with the callers.
import type { Message } from "../../types/chat";
import type {
  BudgetAfterAction, CachePage, EvictPlanInput, QuotaAction, WindowPageRecord,
  WindowPageRecordInput, WindowPlan, WindowPlanInput, WindowResultMeta, WindowResultMetaInput,
} from "./cacheTypes";

export interface CacheDecisions {
  /** Decisions may be answered after the caller left its IndexedDB transaction. */
  readonly deferred: true;
  windowPlan(input: WindowPlanInput): Promise<WindowPlan>;
  windowResultMeta(input: WindowResultMetaInput): Promise<WindowResultMeta>;
  windowPageRecord(input: WindowPageRecordInput): Promise<WindowPageRecord>;
  evictPlan(input: EvictPlanInput): Promise<{ deleteCount: number; candidates: string[] }>;
  evictDeletePlan(input: {
    pages: CachePage[];
    deletingPageIds: string[];
    protectedMessageIds?: string[] | null;
  }): Promise<Array<{ pageId: string; messageIds: string[] }>>;
  /** Every message of a cached page is safe to evict (`undefined` is a missing row). */
  pageConfirmed(messages: Array<Message | undefined>): Promise<boolean>;
  isSafeToEvict(message: Message | undefined): Promise<boolean>;
  budgetThrottled(input: { force: boolean; now: number; lastCheckAt: number }): Promise<boolean>;
  budgetTarget(input: {
    force: boolean; configuredBytes: number; quota?: number | null; usage?: number | null;
  }): Promise<{ target: number; trim: boolean }>;
  budgetCandidates(pages: CachePage[]): Promise<Array<{ id: string; chat_id: string }>>;
  budgetChatStep(normalPageCount: number): Promise<{ skip: boolean; maxPagesPerChat: number }>;
  budgetAfter(input: {
    force: boolean; removed: number; target: number; usage?: number | null;
  }): Promise<BudgetAfterAction>;
  quotaStep(input: {
    stage: "write" | "retry"; canRetry: boolean; errorName: string | null;
  }): Promise<QuotaAction>;
  chatsPageSize(limit: number): Promise<number>;
}

/** The decisions: the Rust adapter, loaded lazily so the Worker client is not bundled eagerly. */
export async function cacheDecisions(): Promise<CacheDecisions> {
  return (await import("../rustCore/persist/rustCachePolicy")).rustCacheDecisions;
}
