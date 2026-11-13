// frontend/packages/ui/src/services/db/chatRowDecisions.ts
// Async decision interface of the `chats` store rows, answered by the shared Rust
// core Worker `persist` unit; there is no TypeScript policy, flag or opt-out.
// IndexedDB reads, writes and encryption stay with the callers.
import type {
  ChatRowDefaults, ChatRowDefaultsInput, ChatRowRecord, DraftFieldsInput, DraftMergeDecision,
  DraftMergeRow, TeamDraftDecision, TeamDraftExpectation, TeamDraftRow,
} from "./chatRowTypes";

export interface ChatRowDecisions {
  /** Answers arrive after the caller left its IndexedDB transaction. */
  readonly deferred: true;
  chatDefaults(chat: ChatRowDefaultsInput, nowSeconds: number): Promise<ChatRowDefaults>;
  keylessDraftOnly(chat: ChatRowRecord, existing: ChatRowRecord | null): Promise<boolean>;
  candidateKeys(existing: string[] | null | undefined, blob: string): Promise<string[] | null>;
  draftMerge(input: {
    chatId: string;
    current: DraftMergeRow | null;
    fields: DraftFieldsInput;
    missingRow: DraftMergeRow | null;
  }): Promise<DraftMergeDecision>;
  teamDraftIntent(input: {
    chat: TeamDraftRow | null;
    teamId: string;
    pending: "update" | "delete" | undefined;
    expected?: TeamDraftExpectation;
  }): Promise<TeamDraftDecision>;
}

/** The decisions: the Rust adapter, loaded lazily so the Worker client is not bundled eagerly. */
export async function chatRowDecisions(): Promise<ChatRowDecisions> {
  return (await import("../rustCore/persist/rustChatRowPolicy")).rustChatRowDecisions;
}
