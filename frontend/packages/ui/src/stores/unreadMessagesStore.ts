// frontend/packages/ui/src/stores/unreadMessagesStore.ts
/**
 * @file unreadMessagesStore.ts
 * @description Svelte store for tracking unread messages per chat.
 *
 * Unread messages are tracked when:
 * 1. An AI response completes for a chat that is NOT the active chat
 * 2. The user has not viewed that chat since the message arrived
 *
 * Unread counts are cleared when:
 * 1. The user opens/views the chat
 * 2. The user responds to the notification
 */
import { writable, get } from "svelte/store";

export interface UnreadMessagesState {
  /** Map of chat_id -> unread message count */
  unreadCounts: Map<string, number>;
}

const initialState: UnreadMessagesState = {
  unreadCounts: new Map(),
};

// Create the writable store
const { subscribe, update } = writable<UnreadMessagesState>(initialState);

export const unreadMessagesStore = {
  subscribe,

  /**
   * Increment unread count for a chat
   * Called when an AI message completes for a background chat
   * @param chatId The chat ID
   */
  incrementUnread: (chatId: string) => {
    update((state) => {
      const newCounts = new Map(state.unreadCounts);
      const currentCount = newCounts.get(chatId) || 0;
      newCounts.set(chatId, currentCount + 1);
      return { unreadCounts: newCounts };
    });
  },

  /**
   * Clear unread count for a chat
   * Called when user opens/views the chat
   * @param chatId The chat ID
   */
  clearUnread: (chatId: string) => {
    update((state) => {
      const newCounts = new Map(state.unreadCounts);
      newCounts.delete(chatId);
      return { unreadCounts: newCounts };
    });
  },

  /**
   * Get unread count for a specific chat
   * @param chatId The chat ID
   * @returns The unread count (0 if none)
   */
  getUnreadCount: (chatId: string): number => {
    const state = get({ subscribe });
    return state.unreadCounts.get(chatId) || 0;
  },

  /**
   * Get total unread count across all chats
   * @returns Total unread messages
   */
  getTotalUnread: (): number => {
    const state = get({ subscribe });
    let total = 0;
    state.unreadCounts.forEach((count) => {
      total += count;
    });
    return total;
  },

  /**
   * Clear all unread counts
   */
  clearAll: () => {
    update(() => ({ unreadCounts: new Map() }));
  },
};

// Export convenience functions for direct access
export function getUnreadCountForChat(chatId: string): number {
  return unreadMessagesStore.getUnreadCount(chatId);
}

export function clearUnreadForChat(chatId: string): void {
  unreadMessagesStore.clearUnread(chatId);
}
