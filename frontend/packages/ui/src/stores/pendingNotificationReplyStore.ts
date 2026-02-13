// frontend/packages/ui/src/stores/pendingNotificationReplyStore.ts
/**
 * @file pendingNotificationReplyStore.ts
 * @description Simple store for passing a reply message from a chat notification
 * to the chat input. When a user types a reply in a notification and hits send,
 * the text is stored here and the app navigates to the chat. The chat input
 * component picks up the pending reply and populates the editor with it.
 */
import { writable, get } from "svelte/store";

interface PendingReply {
  chatId: string;
  text: string;
}

const store = writable<PendingReply | null>(null);

export const pendingNotificationReplyStore = {
  subscribe: store.subscribe,

  /**
   * Set a pending reply to be picked up by the chat input
   * @param chatId The chat to reply in
   * @param text The reply text
   */
  set: (chatId: string, text: string) => {
    store.set({ chatId, text });
  },

  /**
   * Consume the pending reply (returns and clears it)
   * Called by the chat input when it picks up the reply
   * @param chatId Only consume if it matches the given chat ID
   * @returns The pending reply text, or null if none
   */
  consume: (chatId: string): string | null => {
    const pending = get(store);
    if (pending && pending.chatId === chatId) {
      store.set(null);
      return pending.text;
    }
    return null;
  },

  /** Clear any pending reply */
  clear: () => {
    store.set(null);
  },
};
