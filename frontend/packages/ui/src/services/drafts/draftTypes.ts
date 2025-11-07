import type { Chat } from '../../types/chat'; // Adjusted path

// Define TiptapJSON type directly if not available from a central import
// This represents the JSON structure of Tiptap editor content.
export type TiptapJSON = Record<string, any>;

// --- Store for Draft Editor UI State ---
export interface DraftEditorState {
	currentChatId: string | null; // The chat_id for which a draft is being edited.
	currentUserDraftVersion: number; // Version of the current user's draft being edited for currentChatId.
	hasUnsavedChanges: boolean; // Flag to indicate if local changes haven't been confirmed by server.
	newlyCreatedChatIdToSelect: string | null; // chat_id of a new chat to be selected by UI.
	lastSavedContentMarkdown: string | null; // Stores the cleartext markdown of the last successfully saved draft (for comparison)
	isSwitchingContext: boolean; // Flag to prevent draft deletion during context switching
}

// Represents a draft as stored in IndexedDB or managed in client-side state per user per chat.
// User ID is implicit as IndexedDB is per browser profile (i.e., per user on that device).
export interface UserChatDraft {
    chat_id: string;
    // user_id: string; // Removed: Implicit for client-side storage.
    encrypted_draft_md: string | null; // Encrypted markdown content.
    version: number; // Version of this specific draft for this chat (for the current user).
    last_edited_timestamp: number; // Local timestamp
}


// --- WebSocket Event Payloads Related to Drafts ---

/**
 * Payload for the 'chat_draft_updated' event received from the server.
 * This event is broadcast to the originating user's other devices.
 */
export interface ServerChatDraftUpdatedEventPayload {
    event: "chat_draft_updated";
    chat_id: string;
    data: {
        encrypted_draft_md: string | null; // Encrypted draft content (markdown)
    };
    versions: {
        draft_v: number; // The new version of the user's draft for this chat
    };
    last_edited_overall_timestamp: number; // Timestamp for the chat's overall last edit
}

// Example of a client-initiated draft update payload (sent to server)
export interface ClientUpdateDraftPayload {
    action: "update_draft";
    chat_id: string;
    encrypted_draft_md: string | null;
    // basedOnVersion might be useful for client-side optimistic updates or conflict detection,
    // but server primarily relies on incrementing its current version.
}


export interface DraftConflictPayload {
    chat_id: string; // chat_id for which the conflict occurred
    // Additional fields might be needed depending on conflict resolution strategy
}
// Represents the server's response for a 'get_chat_details' request,
// potentially including the current user's draft for that chat.
export interface ChatDetailsServerResponse extends Chat {
    encrypted_draft_md?: string | null; // The current user's encrypted draft content for this chat, if available
    draft_v?: number;                 // The version of the current user's draft for this chat, if available
}