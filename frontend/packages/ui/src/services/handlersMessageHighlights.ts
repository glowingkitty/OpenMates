/**
 * handlersMessageHighlights.ts — receive-side handlers for the 3 highlight
 * WS events (add / update / remove). Decrypts the payload with the chat key,
 * writes through IndexedDB, and updates the in-memory messageHighlightsStore.
 */
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import {
  upsertHighlight as idbUpsertHighlight,
  deleteHighlightById as idbDeleteHighlight,
} from "./db/messageHighlights";
import {
  upsertHighlight as storeUpsertHighlight,
  removeHighlight as storeRemoveHighlight,
} from "../stores/messageHighlightsStore";
import type {
  MessageHighlight,
  MessageHighlightAddedPayload,
  MessageHighlightRemovedPayload,
  MessageHighlightUpdatedPayload,
} from "../types/chat";

// The shared Rust chatState unit decrypts and maps inbound highlight payloads;
// there is no TypeScript fallback.

/**
 * KEYS-04: use withKey() so decrypt is buffered until the key is resident in
 * memory (see decryptInto). Null when no key can be made resident.
 */
async function residentChatKey(chat_id: string, id: string): Promise<Uint8Array | null> {
  let chatKey: Uint8Array | null = null;
  try {
    await chatKeyManager.withKey(chat_id, "decrypt-highlight", async (key) => {
      chatKey = key;
    });
  } catch {
    console.warn(
      `[handlersMessageHighlights] no chat key for chat ${chat_id} — dropping highlight ${id}`,
    );
    return null;
  }
  return chatKey;
}

/** Inbound decode: Rust decrypts and maps the payload; a drop reason is logged like the web client. */
async function rustDecodeInto(
  kind: "added" | "updated",
  p: MessageHighlightAddedPayload | MessageHighlightUpdatedPayload,
  cached: MessageHighlight | null,
): Promise<MessageHighlight | null> {
  const chatKey = await residentChatKey(p.chat_id, p.id);
  if (!chatKey) return null;
  const rust = await import("./rustCore/chatState/rustHighlights");
  const out = kind === "added"
    ? await rust.rustDecodeHighlightAdded(p, chatKey)
    : await rust.rustDecodeHighlightUpdated(p, chatKey, cached);
  if ("store" in out) return out.store;
  if (out.drop !== "undecryptable") {
    console.warn(`[handlersMessageHighlights] dropping highlight ${p.id} — ${out.drop}`);
  }
  return null;
}

export async function handleMessageHighlightAddedImpl(
  payload: unknown,
): Promise<void> {
  const p = payload as MessageHighlightAddedPayload;
  const h = await rustDecodeInto("added", p, null);
  if (!h) return;
  storeUpsertHighlight(h);
  try {
    await idbUpsertHighlight(chatDB, h);
  } catch (e) {
    console.error("[handlersMessageHighlights] IDB upsert failed", e);
  }
}

export async function handleMessageHighlightUpdatedImpl(
  payload: unknown,
): Promise<void> {
  const p = payload as MessageHighlightUpdatedPayload;
  // We don't know author_user_id or created_at from the update payload; merge
  // with the cached row if present. If not cached (edge case — first-time sync
  // landed update before add), we still store minimal info.
  const { getHighlightsForMessage } = await import("./db/messageHighlights");
  const cached = (await getHighlightsForMessage(chatDB, p.chat_id, p.message_id))
    .find((h) => h.id === p.id);
  const h = await rustDecodeInto("updated", p, cached ?? null);
  if (!h) return;
  storeUpsertHighlight(h);
  try {
    await idbUpsertHighlight(chatDB, h);
  } catch (e) {
    console.error("[handlersMessageHighlights] IDB update failed", e);
  }
}

export async function handleMessageHighlightRemovedImpl(
  payload: unknown,
): Promise<void> {
  const p = payload as MessageHighlightRemovedPayload;
  storeRemoveHighlight(p.chat_id, p.message_id, p.id);
  try {
    await idbDeleteHighlight(chatDB, p.id);
  } catch (e) {
    console.error("[handlersMessageHighlights] IDB delete failed", e);
  }
}
