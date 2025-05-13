// Alias for Tiptap JSON content
export type TiptapJSON = Record<string, any> | null;

// Represents the state of a message on the client, aligned with chat_sync_architecture.md
export interface Message {
  message_id: string; // Unique message identifier (Format: {last_10_chars_of_chat_id}-{uuid_v4})
  chat_id: string; // Identifier of the chat this message belongs to
  sender: 'user' | string; // Indicates the origin: 'user' or AI mate name (e.g., "HelperBot")
  content: TiptapJSON; // Decrypted Tiptap JSON content of the message
  timestamp: number; // Creation Unix timestamp of the message
}


// Represents the state of a full chat on the client, aligned with chat_sync_architecture.md
export interface Chat {
  chat_id: string; // Unique identifier for the chat
  user_id?: string; // Optional: User identifier associated with the chat on the client side (owner/creator)
  title: string | null; // User-defined title of the chat (plain text)
  // draft_content, draft_v, draft_version_db removed as drafts are now user-specific and stored separately.
  
  // Versioning for synchronization
  messages_v: number; // Client's current version for messages for this chat
  title_v: number; // Client's current version for title for this chat
  // user_draft_v is handled per user, per chat, see UserChatDraft and DraftEditorState

  last_edited_overall_timestamp: number; // Unix timestamp of the most recent modification to messages or any user's draft for this chat (for sorting)
  unread_count: number; // Number of unread messages in this chat for the current user

  messages: Message[]; // Array of message objects belonging to this chat
  mates?: string[]; // Optional: List of mate identifiers involved in the chat

  createdAt: Date; // Timestamp of chat record creation (local or initial sync)
  updatedAt: Date; // Timestamp of last local update to the chat record
}

// Represents component versions for a chat, used in synchronization
export interface ChatComponentVersions { // Represents versions for a specific chat entity
    messages_v: number;
    title_v: number;
    // draft_v removed, user-specific draft versions are handled separately (e.g., in UserChatDraft or DraftEditorState)
    // If needed for sync, the server might send a map of user_draft_v for relevant users.
}

// Represents a summarized chat item for display in a list (e.g., sidebar)
// This will be augmented with the current user's draft information at runtime.
export interface ChatListItem {
    chat_id: string;
    title: string | null; // Current chat title (decrypted)
    // draft_content removed, will be fetched/managed per user.
    // A UI component might combine ChatListItem with the current UserChatDraft for display.
    unread_count: number; // Current unread message count for the logged-in user
    last_edited_overall_timestamp: number; // For sorting chat list items by recency
}

// Represents an offline change queued by the client
export interface OfflineChange {
  change_id: string; // Unique UUID for this queued change
  chat_id: string;
  type: 'title' | 'draft' | 'delete_draft'; // Type of change
  value: string | TiptapJSON | null; // New value (plain text for title, TiptapJSON for draft), null for delete_draft
  version_before_edit: number; // Client's component version number *before* this offline edit was made
}
