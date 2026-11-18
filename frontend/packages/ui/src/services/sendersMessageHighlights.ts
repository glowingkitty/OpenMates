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
  upsertHighlight as idbUpsertHighlight,
  deleteHighlightById as idbDeleteHighlight,
} from "./db/messageHighlights";
import {
  upsertHighlight as storeUpsertHighlight,
  removeHighlight as storeRemoveHighlight,
  markHighlightAsMine,
} from "../stores/messageHighlightsStore";
import type { MessageHighlight } from "../types/chat";

// The shared Rust chatState unit builds and decodes the encrypted highlight payloads;
// there is no TypeScript fallback.

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

  const write = await (await import("./rustCore/chatState/rustHighlights")).rustAddHighlight(highlight, chatKey);
  await persistAndSend(write.record ?? highlight, write.type, write.payload, true);
}

/** Tail of add/update: optimistic store + IndexedDB write, then the Rust-built socket frame. */
async function persistAndSend(
  row: MessageHighlight,
  type: string,
  payload: Record<string, unknown>,
  mine: boolean,
): Promise<void> {
  storeUpsertHighlight(row);
  if (mine) markHighlightAsMine(row.id);
  try {
    await idbUpsertHighlight(chatDB, row);
  } catch (e) {
    console.error("[sendersMessageHighlights] IDB write failed", e);
  }
  try {
    await webSocketService.sendMessage(type, payload);
  } catch (e) {
    console.error("[sendersMessageHighlights] WS send failed", e);
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
  const write = await (await import("./rustCore/chatState/rustHighlights")).rustUpdateHighlight(highlight, chatKey, now);
  await persistAndSend(write.record ?? { ...highlight, updated_at: now }, write.type, write.payload, false);
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
    const frame = await (await import("./rustCore/chatState/rustHighlights")).rustRemoveHighlight(chat_id, message_id, id);
    await webSocketService.sendMessage(frame.type, frame.payload);
  } catch (e) {
    console.error("[sendersMessageHighlights] WS remove failed", e);
  }
}
