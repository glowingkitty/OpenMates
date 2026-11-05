/**
 * Maps one Rust saved-chat read (decrypted by the shared Rust core) to the
 * existing TypeScript chat `Message` rows and message-window result, so the
 * unchanged ChatHistory/ChatMessage UI renders Rust-owned history.
 *
 * Parity target: `normalizeServerMessage` (server window rows) plus the
 * decrypted fields the IndexedDB path fills in. Shapes this mapper cannot
 * represent faithfully are refused with a fixed code, never coerced.
 */
import type { Message, MessageStatus, PIIMapping } from "../../types/chat";
import type { MessageWindowResult } from "../db/messageOperations";
import type { LocalChatReadback, SavedChatReadback, SavedReadCursor } from "./savedReadProtocol";

/** Fixed refusal codes. Log these only; never content or identifiers. */
export type RustHistoryRefusalCode =
  | "team_chat" | "shared_chat" | "unsynced_chat" | "unsupported_view"
  | "unsupported_role" | "unsupported_message_status" | "unsupported_queue_state"
  | "unsupported_pii_mapping" | "anchor_not_found";

/** Explicit, typed "Rust does not own this chat shape": the only TS fallback. */
export class RustHistoryRefusal extends Error {
  readonly code: RustHistoryRefusalCode;
  constructor(code: RustHistoryRefusalCode) { super(code); this.name = "RustHistoryRefusal"; this.code = code; }
}

const ROLES = new Set(["user", "assistant", "system"]);
// Stored states that keep a meaning in a saved (server) read. In-flight transport
// states describe a turn of another client; the server window path shows them as
// synced too (normalizeServerMessage), so this keeps TS parity.
const KEPT_STATUS = new Set<MessageStatus>(["queued", "waiting_for_user", "failed"]);
const SYNCED_STATUS = new Set<string>(["synced", "delivered", "sending", "streaming", "processing", "waiting_for_internet", "waiting_for_upload"]);
const QUEUE_MODES = new Set(["follow_up", "steer"]);
const QUEUE_DISPATCH = new Set(["queued", "processing", "paused"]);

function status(raw: string | null): MessageStatus {
  if (raw === null || SYNCED_STATUS.has(raw)) return "synced";
  if (KEPT_STATUS.has(raw as MessageStatus)) return raw as MessageStatus;
  throw new RustHistoryRefusal("unsupported_message_status");
}

function piiMappings(values: unknown[] | undefined): PIIMapping[] | undefined {
  if (!values || values.length === 0) return undefined;
  return values.map((value) => {
    const row = value as Record<string, unknown> | null;
    if (!row || typeof row !== "object" || typeof row.placeholder !== "string"
      || typeof row.original !== "string" || typeof row.type !== "string") throw new RustHistoryRefusal("unsupported_pii_mapping");
    return { placeholder: row.placeholder, original: row.original, type: row.type };
  });
}

type DecryptedRows = Pick<SavedChatReadback, "chat" | "messageMetadata" | "piiMappingsByMessageId">;

/** Rust page rows -> TS `Message` rows, in Rust's canonical order. */
export function savedReadToMessages(read: DecryptedRows, chatId: string): Message[] {
  if (read.chat.id !== chatId) throw new Error("protocol");
  return read.chat.messages.map((message, index) => {
    const meta = read.messageMetadata[index];
    if (!meta || meta.id !== message.id || meta.chatId !== chatId) throw new Error("protocol");
    if (!ROLES.has(message.role)) throw new RustHistoryRefusal("unsupported_role");
    if ((meta.queueMode !== null && !QUEUE_MODES.has(meta.queueMode))
      || (meta.queueDispatchMode !== null && !QUEUE_MODES.has(meta.queueDispatchMode))
      || (meta.queueDispatchStatus !== null && !QUEUE_DISPATCH.has(meta.queueDispatchStatus))) throw new RustHistoryRefusal("unsupported_queue_state");
    const row: Message = {
      message_id: message.id,
      chat_id: chatId,
      role: message.role as Message["role"],
      created_at: meta.createdAt,
      status: status(meta.rawStatus),
      content: message.content,
    };
    const sender = message.sender || meta.senderName;
    if (sender) row.sender_name = sender;
    if (meta.category !== null) row.category = meta.category;
    if (meta.modelName !== null) row.model_name = meta.modelName;
    if (message.thinking) row.thinking_content = message.thinking;
    if (meta.thinkingSignature !== null) row.thinking_signature = meta.thinkingSignature;
    if (meta.hasThinking !== null) row.has_thinking = meta.hasThinking;
    if (meta.thinkingTokenCount !== null) row.thinking_token_count = meta.thinkingTokenCount;
    if (meta.hashedUserId !== null) row.hashed_user_id = meta.hashedUserId;
    if (meta.userMessageId !== null) row.user_message_id = meta.userMessageId;
    if (meta.clientMessageId !== null) row.client_message_id = meta.clientMessageId;
    if (meta.keyVersion !== null) row.key_version = meta.keyVersion;
    if (meta.queueRevision !== null) row.queue_revision = meta.queueRevision;
    if (meta.queueMode !== null) row.queue_mode = meta.queueMode as Message["queue_mode"];
    if (meta.queueDispatchStatus !== null) row.queue_dispatch_status = meta.queueDispatchStatus as Message["queue_dispatch_status"];
    if (meta.queueDispatchMode !== null) row.queue_dispatch_mode = meta.queueDispatchMode as Message["queue_dispatch_mode"];
    if (meta.queueDispatchTaskId !== null) row.queue_dispatch_task_id = meta.queueDispatchTaskId;
    const pii = piiMappings(read.piiMappingsByMessageId[message.id]);
    if (pii) row.pii_mappings = pii;
    return row;
  });
}

function cursorTime(cursor: SavedReadCursor | null): number | null { return cursor ? cursor.createdAt : null; }

/**
 * Rust cache-first page (existing retained IndexedDB rows decrypted in the Rust
 * Worker) -> the same window shape. Same row mapper as the server read, so the
 * rendered rows are identical; unknown retained boundaries read as "no more".
 */
export function localReadToMessageWindow(read: LocalChatReadback, chatId: string, anchored: boolean): MessageWindowResult {
  if (!read.messageMetadata || !read.piiMappingsByMessageId) throw new Error("protocol");
  if (anchored && !read.anchorFound) throw new RustHistoryRefusal("anchor_not_found");
  return {
    messages: savedReadToMessages({ chat: read.chat, messageMetadata: read.messageMetadata, piiMappingsByMessageId: read.piiMappingsByMessageId }, chatId),
    hasMoreBefore: read.hasMoreBefore ?? false,
    hasMoreAfter: read.hasMoreAfter ?? false,
    startCursor: cursorTime(read.startCursor),
    startCursorMessageId: read.startCursor?.messageId ?? null,
    endCursor: cursorTime(read.endCursor),
    endCursorMessageId: read.endCursor?.messageId ?? null,
    anchorFound: anchored ? read.anchorFound : true,
  };
}

/** Rust page -> the `MessageWindowResult` ActiveChat already consumes. */
export function savedReadToMessageWindow(read: SavedChatReadback, chatId: string, anchored: boolean): MessageWindowResult {
  if (anchored && !read.anchorFound) throw new RustHistoryRefusal("anchor_not_found");
  return {
    messages: savedReadToMessages(read, chatId),
    hasMoreBefore: read.hasMoreBefore,
    hasMoreAfter: read.hasMoreAfter,
    startCursor: cursorTime(read.startCursor),
    startCursorMessageId: read.startCursor?.messageId ?? null,
    endCursor: cursorTime(read.endCursor),
    endCursorMessageId: read.endCursor?.messageId ?? null,
    anchorFound: anchored ? read.anchorFound : true,
  };
}
