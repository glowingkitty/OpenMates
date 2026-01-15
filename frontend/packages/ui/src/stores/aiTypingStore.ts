import { writable } from 'svelte/store';

export interface AITypingStatus {
    isTyping: boolean;
    category: string | null; // Changed from mateName
    modelName?: string | null; // Added field for the AI model name
    providerName?: string | null; // Added field for the AI provider name
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
    chatId: null,
    userMessageId: null,
    aiMessageId: null,
};

const store = writable<AITypingStatus>(initialTypingStatus);

export const aiTypingStore = {
    subscribe: store.subscribe,
    setTyping: (chatId: string, userMessageId: string, aiMessageId: string, category: string, modelName?: string | null, providerName?: string | null, icon_names?: string[]) => { // Changed mateName to category, added modelName, providerName and icon_names
        store.set({ 
            isTyping: true, 
            category, // Changed from mateName
            modelName: modelName || null,
            providerName: providerName || null,
            chatId,
            userMessageId,
            aiMessageId,
            icon_names: icon_names || []
        });
    },
    clearTyping: (chatId: string, aiMessageId: string) => {
        // Clear typing if the chat and message ID match
        store.update(current => {
            if (current.chatId === chatId && current.aiMessageId === aiMessageId) {
                console.debug(`[aiTypingStore] Clearing typing for chat ${chatId}, message ${aiMessageId}`);
                return { ...initialTypingStatus };
            }
            console.debug(`[aiTypingStore] NOT clearing typing - current: ${current.chatId}/${current.aiMessageId}, requested: ${chatId}/${aiMessageId}`);
            return current; // Don't clear if different chat or message
        });
    },
    /**
     * Clear typing for a specific chat ID regardless of aiMessageId.
     * Used when cancelling tasks where we only have task_id, not message_id.
     * @param chatId - The chat ID to clear typing for
     */
    clearTypingForChat: (chatId: string) => {
        store.update(current => {
            if (current.chatId === chatId) {
                console.debug(`[aiTypingStore] Clearing typing for chat ${chatId} (any message)`);
                return { ...initialTypingStatus };
            }
            console.debug(`[aiTypingStore] NOT clearing typing - current chatId: ${current.chatId}, requested: ${chatId}`);
            return current; // Don't clear if different chat
        });
    },
    reset: () => {
        store.set({...initialTypingStatus});
    }
};
