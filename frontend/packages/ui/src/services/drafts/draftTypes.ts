import type { Chat } from '../../types/chat'; // Adjusted path

// --- Store for Draft State ---
export interface DraftState {
	currentChatId: string | null; // Stores the client-generated UUID. This is the primary ID on the client.
	draft_v: number; // Version of the draft being edited, aligns with Chat.draft_v
	hasUnsavedChanges: boolean; // Flag to indicate if local changes haven't been confirmed by server
	newlyCreatedChatIdToSelect: string | null; // Client UUID of a new chat to be selected by UI
}

// --- Type for chat_details payload ---
// Assuming ChatDetailsPayload will also include user_id if it's part of the Chat type
export type ChatDetailsPayload = Chat;

// Define a more accurate type based on observed payload and backend change
export interface DraftUpdatedPayload {
    chatId: string; // This is the server-side composite ID (user_hash_suffix + client_uuid)
    id: string; // This is the client-generated UUID
    user_id: string; // The 10-character user hash suffix from the server
    basedOnVersion: number; // This holds the *new* version number
    content?: Record<string, any>; // Optional content
}

export interface DraftConflictPayload {
    chatId: string; // Server-side composite ID for which the conflict occurred
    id: string; // Client-generated UUID for which the conflict occurred
    draftId?: string; // Potentially redundant if 'id' is always the client UUID.
}