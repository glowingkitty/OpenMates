// frontend/packages/ui/src/types/chat.ts
// Defines the core data structures for chat, messages, and related entities.

// Alias for Tiptap JSON content
export type TiptapJSON = Record<string, any> | null;

// Represents the state of a message on the client, aligned with chat_sync_architecture.md
export type MessageStatus = 'sending' | 'synced' | 'failed';

export interface Message {
  message_id: string; // Unique message identifier (Format: {last_10_chars_of_chat_id}-{uuid_v4})
  chat_id: string; // Identifier of the chat this message belongs to
  sender: 'user' | string; // Indicates the origin: 'user' or AI mate name (e.g., "HelperBot")
  content: TiptapJSON; // Decrypted Tiptap JSON content of the message
  timestamp: number; // Creation Unix timestamp of the message
  status: MessageStatus; // Status of the message sending process
}


// Represents the state of a full chat on the client, aligned with chat_sync_architecture.md
export interface Chat {
  chat_id: string; // Unique identifier for the chat
  user_id?: string; // Optional: User identifier associated with the chat on the client side (owner/creator)
  title: string | null; // User-defined title of the chat (plain text)
  
  // User's draft content and version are stored directly on the chat object.
  draft_json?: TiptapJSON | null; // User's draft content for this chat
  draft_v?: number;              // Version of the user's draft for this chat

  // Versioning for synchronization
  messages_v: number; // Client's current version for messages for this chat
  title_v: number; // Client's current version for title for this chat

  last_edited_overall_timestamp: number; // Unix timestamp of the most recent modification to messages or the user's draft for this chat (for sorting)
  unread_count: number; // Number of unread messages in this chat for the current user

  messages: Message[]; // Array of message objects belonging to this chat
  mates?: string[]; // Optional: List of mate identifiers involved in the chat

  createdAt: Date; // Timestamp of chat record creation (local or initial sync)
  updatedAt: Date; // Timestamp of last local update to the chat record
}

// Represents component versions for a chat, used in synchronization requests from client to server.
export interface ChatComponentVersions { // Represents versions for a specific chat entity
    messages_v: number;
    title_v: number;
    draft_v?: number; // Version of the current user's draft for this chat, sent to server
}

// Represents a summarized chat item for display in a list (e.g., sidebar)
// This will be augmented with the current user's draft information at runtime if needed,
// though draft_json is now directly on the Chat object.
export interface ChatListItem {
    chat_id: string;
    title: string | null; // Current chat title (decrypted)
    // draft_content is available via the full Chat object if needed.
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
