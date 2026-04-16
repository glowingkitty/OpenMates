/**
 * handlersMessageHighlights.ts — receive-side handlers for the 3 highlight
 * WS events (add / update / remove). Decrypts the payload with the chat key,
 * writes through IndexedDB, and updates the in-memory messageHighlightsStore.
 */
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptHighlightPayload } from "./encryption/MessageEncryptor";
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

async function decryptInto(
  chat_id: string,
  message_id: string,
  id: string,
  author_user_id: string,
  encrypted_payload: string,
  created_at: number,
  updated_at?: number,
  key_version?: number | null,
): Promise<MessageHighlight | null> {
  const chatKey = chatKeyManager.getKeySync(chat_id)
    ?? (await chatKeyManager.getKey(chat_id));
  if (!chatKey) {
    console.warn(
      `[handlersMessageHighlights] no chat key for chat ${chat_id} — dropping highlight ${id}`,
    );
    return null;
  }
  const plain = await decryptHighlightPayload(encrypted_payload, chatKey, {
    chatId: chat_id,
    messageId: message_id,
  });
  if (!plain) return null;

  const kind = plain["kind"] as "text" | "embed";
  if (kind === "text") {
    const start = typeof plain["start"] === "number" ? (plain["start"] as number) : undefined;
    const end = typeof plain["end"] === "number" ? (plain["end"] as number) : undefined;
    if (start === undefined || end === undefined) return null;
    return {
      id,
      kind: "text",
      chat_id,
      message_id,
      start,
      end,
      author_user_id,
      author_display_name:
        typeof plain["author_display_name"] === "string"
          ? (plain["author_display_name"] as string)
          : undefined,
      comment:
        typeof plain["comment"] === "string" && (plain["comment"] as string).trim()
          ? (plain["comment"] as string)
          : undefined,
      created_at,
      updated_at,
      key_version: key_version ?? null,
    };
  }
  if (kind === "embed") {
    const embed_id = typeof plain["embed_id"] === "string" ? (plain["embed_id"] as string) : undefined;
    if (!embed_id) return null;
    return {
      id,
      kind: "embed",
      chat_id,
      message_id,
      embed_id,
      author_user_id,
      author_display_name:
        typeof plain["author_display_name"] === "string"
          ? (plain["author_display_name"] as string)
          : undefined,
      comment:
        typeof plain["comment"] === "string" && (plain["comment"] as string).trim()
          ? (plain["comment"] as string)
          : undefined,
      created_at,
      updated_at,
      key_version: key_version ?? null,
    };
  }
  return null;
}

export async function handleMessageHighlightAddedImpl(
  payload: unknown,
): Promise<void> {
  const p = payload as MessageHighlightAddedPayload;
  const h = await decryptInto(
    p.chat_id,
    p.message_id,
    p.id,
    p.author_user_id,
    p.encrypted_payload,
    p.created_at,
    p.created_at,
    p.key_version ?? null,
  );
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
  const author_user_id = cached?.author_user_id ?? "";
  const created_at = cached?.created_at ?? p.updated_at;
  const h = await decryptInto(
    p.chat_id,
    p.message_id,
    p.id,
    author_user_id,
    p.encrypted_payload,
    created_at,
    p.updated_at,
    cached?.key_version ?? null,
  );
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
