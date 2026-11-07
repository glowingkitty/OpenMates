// frontend/packages/ui/src/services/chatInboundDecisions.ts
// Small pure decision of inbound chat updates, extracted from
// chatSyncServiceHandlersChatUpdates.ts and chatSyncServiceHandlersCoreSync.ts.
// Default builds run the TypeScript below; the opt-in shared Rust core build
// (VITE_OPENMATES_RUST_CORE) answers the same decisions from the shared Worker
// `sync` unit (web_sync/inbound.rs) with no TypeScript fallback.
import type { Chat } from "../types/chat";
import { RUST_UPDATES_POLICY } from "./chatSyncUpdatesPolicy";
import { isDraftUpdateBlockedByLocalDeletion } from "./chatSyncMerge";

const RUST_SYNC_BUILD = RUST_UPDATES_POLICY;

/** First failed admission check of a title/draft frame (null: admitted). */
export type InboundFrameInvalid = "chat_id" | "data" | "versions" | null;

function inboundOps() {
  return import("./rustCore/sync/inboundOps");
}

/** Drops the draft of a draft-only shell once its first message version arrives; returns the same object otherwise. */
export async function clearDraftOnlyShellForMessages(chat: Chat, messagesV: number): Promise<Chat> {
  const clear = RUST_SYNC_BUILD
    ? (await (await inboundOps()).draftShell(chat, messagesV)).clear
    : !(messagesV <= 0 || (chat.messages_v || 0) !== 0 || !(chat.encrypted_draft_md || chat.encrypted_draft_preview));
  if (!clear) return chat;
  return { ...chat, encrypted_draft_md: null, encrypted_draft_preview: null, draft_v: 0 };
}

/** Builds the Rust-decided update frames only in the shared Rust core build. */
export const INBOUND_FRAMES_IN_RUST = RUST_SYNC_BUILD;

/** Flag-off admission checks of `chat_title_updated` / `chat_draft_updated`, in handler order. */
export function updateFrameInvalidTs(
  kind: "title" | "draft",
  payload: { chat_id?: string; data?: Record<string, unknown>; versions?: Record<string, unknown> } | null | undefined,
): InboundFrameInvalid {
  const [dataKey, versionKey] = kind === "title" ? ["encrypted_title", "title_v"] : ["encrypted_draft_md", "draft_v"];
  if (!payload || !payload.chat_id) return "chat_id";
  if (!payload.data || payload.data[dataKey] === undefined) return "data";
  if (!payload.versions || payload.versions[versionKey] === undefined) return "versions";
  return null;
}

/** Rust admission of the same frames (shared Worker `sync` unit; no TypeScript fallback). */
export async function updateFrameInvalidRust(
  kind: "title" | "draft",
  payload: { chat_id?: string; data?: Record<string, unknown>; versions?: Record<string, unknown> } | null | undefined,
): Promise<InboundFrameInvalid> {
  const dataKey = kind === "title" ? "encrypted_title" : "encrypted_draft_md";
  const versionKey = kind === "title" ? "title_v" : "draft_v";
  const slim = payload ? {
    chat_id: payload.chat_id,
    data: payload.data ? { [dataKey]: payload.data[dataKey] } : payload.data,
    versions: payload.versions ? { [versionKey]: payload.versions[versionKey] } : payload.versions,
  } : payload;
  return (await (await inboundOps()).updateFrame(kind, slim)).invalid;
}

/** Flag-off stale check and draft-deletion cleared version of `chat_draft_updated` against an existing chat. */
export function draftApplyTs(local: Chat, incomingDraftV: number, deletion: boolean): { stale: boolean; clearedDraftV: number | null } {
  if ((local.draft_v ?? 0) > incomingDraftV || isDraftUpdateBlockedByLocalDeletion(local, incomingDraftV)) {
    return { stale: true, clearedDraftV: null };
  }
  return {
    stale: false,
    clearedDraftV: deletion ? Math.max(local.cleared_draft_v ?? 0, local.draft_v ?? 0, incomingDraftV) : null,
  };
}

/** Rust stale check and cleared version of the same decision. */
export async function draftApplyRust(local: Chat, incomingDraftV: number, deletion: boolean) {
  return (await inboundOps()).draftApply(local, incomingDraftV, deletion);
}
