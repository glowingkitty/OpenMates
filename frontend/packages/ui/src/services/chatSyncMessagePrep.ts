// frontend/packages/ui/src/services/chatSyncMessagePrep.ts
// Storage preparation of synced messages, extracted verbatim from
// chatSyncServiceHandlersPhasedSync.ts (Phase 2/3 and background sync) and
// chatSyncServiceHandlersCoreSync.ts (Phase 1b and the on-demand content batch).
// Each loop parses the server's JSON strings, picks the message id, fills the
// chat id and derives the queued/processing status. Default builds run the
// TypeScript below; the opt-in shared Rust core build (VITE_OPENMATES_RUST_CORE)
// takes the id/chat/role fallbacks, skip and queue-classification decisions from
// the shared Worker `sync` unit (web_sync/message_prep.rs) through
// rustCore/sync/messagePrepOps.ts, with no TypeScript fallback.
import type { Message, MessageStatus } from "../types/chat";
import { clearQueuedProcessingForMessage, hasQueuedProcessing } from "./queuedMessageLifecycle";
import { RUST_UPDATES_POLICY } from "./chatSyncUpdatesPolicy";

/** The handlers await the Rust plans only in the shared Rust core build. */
export const MESSAGE_PREP_IN_RUST = RUST_UPDATES_POLICY;

export function messagePrepOps() {
  return import("./rustCore/sync/messagePrepOps");
}

/**
 * Prepare messages for storage - parses JSON strings and validates required fields
 */
export function prepareMessagesForStorage(
  messages: Message[],
  chatId: string,
  phaseName: string,
): Message[] {
  const preparedMessages: Message[] = [];

  if (!messages || !Array.isArray(messages)) {
    return preparedMessages;
  }

  for (const messageData of messages) {
    let message = messageData;

    // Parse JSON string if needed
    if (typeof messageData === "string") {
      try {
        message = JSON.parse(messageData);
        const messageId =
          message.message_id || (message as Message & { id?: string }).id;
        console.debug(
          `[ChatSyncService] ${phaseName} - Parsed message JSON string for message: ${messageId}`,
        );
      } catch (e) {
        console.error(
          `[ChatSyncService] ${phaseName} - Failed to parse message JSON for chat ${chatId}:`,
          e,
        );
        continue;
      }
    }

    // Use 'id' field as message_id if message_id is missing
    if (!message.message_id && (message as Message & { id?: string }).id) {
      message.message_id = (message as Message & { id?: string }).id;
    }

    // Skip messages without message_id
    if (!message.message_id) {
      console.error(
        `[ChatSyncService] ${phaseName} - Message missing message_id after parsing, skipping:`,
        message,
      );
      continue;
    }

    // Ensure chat_id is set
    if (!message.chat_id) {
      message.chat_id = chatId;
    }

    // Directus queue receipt is authoritative after reconnect or Redis loss.
    if (message.queue_dispatch_status === "paused") {
      clearQueuedProcessingForMessage(message.chat_id, message.message_id);
      message.status = "delivered";
      message.queue_mode = undefined;
    } else if (hasQueuedProcessing(message.chat_id, message.message_id) ||
        message.queue_dispatch_status === "processing") {
      message.status = "delivered";
      message.queue_mode = undefined;
      message.queue_dispatch_status = "processing";
    } else if (message.queue_dispatch_status === "queued" &&
        (message.queue_dispatch_mode === "follow_up" || message.queue_dispatch_mode === "steer")) {
      message.status = "queued";
      message.queue_mode = message.queue_dispatch_mode;
    } else if (!message.status) {
      message.status = "delivered";
    }

    preparedMessages.push(message);
  }

  return preparedMessages;
}

/** Background (new Phase 3) batch: parse JSON strings and normalize message_id. */
export function prepareBackgroundMessages(messages: (Message | string)[], chatId: string): Message[] {
  // Parse JSON strings and normalize message_id
  const preparedMessages: Message[] = [];
  for (const msgData of messages) {
    let msg = msgData;
    if (typeof msgData === "string") {
      try {
        msg = JSON.parse(msgData);
      } catch {
        continue;
      }
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- server rows are untyped JSON until normalized
    const msgObj = msg as any;
    if (!msgObj.message_id && msgObj.id) {
      msgObj.message_id = msgObj.id;
    }
    if (!msgObj.message_id) continue;
    if (!msgObj.chat_id) msgObj.chat_id = chatId;
    if (!msgObj.status) msgObj.status = "delivered";
    preparedMessages.push(msgObj as Message);
  }
  return preparedMessages;
}

/** Phase 1b content: parse JSON strings, normalize message_id and the queue receipt status. */
export function preparePhase1bMessages(messages: (Message | string)[], chatId: string): Message[] {
  const preparedMessages: Message[] = [];
  for (const msgData of messages) {
    let msg = msgData;
    if (typeof msgData === "string") {
      try {
        msg = JSON.parse(msgData);
      } catch {
        continue;
      }
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- server rows are untyped JSON until normalized
    const msgObj = msg as any;
    if (!msgObj.message_id && msgObj.id) {
      msgObj.message_id = msgObj.id;
    }
    if (!msgObj.message_id) continue;
    if (!msgObj.chat_id) msgObj.chat_id = chatId;
    if (msgObj.queue_dispatch_status === "paused") {
      clearQueuedProcessingForMessage(chatId, msgObj.message_id);
      msgObj.status = "delivered";
      msgObj.queue_mode = undefined;
    } else if (hasQueuedProcessing(chatId, msgObj.message_id) ||
        msgObj.queue_dispatch_status === "processing") {
      msgObj.status = "delivered";
      msgObj.queue_mode = undefined;
      msgObj.queue_dispatch_status = "processing";
    } else if (msgObj.queue_dispatch_status === "queued" &&
        (msgObj.queue_dispatch_mode === "follow_up" || msgObj.queue_dispatch_mode === "steer")) {
      msgObj.status = "queued";
      msgObj.queue_mode = msgObj.queue_dispatch_mode;
    } else if (!msgObj.status) msgObj.status = "delivered";
    preparedMessages.push(msgObj as Message);
  }
  return preparedMessages;
}

/** Copies the stored fields of one normalized on-demand batch message (no decision). */
export function batchMessageRecord(
  message: Record<string, unknown>,
  decided: Pick<Message, "message_id" | "chat_id" | "role" | "status" | "queue_mode" | "queue_dispatch_status">,
): Message {
  return {
    message_id: decided.message_id,
    chat_id: decided.chat_id,
    role: decided.role,
    hashed_user_id: message.hashed_user_id as string | undefined,
    created_at: message.created_at as number,
    status: decided.status,
    client_message_id: message.client_message_id as string | undefined,
    user_message_id: message.user_message_id as string | undefined,
    queue_revision: message.queue_revision as number | undefined,
    queue_mode: decided.queue_mode,
    queue_dispatch_status: decided.queue_dispatch_status,
    queue_dispatch_mode: message.queue_dispatch_mode as "follow_up" | "steer" | null | undefined,
    queue_dispatch_task_id: message.queue_dispatch_task_id as string | null | undefined,
    // Encrypted fields (zero-knowledge architecture)
    encrypted_content: message.encrypted_content as string,
    encrypted_sender_name: message.encrypted_sender_name as
      | string
      | undefined,
    encrypted_category: message.encrypted_category as string | undefined,
    encrypted_model_name: message.encrypted_model_name as
      | string
      | undefined,
    encrypted_thinking_content: message.encrypted_thinking_content as
      | string
      | undefined,
    encrypted_thinking_signature: message.encrypted_thinking_signature as
      | string
      | undefined,
    has_thinking: message.has_thinking as boolean | undefined,
    thinking_token_count: message.thinking_token_count as
      | number
      | undefined,
    // PII mappings for client-side restoration of anonymized data
    encrypted_pii_mappings: message.encrypted_pii_mappings as
      | string
      | undefined,
  };
}

/** On-demand `chat_content_batch_response` messages of one chat, normalized for storage. */
export function prepareBatchMessagesForStorage(rawMessages: unknown[], chatId: string): Message[] {
  // Parse messages — server sends JSON-serialized strings from sync cache/Directus
  // Same pattern as prepareMessagesForStorage in phased sync
  const preparedMessages: Message[] = [];
  for (const messageData of rawMessages) {
    let message: Record<string, unknown>;

    // Parse JSON string if needed (server sends JSON strings from sync cache)
    if (typeof messageData === "string") {
      try {
        message = JSON.parse(messageData);
      } catch (e) {
        console.error(
          `[ChatSyncService:CoreSync] Failed to parse message JSON for chat ${chatId}:`,
          e,
        );
        continue;
      }
    } else {
      message = messageData as unknown as Record<string, unknown>;
    }

    // Normalize message_id: use 'id' field as fallback (Directus UUID)
    const messageId = (message.message_id ||
      message.client_message_id ||
      message.id) as string | undefined;
    if (!messageId) {
      console.error(
        `[ChatSyncService:CoreSync] Message missing message_id after parsing, skipping:`,
        message,
      );
      continue;
    }

    if (message.queue_dispatch_status === "paused") {
      clearQueuedProcessingForMessage(chatId, messageId);
    }
    const hasProcessingFence = message.queue_dispatch_status !== "paused" &&
      hasQueuedProcessing(chatId, messageId);

    preparedMessages.push(batchMessageRecord(message, {
      message_id: messageId,
      chat_id: (message.chat_id as string) || chatId,
      role: (message.role as Message["role"]) || "user",
      status: hasProcessingFence ||
        message.queue_dispatch_status === "processing" || message.queue_dispatch_status === "paused"
        ? "delivered"
        : message.queue_dispatch_status === "queued" &&
        (message.queue_dispatch_mode === "follow_up" || message.queue_dispatch_mode === "steer")
          ? "queued"
            : (message.status as MessageStatus) || "delivered",
      queue_mode: !hasProcessingFence && message.queue_dispatch_status === "queued" &&
        (message.queue_dispatch_mode === "follow_up" || message.queue_dispatch_mode === "steer")
          ? message.queue_dispatch_mode : undefined,
      queue_dispatch_status: hasProcessingFence
        ? "processing" : message.queue_dispatch_status as "queued" | "processing" | "paused" | null | undefined,
    }));
  }
  return preparedMessages;
}
