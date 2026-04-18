/**
 * sendersMessageHighlights.ts — WebSocket senders for the message-highlights
 * annotation layer. Each op encrypts the semantic payload with the chat key
 * client-side, persists it to IndexedDB locally (so the UI is responsive
 * without round-trip), then fires the WS op for cross-device sync.
 *
 * See plans/when-a-user-is-fuzzy-turing.md for the per-row E2EE rationale.
 */
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import {
  encryptHighlightPayload,
} from "./encryption/MessageEncryptor";
import {
  upsertHighlight as idbUpsertHighlight,
  deleteHighlightById as idbDeleteHighlight,
} from "./db/messageHighlights";
import {
  upsertHighlight as storeUpsertHighlight,
  removeHighlight as storeRemoveHighlight,
  markHighlightAsMine,
} from "../stores/messageHighlightsStore";
import type {
  MessageHighlight,
  MessageHighlightPayload,
} from "../types/chat";

/**
 * Build the ciphertext + row metadata for a highlight, persist locally, push
 * to the store, and send the add_message_highlight WS op.
 *
 * Throws only when the chat key is unavailable. All other errors (WS send,
 * IDB write) are logged and swallowed — the local store stays authoritative.
 */
export async function sendAddMessageHighlightImpl(
  highlight: MessageHighlight,
): Promise<void> {
  const chatKey = chatKeyManager.getKeySync(highlight.chat_id)
    ?? (await chatKeyManager.getKey(highlight.chat_id));
  if (!chatKey) {
    throw new Error(
      `[sendersMessageHighlights] No chat key for chat ${highlight.chat_id} — cannot encrypt highlight`,
    );
  }

  const payload: MessageHighlightPayload = {
    kind: highlight.kind,
    anchor: highlight.kind === "text" ? highlight.anchor : undefined,
    embed_id: highlight.kind === "embed" ? highlight.embed_id : undefined,
    comment: highlight.comment,
    author_display_name: highlight.author_display_name,
    created_at: highlight.created_at,
  };

  const encrypted_payload = await encryptHighlightPayload(
    payload as unknown as Record<string, unknown>,
    chatKey,
  );

  // Optimistic local persistence
  storeUpsertHighlight(highlight);
  markHighlightAsMine(highlight.id);
  try {
    await idbUpsertHighlight(chatDB, highlight);
  } catch (e) {
    console.error("[sendersMessageHighlights] IDB upsert failed", e);
  }

  try {
    await webSocketService.sendMessage("add_message_highlight", {
      chat_id: highlight.chat_id,
      message_id: highlight.message_id,
      id: highlight.id,
      author_user_id: highlight.author_user_id,
      key_version: highlight.key_version ?? null,
      encrypted_payload,
      created_at: highlight.created_at,
    });
  } catch (e) {
    console.error("[sendersMessageHighlights] WS add failed", e);
  }
}

/**
 * Update the comment (or any semantic field) on an existing highlight.
 */
export async function sendUpdateMessageHighlightImpl(
  highlight: MessageHighlight,
): Promise<void> {
  const chatKey = chatKeyManager.getKeySync(highlight.chat_id)
    ?? (await chatKeyManager.getKey(highlight.chat_id));
  if (!chatKey) {
    throw new Error(
      `[sendersMessageHighlights] No chat key for chat ${highlight.chat_id}`,
    );
  }

  const now = Math.floor(Date.now() / 1000);
  const merged: MessageHighlight = { ...highlight, updated_at: now };

  const payload: MessageHighlightPayload = {
    kind: merged.kind,
    anchor: merged.kind === "text" ? merged.anchor : undefined,
    embed_id: merged.kind === "embed" ? merged.embed_id : undefined,
    comment: merged.comment,
    author_display_name: merged.author_display_name,
    created_at: merged.created_at,
    updated_at: now,
  };

  const encrypted_payload = await encryptHighlightPayload(
    payload as unknown as Record<string, unknown>,
    chatKey,
  );

  storeUpsertHighlight(merged);
  try {
    await idbUpsertHighlight(chatDB, merged);
  } catch (e) {
    console.error("[sendersMessageHighlights] IDB update failed", e);
  }

  try {
    await webSocketService.sendMessage("update_message_highlight", {
      chat_id: merged.chat_id,
      message_id: merged.message_id,
      id: merged.id,
      encrypted_payload,
      updated_at: now,
    });
  } catch (e) {
    console.error("[sendersMessageHighlights] WS update failed", e);
  }
}

export async function sendRemoveMessageHighlightImpl(
  chat_id: string,
  message_id: string,
  id: string,
): Promise<void> {
  storeRemoveHighlight(chat_id, message_id, id);
  try {
    await idbDeleteHighlight(chatDB, id);
  } catch (e) {
    console.error("[sendersMessageHighlights] IDB delete failed", e);
  }
  try {
    await webSocketService.sendMessage("remove_message_highlight", {
      chat_id,
      message_id,
      id,
    });
  } catch (e) {
    console.error("[sendersMessageHighlights] WS remove failed", e);
  }
}
