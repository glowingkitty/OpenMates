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
  HighlightAnchor,
  MessageHighlight,
  MessageHighlightAddedPayload,
  MessageHighlightRemovedPayload,
  MessageHighlightUpdatedPayload,
} from "../types/chat";

// Opt-in shared Rust core (build-time VITE_OPENMATES_RUST_CORE === "1"): the chatState unit decrypts
// and maps inbound highlight payloads; no TypeScript fallback. Default builds keep the code below.
const RUST_HIGHLIGHTS: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1"
  && !(typeof localStorage !== "undefined" && localStorage.getItem("openmates_rust_core_chatstate") === "ts");

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

/** Flag-on inbound decode: Rust decrypts and maps the payload; a drop reason is logged like the web client. */
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
  // KEYS-04: use withKey() so decrypt is buffered until the key is resident in
  // memory — getKeySync()/getKey() returns null during async IDB unwrap on
  // secondary devices, silently dropping highlights received during phased sync.
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
  if (!chatKey) return null;
  const plain = await decryptHighlightPayload(encrypted_payload, chatKey, {
    chatId: chat_id,
    messageId: message_id,
  });
  if (!plain) return null;

  const kind = plain["kind"] as "text" | "embed";
  if (kind === "text") {
    const anchorRaw = plain["anchor"] as Record<string, unknown> | undefined;
    let anchor: HighlightAnchor | null = null;
    if (anchorRaw && typeof anchorRaw["exact"] === "string") {
      anchor = {
        exact: String(anchorRaw["exact"]),
        prefix: typeof anchorRaw["prefix"] === "string" ? String(anchorRaw["prefix"]) : "",
        suffix: typeof anchorRaw["suffix"] === "string" ? String(anchorRaw["suffix"]) : "",
      };
    }
    if (!anchor) {
      console.warn(
        `[handlersMessageHighlights] dropping text highlight ${id} — no anchor in payload (legacy offset-only row?)`,
      );
      return null;
    }
    return {
      id,
      kind: "text",
      chat_id,
      message_id,
      anchor,
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
  const h = RUST_HIGHLIGHTS ? await rustDecodeInto("added", p, null) : await decryptInto(
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
  const h = RUST_HIGHLIGHTS ? await rustDecodeInto("updated", p, cached ?? null) : await decryptInto(
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
