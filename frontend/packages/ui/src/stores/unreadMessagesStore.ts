// frontend/packages/ui/src/stores/unreadMessagesStore.ts
/**
 * @file unreadMessagesStore.ts
 * @description Svelte store for tracking unread messages per chat.
 *
 * A finished assistant reply stays unread until its last line has been visible
 * in the user's viewport. The server owns the persisted count (incremented when
 * a reply is persisted, broadcast with the reply's message_id); this store mirrors
 * it and also counts background completions optimistically. Each reply is counted
 * at most once, whichever signal arrives first.
 *
 * Unread counts are cleared when:
 * 1. The last line of the chat's latest reply is visible (ActiveChat)
 * 2. The user sends a follow-up (a reply is assumed read once answered)
 * 3. The user marks the chat as read from the context menu
 * Opening a chat alone does NOT clear the count.
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

/** Replies already counted per chat, so local and server signals never double count. */
const countedReplyIds = new Map<string, Set<string>>();
const MAX_COUNTED_REPLY_IDS_PER_CHAT = 50;
/** Chats the user explicitly marked unread; visibility must not silently clear them. */
const manuallyUnreadChatIds = new Set<string>();

/** Returns false when this reply was already counted for the chat. */
function rememberCountedReply(chatId: string, messageId: string): boolean {
  let ids = countedReplyIds.get(chatId);
  if (!ids) {
    ids = new Set();
    countedReplyIds.set(chatId, ids);
  }
  if (ids.has(messageId)) return false;
  ids.add(messageId);
  if (ids.size > MAX_COUNTED_REPLY_IDS_PER_CHAT) {
    const oldest = ids.values().next().value;
    if (oldest !== undefined) ids.delete(oldest);
  }
  return true;
}

export const unreadMessagesStore = {
  subscribe,

  /**
   * Increment unread count for a chat
   * Called when an AI message completes for a background chat
   * @param chatId The chat ID
   * @param messageId The reply that became unread; repeated calls for it are ignored
   */
  incrementUnread: (chatId: string, messageId?: string) => {
    if (messageId && !rememberCountedReply(chatId, messageId)) return;
    update((state) => {
      const newCounts = new Map(state.unreadCounts);
      const currentCount = newCounts.get(chatId) || 0;
      newCounts.set(chatId, currentCount + 1);
      return { unreadCounts: newCounts };
    });
  },

  /**
   * Set unread count for a chat to a specific value.
   * Used by cross-device sync (chat_read_status_updated event) and phased sync
   * to reflect the server-authoritative unread count on this device.
   * @param chatId The chat ID
   * @param count The unread count to set (0 removes the entry)
   * @param messageId Reply the server counted, so a later local increment for it is ignored
   */
  setUnread: (chatId: string, count: number, messageId?: string) => {
    if (messageId) rememberCountedReply(chatId, messageId);
    update((state) => {
      const newCounts = new Map(state.unreadCounts);
      if (count <= 0) {
        newCounts.delete(chatId);
      } else {
        newCounts.set(chatId, count);
      }
      return { unreadCounts: newCounts };
    });
  },

  /**
   * Clear unread count for a chat
   * Called when user opens/views the chat
   * @param chatId The chat ID
   */
  clearUnread: (chatId: string) => {
    manuallyUnreadChatIds.delete(chatId);
    update((state) => {
      const newCounts = new Map(state.unreadCounts);
      newCounts.delete(chatId);
      return { unreadCounts: newCounts };
    });
  },

  /**
   * Mark a chat unread by explicit user action (context menu). The count is
   * exactly 1, and automatic "last line visible" read detection skips the chat
   * until the user leaves it or marks it read.
   */
  markManuallyUnread: (chatId: string) => {
    manuallyUnreadChatIds.add(chatId);
    update((state) => {
      const newCounts = new Map(state.unreadCounts);
      newCounts.set(chatId, 1);
      return { unreadCounts: newCounts };
    });
  },

  isManuallyUnread: (chatId: string): boolean => manuallyUnreadChatIds.has(chatId),

  /** Called when the user leaves a chat, so returning to it can mark it read again. */
  releaseManualUnread: (chatId: string) => {
    manuallyUnreadChatIds.delete(chatId);
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
    countedReplyIds.clear();
    manuallyUnreadChatIds.clear();
    update(() => ({ unreadCounts: new Map() }));
  },
};
