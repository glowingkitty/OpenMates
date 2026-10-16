/**
 * Records a submission failure after encrypted preflight and socket dispatch.
 * Keeps the original message identity and ciphertext for offline reconnect.
 * Separates transport loss from connected validation or serialization errors.
 * Emits the authoritative local status without exposing message content.
 */
import type { Message } from "../types/chat";
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";

/** Retain the original encrypted row for reconnect after a lost dispatch. */
export async function recordMessageDispatchFailure(
  eventTarget: EventTarget,
  message: Message,
  attemptedTransport: boolean,
): Promise<"waiting_for_internet" | "failed" | null> {
  // A mismatched ID must never modify a row belonging to another chat.
  const stored = await chatDB.getMessage(message.message_id);
  if (stored && stored.chat_id !== message.chat_id) {
    console.warn("[ChatSyncService:Senders] Dispatch failure found message in another chat", {
      messageId: message.message_id,
      expectedChatId: message.chat_id,
      storedChatId: stored.chat_id,
    });
    return null;
  }

  // sendMessage can also reject during serialization while the socket is live.
  // Only a lost connection should enter the automatic reconnect queue.
  const disconnected = attemptedTransport && !webSocketService.isConnected();
  const status = disconnected ? "waiting_for_internet" : "failed";
  await chatDB.updateMessageStatus(message.message_id, status);
  eventTarget.dispatchEvent(new CustomEvent("messageStatusChanged", {
    detail: { chatId: message.chat_id, messageId: message.message_id, status },
  }));
  if (disconnected) webSocketService.forceReconnect("chat message dispatch failed");
  return status;
}
