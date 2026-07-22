// frontend/packages/ui/src/services/chatNotificationVisibility.ts
/**
 * Shared visibility guard for chat-message notifications.
 *
 * Chat notifications should only appear for chats that are not currently visible.
 * The URL hash is the visible source of truth when present because store updates
 * can lag during chat navigation and websocket event handling.
 */
import { activeChatStore } from "../stores/activeChatStore";

export function getVisibleHashChatId(): string | null {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!hash) return null;
  const params = new URLSearchParams(hash);
  return params.get("chat-id") ?? params.get("chat_id");
}

export function isChatVisiblyActive(chatId: string): boolean {
  const visibleHashChatId = getVisibleHashChatId();
  if (visibleHashChatId !== null) return visibleHashChatId === chatId;
  return activeChatStore.get() === chatId;
}
