// frontend/packages/ui/src/services/db/cacheDecisions.ts
// Async decision interface of the IndexedDB cache layer. Flag off: the pure
// TypeScript policy (cachePolicy.ts, messageRowPolicy.ts). Flag on
// (VITE_OPENMATES_RUST_CORE): the shared Rust core Worker `persist` unit, with
// no TypeScript fallback (measurement-only opt-out `openmates_rust_core_persist`
// = 'ts'). IndexedDB reads, writes and encryption stay with the callers.
import type { Message } from "../../types/chat";
import * as policy from "./cachePolicy";
import { isSafeToEvictMessage } from "./messageRowPolicy";

export interface CacheDecisions {
  /** Decisions may be answered after the caller left its IndexedDB transaction. */
  readonly deferred: boolean;
  windowPlan(input: policy.WindowPlanInput): Promise<policy.WindowPlan>;
  windowResultMeta(input: policy.WindowResultMetaInput): Promise<policy.WindowResultMeta>;
  windowPageRecord(input: policy.WindowPageRecordInput): Promise<policy.WindowPageRecord>;
  evictPlan(input: policy.EvictPlanInput): Promise<{ deleteCount: number; candidates: string[] }>;
  evictDeletePlan(input: {
    pages: policy.CachePage[];
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
  budgetCandidates(pages: policy.CachePage[]): Promise<Array<{ id: string; chat_id: string }>>;
  budgetChatStep(normalPageCount: number): Promise<{ skip: boolean; maxPagesPerChat: number }>;
  budgetAfter(input: {
    force: boolean; removed: number; target: number; usage?: number | null;
  }): Promise<policy.BudgetAfterAction>;
  quotaStep(input: {
    stage: "write" | "retry"; canRetry: boolean; errorName: string | null;
  }): Promise<policy.QuotaAction>;
  chatsPageSize(limit: number): Promise<number>;
}

const tsDecisions: CacheDecisions = {
  deferred: false,
  windowPlan: async (input) => policy.planMessageWindow(input),
  windowResultMeta: async (input) => policy.windowResultMeta(input),
  windowPageRecord: async (input) => policy.buildWindowPageRecord(input),
  evictPlan: async (input) => policy.planPageEviction(input),
  evictDeletePlan: async (input) => policy.planPageDeletion(input),
  pageConfirmed: async (messages) => messages.every((message) => isSafeToEvictMessage(message)),
  isSafeToEvict: async (message) => isSafeToEvictMessage(message),
  budgetThrottled: async (input) => policy.budgetCheckThrottled(input),
  budgetTarget: async (input) => policy.budgetTarget(input),
  budgetCandidates: async (pages) => policy.budgetCandidates(pages),
  budgetChatStep: async (normalPageCount) => policy.budgetChatStep({ normalPageCount }),
  budgetAfter: async (input) => policy.budgetAfterEviction(input),
  quotaStep: async (input) => policy.quotaStep(input),
  chatsPageSize: async (limit) => policy.chatsPageSize(limit),
};

/** Opt-in shared Rust core build; the measurement-only opt-out keeps the TypeScript policy. */
export const RUST_PERSIST_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1"
  && !(typeof localStorage !== "undefined" && localStorage.getItem("openmates_rust_core_persist") === "ts");

/** The decisions for this build; the Rust adapter loads lazily so default builds never bundle it. */
export async function cacheDecisions(): Promise<CacheDecisions> {
  if (!RUST_PERSIST_BUILD) return tsDecisions;
  return (await import("../rustCore/persist/rustCachePolicy")).rustCacheDecisions;
}
