import { writable } from 'svelte/store';

export interface AITypingStatus {
    isTyping: boolean;
    category: string | null; // Changed from mateName
    chatId: string | null;
    userMessageId: string | null; // The user message that triggered the AI
    aiMessageId: string | null; // The AI's message (task_id)
}

const initialTypingStatus: AITypingStatus = {
    isTyping: false,
    category: null, // Changed from mateName
    chatId: null,
    userMessageId: null,
    aiMessageId: null,
};

const store = writable<AITypingStatus>(initialTypingStatus);

export const aiTypingStore = {
    subscribe: store.subscribe,
    setTyping: (chatId: string, userMessageId: string, aiMessageId: string, category: string) => { // Changed mateName to category
        store.set({ 
            isTyping: true, 
            category, // Changed from mateName
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
