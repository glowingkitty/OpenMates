// frontend/packages/ui/src/services/db/chatRowTypes.ts
// Types of the chat-row decisions answered by the Worker persist unit (no logic).

export type ChatRowRecord = Record<string, unknown>;

export interface DraftFieldsInput {
  encrypted_draft_md?: string | null;
  encrypted_draft_preview?: string | null;
  draft_v?: number;
  cleared_draft_v?: number;
  ideabucket?: unknown;
  ideabucket_processing_window_id?: unknown;
  updated_at?: number;
}

export type DraftMergeAction = "none" | "abort" | "keep" | "put";

export interface DraftMergeRow {
  chat_id?: string;
  team_id?: string | null;
  draft_v?: number | null;
  cleared_draft_v?: number | null;
  updated_at?: number | null;
}

export interface TeamDraftRow {
  team_id?: string | null;
  team_draft_pending_sync?: string | null;
  encrypted_draft_md?: string | null;
  draft_v?: number | null;
  cleared_draft_v?: number | null;
}

export interface TeamDraftExpectation {
  kind: "update" | "delete";
  cipher?: string | null;
  version?: number;
  clearedDraftVersion?: number;
}

export interface ChatRowDefaultsInput {
  draft_v?: number | null; title_v?: number | null; messages_v?: number | null;
  last_edited_overall_timestamp?: number | null; updated_at?: number | null; created_at?: number | null;
}

export interface ChatRowDefaults {
  draft_v: number; title_v: number; messages_v: number; last_edited_overall_timestamp: number;
}

export interface DraftMergeDecision {
  action: DraftMergeAction; patch: ChatRowRecord; undefinedKeys: string[];
}

export interface TeamDraftDecision {
  apply: boolean; patch: ChatRowRecord; undefinedKeys: string[];
}
