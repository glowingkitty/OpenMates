import { writable } from "svelte/store";

export interface AITypingStatus {
  isTyping: boolean;
  category: string | null; // Changed from mateName
  modelName?: string | null; // Added field for the AI model name
  providerName?: string | null; // Added field for the AI provider name
  serverRegion?: string | null; // Server region for UI display (e.g., "EU", "US", "APAC")
  chatId: string | null;
  userMessageId: string | null; // The user message that triggered the AI
  aiMessageId: string | null; // The AI's message UUID (set from payload.message_id in ai_typing_started)
  icon_names?: string[]; // Added field for Lucide icon names
}

const initialTypingStatus: AITypingStatus = {
  isTyping: false,
  category: null, // Changed from mateName
  modelName: null,
  providerName: null,
  serverRegion: null,
  chatId: null,
  userMessageId: null,
  aiMessageId: null,
};

const store = writable<AITypingStatus>(initialTypingStatus);
export const aiTypingByChatStore = writable<Record<string, AITypingStatus>>({});

export const aiTypingStore = {
  subscribe: store.subscribe,
  setTyping: (
    chatId: string,
    userMessageId: string,
    aiMessageId: string,
    category: string,
    modelName?: string | null,
    providerName?: string | null,
    serverRegion?: string | null,
    icon_names?: string[],
  ) => {
    // Changed mateName to category, added modelName, providerName, serverRegion and icon_names
    const status: AITypingStatus = {
      isTyping: true,
      category, // Changed from mateName
      modelName: modelName || null,
      providerName: providerName || null,
      serverRegion: serverRegion || null,
      chatId,
      userMessageId,
      aiMessageId,
      icon_names: icon_names || [],
    };
    aiTypingByChatStore.update(chats => ({ ...chats, [chatId]: status }));
    store.set(status);
  },
  clearTyping: (chatId: string, aiMessageId: string) => {
    aiTypingByChatStore.update(chats => {
      if (chats[chatId]?.aiMessageId !== aiMessageId) return chats;
      const next = { ...chats };
      delete next[chatId];
      return next;
    });
    // Clear typing if the chat and message ID match
    store.update((current) => {
      if (current.chatId === chatId && current.aiMessageId === aiMessageId) {
        console.debug(
          `[aiTypingStore] Clearing typing for chat ${chatId}, message ${aiMessageId}`,
        );
        return { ...initialTypingStatus };
      }
      console.debug(
        `[aiTypingStore] NOT clearing typing - current: ${current.chatId}/${current.aiMessageId}, requested: ${chatId}/${aiMessageId}`,
      );
      return current; // Don't clear if different chat or message
    });
  },
  /**
   * Clear typing when a terminal final ends the turn that is typing.
   * Typing is keyed to the running task id, while a resumed turn's final
   * carries the shared assistant message id; so a final ends typing when either
   * id matches or when it belongs to the same user message.
   */
  clearTypingForTurn: (
    chatId: string,
    ids: Array<string | null | undefined>,
    userMessageId?: string | null,
  ) => {
    const ends = (status: AITypingStatus | undefined) =>
      !!status && status.chatId === chatId && (
        ids.some((id) => !!id && id === status.aiMessageId)
        || (!!userMessageId && status.userMessageId === userMessageId)
      );
    aiTypingByChatStore.update(chats => {
      if (!ends(chats[chatId])) return chats;
      const next = { ...chats };
      delete next[chatId];
      return next;
    });
    store.update((current) => (ends(current) ? { ...initialTypingStatus } : current));
  },
  /**
   * Clear typing for a specific chat ID regardless of aiMessageId.
   * Used when cancelling tasks where we only have task_id, not message_id.
   * @param chatId - The chat ID to clear typing for
   */
  clearTypingForChat: (chatId: string) => {
    aiTypingByChatStore.update(chats => {
      const next = { ...chats };
      delete next[chatId];
      return next;
    });
    store.update((current) => {
      if (current.chatId === chatId) {
        console.debug(
          `[aiTypingStore] Clearing typing for chat ${chatId} (any message)`,
        );
        return { ...initialTypingStatus };
      }
      console.debug(
        `[aiTypingStore] NOT clearing typing - current chatId: ${current.chatId}, requested: ${chatId}`,
      );
      return current; // Don't clear if different chat
    });
  },
  reset: () => {
    aiTypingByChatStore.set({});
    store.set({ ...initialTypingStatus });
  },
};
