import { writable } from 'svelte/store';

export interface AITypingStatus {
    isTyping: boolean;
    category: string | null; // Changed from mateName
    modelName?: string | null; // Added field for the AI model name
    chatId: string | null;
    userMessageId: string | null; // The user message that triggered the AI
    aiMessageId: string | null; // The AI's message (task_id)
}

const initialTypingStatus: AITypingStatus = {
    isTyping: false,
    category: null, // Changed from mateName
    modelName: null,
    chatId: null,
    userMessageId: null,
    aiMessageId: null,
};

const store = writable<AITypingStatus>(initialTypingStatus);

export const aiTypingStore = {
    subscribe: store.subscribe,
    setTyping: (chatId: string, userMessageId: string, aiMessageId: string, category: string, modelName?: string | null) => { // Changed mateName to category, added modelName
        store.set({ 
            isTyping: true, 
            category, // Changed from mateName
            modelName: modelName || null,
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
