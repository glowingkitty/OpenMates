// frontend/packages/ui/src/services/chatSyncServiceHandlersWebhooks.ts
/**
 * WebSocket handler for incoming-webhook chats.
 *
 * Mirrors handleReminderFiredImpl in chatSyncServiceHandlersAppSettings.ts —
 * webhooks and reminders share the same "external trigger creates a new chat
 * with a system message" pattern, so they share the same client-side flow:
 *
 *   1. Receive `webhook_chat` event with PLAINTEXT content (the WS channel
 *      is already TLS- and session-authenticated; encrypting on top buys
 *      nothing).
 *   2. Generate a fresh chat key via ChatKeyManager.
 *   3. Encrypt the title + content with the chat key (zero-knowledge — the
 *      server only ever sees chat-key-encrypted bytes from this point on).
 *   4. Save the new chat + system message to IndexedDB.
 *   5. Send `chat_system_message_added` to the server so it can persist the
 *      chat-key-encrypted message to Directus.
 *   6. Dispatch a `chatUpdated` event so the sidebar/active chat refresh.
 *
 * The backend dispatches the AI ask-request server-side and unconditionally,
 * so the assistant response will arrive via the normal AI streaming events
 * regardless of whether this device is the one that received this WS event.
 *
 * Architecture: docs/architecture/webhooks.md
 */

import type { ChatSynchronizationService } from "./chatSyncService";
import { notificationStore } from "../stores/notificationStore";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { encryptWithChatKey } from "./encryption/MessageEncryptor";

/**
 * Payload structure for the webhook_chat WebSocket event.
 *
 * The backend (`backend/core/api/app/routers/webhooks.py::webhook_incoming`)
 * sends PLAINTEXT content. The webhook key's name is encrypted with the
 * user's master key server-side and cannot be decrypted by the backend, so
 * it is not included in the payload — the chat title falls back to a generic
 * label until the user renames the chat.
 */
interface WebhookChatPayload {
  chat_id: string;
  message_id: string;
  content: string; // PLAINTEXT message content
  status: "processing" | "pending_confirmation";
  source: "webhook";
  webhook_id: string;
  fired_at?: number; // Unix timestamp set by backend
}

const DEFAULT_WEBHOOK_CHAT_TITLE = "Webhook";

/**
 * Handles the "webhook_chat" WebSocket event when an external service triggers
 * a new chat via POST /v1/webhooks/incoming.
 *
 * See module docstring for the full flow rationale.
 */
export async function handleWebhookChatImpl(
  serviceInstance: ChatSynchronizationService,
  rawPayload: unknown,
): Promise<void> {
  const payload = rawPayload as WebhookChatPayload;

  console.info("[ChatSyncService:Webhook] Received 'webhook_chat':", {
    chat_id: payload?.chat_id,
    message_id: payload?.message_id,
    status: payload?.status,
  });

  if (!payload?.chat_id || !payload.message_id || !payload.content) {
    console.warn(
      "[ChatSyncService:Webhook] Invalid webhook_chat payload:",
      payload,
    );
    return;
  }

  const { chat_id, message_id, content, status } = payload;

  try {
    // Deduplicate: if the message already exists locally (e.g. user has two
    // tabs open and both received the same broadcast) skip it.
    const existingMessage = await chatDB.getMessage(message_id);
    if (existingMessage) {
      console.debug(
        `[ChatSyncService:Webhook] Message ${message_id} already exists locally, skipping duplicate`,
      );
      return;
    }

    // Use fired_at from the backend payload for correct ordering — if the
    // user was offline, fired_at predates the eventual delivery time and we
    // want the system message to sit BEFORE any AI response that the server
    // already produced.
    const firedAt = payload.fired_at || Math.floor(Date.now() / 1000);

    // Generate a chat key via the single source of truth (ChatKeyManager).
    const chatKey = chatKeyManager.createKeyForNewChat(chat_id);
    if (!chatKey) {
      console.error(
        "[ChatSyncService:Webhook] Failed to generate chat key for new webhook chat",
      );
      return;
    }

    // Encrypt the title and content with the new chat key.
    const titleText = DEFAULT_WEBHOOK_CHAT_TITLE;
    const encryptedTitle = await encryptWithChatKey(titleText, chatKey);
    const encryptedContent = await encryptWithChatKey(content, chatKey);

    if (!encryptedContent) {
      console.error(
        "[ChatSyncService:Webhook] Failed to encrypt webhook content with chat key",
      );
      return;
    }

    const newChat = {
      chat_id,
      title: titleText,
      encrypted_title: encryptedTitle,
      created_at: firedAt,
      updated_at: firedAt,
      messages_v: 0,
      title_v: 0,
      last_edited_overall_timestamp: firedAt,
      unread_count: 1,
    };

    await chatDB.updateChat(newChat as import("../types/chat").Chat);
    console.info(
      `[ChatSyncService:Webhook] Created local chat ${chat_id} for incoming webhook`,
    );

    const systemMessage = {
      message_id,
      chat_id,
      role: "system" as const,
      content, // Plaintext for local rendering
      created_at: firedAt,
      status: "sending" as const,
      encrypted_content: encryptedContent,
    };

    await chatDB.saveMessage(systemMessage);
    console.debug(
      `[ChatSyncService:Webhook] Saved webhook system message ${message_id} to IndexedDB`,
    );

    // Send the encrypted content to the server for persistence via the same
    // path reminders use (`chat_system_message_added` → system_message_handler
    // → persist_new_chat_message Celery task).
    const { webSocketService } = await import("./websocketService");
    const serverPayload = {
      chat_id,
      message: {
        message_id,
        role: "system",
        encrypted_content: encryptedContent,
        created_at: firedAt,
      },
    };

    try {
      await webSocketService.sendMessage(
        "chat_system_message_added",
        serverPayload,
      );
      const syncedMessage = { ...systemMessage, status: "synced" as const };
      await chatDB.saveMessage(syncedMessage);
      console.debug(
        `[ChatSyncService:Webhook] Sent webhook system message ${message_id} to server for persistence`,
      );
    } catch (sendError) {
      console.error(
        "[ChatSyncService:Webhook] Error sending webhook message to server:",
        sendError,
      );
      // Local copy is saved; will sync later via normal retry path.
    }

    // Refresh the UI: surface the new chat in the sidebar and let the active
    // chat view pick it up immediately.
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id,
          type: "webhook_system_message_added",
          newMessage: systemMessage,
          messagesUpdated: true,
          chat: newChat,
        },
      }),
    );

    // Toast notification — same UX as a reminder firing.
    const previewText = content.length > 100
      ? `${content.substring(0, 100)}…`
      : content;
    const toastTitle =
      status === "pending_confirmation"
        ? "Webhook chat awaiting approval"
        : "Webhook started a new chat";
    notificationStore.chatMessage(
      chat_id,
      toastTitle,
      previewText,
      undefined,
      undefined,
    );

    console.info(
      `[ChatSyncService:Webhook] Processed webhook chat ${chat_id} (status=${status})`,
    );
  } catch (error) {
    console.error(
      "[ChatSyncService:Webhook] Error handling webhook_chat:",
      error,
    );
  }
}
