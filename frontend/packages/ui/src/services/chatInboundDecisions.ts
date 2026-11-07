// frontend/packages/ui/src/services/chatInboundDecisions.ts
// Small pure decision of inbound chat updates, extracted from
// chatSyncServiceHandlersChatUpdates.ts and chatSyncServiceHandlersCoreSync.ts.
// Default builds run the TypeScript below; the opt-in shared Rust core build
// (VITE_OPENMATES_RUST_CORE) answers the same decisions from the shared Worker
// `sync` unit (web_sync/inbound.rs) with no TypeScript fallback.
import type { Chat } from "../types/chat";
import { RUST_UPDATES_POLICY } from "./chatSyncUpdatesPolicy";

const RUST_SYNC_BUILD = RUST_UPDATES_POLICY;

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
