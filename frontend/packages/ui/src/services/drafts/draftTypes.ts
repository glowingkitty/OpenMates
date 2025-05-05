import type { Chat } from '../../types/chat'; // Adjusted path

// --- Store for Draft State ---
export interface DraftState {
    currentChatId: string | null; // ID of the chat the draft belongs to (null if new chat)
    currentTempDraftId: string | null; // Temporary ID used before chatId is assigned
    currentVersion: number; // Version of the draft being edited
    hasUnsavedChanges: boolean; // Flag to indicate if local changes haven't been confirmed by server
}

// --- Type for chat_details payload ---
export type ChatDetailsPayload = Chat; // Assuming the backend sends the full Chat object

// Define a more accurate type based on observed payload and backend change
export interface DraftUpdatedPayload {
    chatId: string | null; // Final ID (if assigned)
    tempChatId: string | null; // Original temp ID (should now be included for new chats)
    basedOnVersion: number; // This holds the *new* version number
    content?: Record<string, any>; // Optional content
}

export interface DraftConflictPayload {
    chatId?: string; // Optional: The final chat ID if known
    draftId: string; // Can be tempChatId or chatId
}