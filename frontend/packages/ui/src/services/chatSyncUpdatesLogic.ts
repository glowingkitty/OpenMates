// frontend/packages/ui/src/services/chatSyncUpdatesLogic.ts
// Pure decision helpers of the chat-update and recovery handlers, extracted from
// chatSyncServiceHandlersChatUpdates.ts and chatSyncServiceHandlersRecovery.ts so
// the flag-off TypeScript path and the vector generator share one definition.
// With VITE_OPENMATES_RUST_CORE=1 the handlers ask the shared Rust Worker `sync`
// unit instead (packages/openmates-rust/src/web_sync/updates.rs, proven against
// these functions by web_sync/updates_ts_vectors.json). No imports besides types:
// the module must load in plain Node for the vector generator.
import type { Message } from "../types/chat";

/** Longest notification preview in UTF-16 units, before the `...` suffix. */
export const MESSAGE_PREVIEW_MAX_LENGTH = 120;

/** Notification preview of an assistant reply: markdown stripped, one line, bounded. */
export function messagePreview(content: string | undefined): string {
  const plainText = (content || "")
    .replace(/#{1,6}\s+/g, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`{1,3}[^`]*`{1,3}/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "")
    .replace(/>\s+/g, "")
    .replace(/[-*+]\s+/g, "")
    .replace(/\n+/g, " ")
    .trim();

  if (!plainText) return "New AI response ready";
  return plainText.length > MESSAGE_PREVIEW_MAX_LENGTH
    ? `${plainText.substring(0, MESSAGE_PREVIEW_MAX_LENGTH)}...`
    : plainText;
}

const THINKING_KEYS = ["thinking_content", "thinking_signature"] as const;

// Only observed thinking fields cross the sealed-recovery boundary. Plaintext
// content/signatures are passed to getEncryptedFields, never to the server.
export function recoveredThinkingFields(payload: Record<string, unknown>): Partial<Message> {
  const fields: Partial<Message> = {};
  for (const key of THINKING_KEYS) {
    if (payload[key] !== undefined) {
      if (typeof payload[key] !== "string") throw new Error("Recovery thinking content was invalid.");
      fields[key] = payload[key];
    }
  }
  if (payload.has_thinking !== undefined) {
    if (typeof payload.has_thinking !== "boolean") throw new Error("Recovery thinking flag was invalid.");
    fields.has_thinking = payload.has_thinking;
  }
  if (payload.thinking_token_count !== undefined) {
    if (!Number.isSafeInteger(payload.thinking_token_count) || (payload.thinking_token_count as number) < 0) {
      throw new Error("Recovery thinking token count was invalid.");
    }
    fields.thinking_token_count = payload.thinking_token_count as number;
  }
  return fields;
}

/** Error text of each Rust refusal code of `thinkingFields` (same texts as `recoveredThinkingFields`). */
export const THINKING_FIELD_ERRORS = {
  content: "Recovery thinking content was invalid.",
  flag: "Recovery thinking flag was invalid.",
  count: "Recovery thinking token count was invalid.",
} as const;

/**
 * The part of a recovered payload that decides thinking-field validity. Strings
 * (possibly large plaintext) are replaced by `""` so only their type crosses to
 * the Worker; numbers and booleans are sent as they are, anything else as `{}`.
 */
export function thinkingFieldsRequest(payload: Record<string, unknown>): Record<string, unknown> {
  const request: Record<string, unknown> = {};
  for (const key of [...THINKING_KEYS, "has_thinking", "thinking_token_count"]) {
    const value = payload[key];
    if (value === undefined) continue;
    request[key] = typeof value === "string" ? "" : value === null || typeof value === "boolean" || typeof value === "number" ? value : {};
  }
  return request;
}
