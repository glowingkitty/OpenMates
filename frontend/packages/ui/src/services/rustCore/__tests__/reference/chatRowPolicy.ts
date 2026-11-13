// frontend/packages/ui/src/services/db/chatRowPolicy.ts
// Pure row decisions of the `chats` IndexedDB store (chatCrudOperations.ts):
// stored defaults, the keyless draft-only sync shell, candidate-key bookkeeping
// and the draft-field / Team draft-intent merges that run under a write lock.
// No IndexedDB, no stores: rows in, decision out. This is the flag-off
// implementation and the source of the TS-generated parity vectors of
// packages/openmates-rust/src/web_persist/chat_policy.rs, which serves the same
// decisions on the shared Worker `persist` unit when VITE_OPENMATES_RUST_CORE is on.

type Row = Record<string, unknown>;

/** Maximum candidate keys stored per chat. */
export const MAX_CANDIDATE_KEYS = 5;

/** Version counters and sort timestamp every stored chat row carries. */
export function chatRowDefaults(
  chat: { draft_v?: number | null; title_v?: number | null; messages_v?: number | null;
    last_edited_overall_timestamp?: number | null; updated_at?: number | null; created_at?: number | null },
  nowSeconds: number,
): { draft_v: number; title_v: number; messages_v: number; last_edited_overall_timestamp: number } {
  return {
    draft_v: chat.draft_v ?? 0,
    title_v: chat.title_v ?? 0,
    messages_v: chat.messages_v ?? 0,
    last_edited_overall_timestamp:
      chat.last_edited_overall_timestamp ?? chat.updated_at ?? chat.created_at ?? nowSeconds,
  };
}

/**
 * A new draft-only shell has no chat key or messages yet and its draft is master
 * key encrypted; a real chat must retain the missing-key guard.
 */
export function isExpectedKeylessDraftOnlySyncChat(chat: Row, existingChat: Row | null): boolean {
  return !chat.team_id && !chat.chat_visibility &&
    !chat.is_anonymous && !chat.anonymous_encrypted_chat_key &&
    !chat.is_shared && !chat.is_shared_by_others &&
    !chat.encrypted_chat_key && !chat.encrypted_title &&
    chat.messages_v === 0 && ((chat.draft_v as number | undefined) ?? 0) > 0 &&
    !!chat.encrypted_draft_md && chat.encrypted_draft_md !== "null" &&
    (!existingChat || (
      !existingChat.encrypted_chat_key && !existingChat.encrypted_title &&
      !existingChat.team_id && !existingChat.chat_visibility &&
      existingChat.messages_v === 0
    ));
}

/** The candidate key list after remembering `blob`; null when it is already stored. */
export function nextCandidateKeys(existing: string[] | null | undefined, blob: string): string[] | null {
  const current = existing ?? [];
  if (current.includes(blob)) return null;
  return [...current, blob].slice(-MAX_CANDIDATE_KEYS);
}

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

const DRAFT_ASSIGN_KEYS = ["encrypted_draft_md", "encrypted_draft_preview", "draft_v",
  "ideabucket", "ideabucket_processing_window_id"] as const;

/**
 * Merge draft fields into the latest chat row. `none`: nothing to write (no row
 * and no seed); `abort`: the seed row does not match; `keep`: the stored draft is
 * newer, keep it; `put`: assign `patch` over the base row (keys in
 * `undefinedKeys` are assigned `undefined`).
 */
export function mergeDraftFields(
  chatId: string,
  current: DraftMergeRow | null,
  fields: DraftFieldsInput,
  missingRow: DraftMergeRow | null,
): { action: DraftMergeAction; patch: Row; undefinedKeys: string[] } {
  const none = { patch: {}, undefinedKeys: [] as string[] };
  if (!current && !missingRow) return { action: "none", ...none };
  if (missingRow && (missingRow.chat_id !== chatId ||
      (current && (current.team_id ?? null) !== (missingRow.team_id ?? null)))) {
    return { action: "abort", ...none };
  }
  const base = (current ?? missingRow)!;
  const clearsCurrentDraft = fields.encrypted_draft_md === null && fields.draft_v === 0 &&
    (fields.cleared_draft_v ?? -1) >= (base.draft_v ?? 0);
  if (current && !clearsCurrentDraft && fields.draft_v !== undefined &&
      (fields.draft_v < (current.draft_v ?? 0) ||
        (fields.encrypted_draft_md != null && fields.draft_v <= (current.cleared_draft_v ?? -1)))) {
    return { action: "keep", ...none };
  }
  const patch: Row = {};
  const undefinedKeys: string[] = [];
  for (const key of DRAFT_ASSIGN_KEYS) {
    if (Object.prototype.hasOwnProperty.call(fields, key)) {
      if (fields[key] === undefined) undefinedKeys.push(key);
      else patch[key] = fields[key];
    }
  }
  if (fields.cleared_draft_v !== undefined) patch.cleared_draft_v = Math.max(base.cleared_draft_v ?? 0, fields.cleared_draft_v);
  if (fields.updated_at !== undefined) patch.updated_at = Math.max(base.updated_at ?? 0, fields.updated_at);
  return { action: "put", patch, undefinedKeys };
}

/** Assigns a merge decision's patch onto `row` (keys in `undefinedKeys` become `undefined`). */
export function applyRowPatch<T extends object>(
  row: T,
  decision: { patch: Record<string, unknown>; undefinedKeys: string[] },
): T {
  Object.assign(row, decision.patch);
  for (const key of decision.undefinedKeys) (row as Record<string, unknown>)[key] = undefined;
  return row;
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

/** Whether a Team draft intent may be recorded on the stored row, and the fields to set. */
export function applyTeamDraftIntent(
  chat: TeamDraftRow | null,
  teamId: string,
  pending: "update" | "delete" | undefined,
  expected?: TeamDraftExpectation,
): { apply: boolean; patch: Row; undefinedKeys: string[] } {
  const refuse = { apply: false, patch: {}, undefinedKeys: [] as string[] };
  if (!chat || chat.team_id !== teamId) return refuse;
  if (expected && (chat.team_draft_pending_sync !== expected.kind ||
      (expected.cipher !== undefined && chat.encrypted_draft_md !== expected.cipher) ||
      (expected.version !== undefined && (chat.draft_v ?? 0) !== expected.version))) {
    return refuse;
  }
  const patch: Row = {};
  const undefinedKeys: string[] = [];
  if (pending === undefined) undefinedKeys.push("team_draft_pending_sync");
  else patch.team_draft_pending_sync = pending;
  if (expected?.clearedDraftVersion !== undefined) {
    patch.cleared_draft_v = Math.max(chat.cleared_draft_v ?? 0, expected.clearedDraftVersion);
  }
  return { apply: true, patch, undefinedKeys };
}
