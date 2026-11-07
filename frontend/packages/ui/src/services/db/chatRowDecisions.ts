// frontend/packages/ui/src/services/db/chatRowDecisions.ts
// Async decision interface of the `chats` store rows. Flag off: the pure
// TypeScript policy (chatRowPolicy.ts). Flag on (VITE_OPENMATES_RUST_CORE): the
// shared Rust core Worker `persist` unit, with no TypeScript fallback. IndexedDB
// reads, writes and encryption stay with the callers.
import * as policy from "./chatRowPolicy";
import { RUST_PERSIST_BUILD } from "./cacheDecisions";

type Row = Record<string, unknown>;

export interface ChatRowDecisions {
  /** Answers may arrive after the caller left its IndexedDB transaction. */
  readonly deferred: boolean;
  chatDefaults(chat: Parameters<typeof policy.chatRowDefaults>[0], nowSeconds: number): Promise<ReturnType<typeof policy.chatRowDefaults>>;
  keylessDraftOnly(chat: Row, existing: Row | null): Promise<boolean>;
  candidateKeys(existing: string[] | null | undefined, blob: string): Promise<string[] | null>;
  draftMerge(input: {
    chatId: string;
    current: policy.DraftMergeRow | null;
    fields: policy.DraftFieldsInput;
    missingRow: policy.DraftMergeRow | null;
  }): Promise<ReturnType<typeof policy.mergeDraftFields>>;
  teamDraftIntent(input: {
    chat: policy.TeamDraftRow | null;
    teamId: string;
    pending: "update" | "delete" | undefined;
    expected?: policy.TeamDraftExpectation;
  }): Promise<ReturnType<typeof policy.applyTeamDraftIntent>>;
}

const tsDecisions: ChatRowDecisions = {
  deferred: false,
  chatDefaults: async (chat, now) => policy.chatRowDefaults(chat, now),
  keylessDraftOnly: async (chat, existing) => policy.isExpectedKeylessDraftOnlySyncChat(chat, existing),
  candidateKeys: async (existing, blob) => policy.nextCandidateKeys(existing, blob),
  draftMerge: async ({ chatId, current, fields, missingRow }) => policy.mergeDraftFields(chatId, current, fields, missingRow),
  teamDraftIntent: async ({ chat, teamId, pending, expected }) => policy.applyTeamDraftIntent(chat, teamId, pending, expected),
};

/** The decisions for this build; the Rust adapter loads lazily so default builds never bundle it. */
export async function chatRowDecisions(): Promise<ChatRowDecisions> {
  if (!RUST_PERSIST_BUILD) return tsDecisions;
  return (await import("../rustCore/persist/rustChatRowPolicy")).rustChatRowDecisions;
}
