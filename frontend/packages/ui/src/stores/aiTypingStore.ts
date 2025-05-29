import { writable } from 'svelte/store';

export interface AITypingStatus {
    isTyping: boolean;
    mateName: string | null;
    chatId: string | null;
    userMessageId: string | null; // The user message that triggered the AI
    aiMessageId: string | null; // The AI's message (task_id)
}

const initialTypingStatus: AITypingStatus = {
    isTyping: false,
    mateName: null,
    chatId: null,
    userMessageId: null,
    aiMessageId: null,
};

const store = writable<AITypingStatus>(initialTypingStatus);

export const aiTypingStore = {
    subscribe: store.subscribe,
    setTyping: (chatId: string, userMessageId: string, aiMessageId: string, mateName: string) => {
        store.set({ 
            isTyping: true, 
            mateName, 
            chatId,
            userMessageId,
            aiMessageId
        });
    },
    clearTyping: (chatId: string, aiMessageId: string) => {
        // Only clear if the ended typing matches the current typing chat and message
        store.update(current => {
            if (current.chatId === chatId && current.aiMessageId === aiMessageId) {
                return { ...initialTypingStatus };
            }
            return current; // Otherwise, don't change if a different typing event ended
        });
    },
    reset: () => {
        store.set({...initialTypingStatus});
    }
};
