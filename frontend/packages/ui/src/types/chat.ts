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
  user_id?: string; // Optional: User identifier associated with the chat on the client side
  title: string | null; // User-defined title of the chat (plain text)
  draft_content: TiptapJSON; // Tiptap JSON representing the user's unsent draft, or null
  
  // Versioning for synchronization
  messages_v: number; // Client's current version for messages
  draft_v: number; // Client's current version for its latest draft
  title_v: number; // Client's current version for title
  draft_version_db: number; // Version of the draft_content that is persisted in Directus (synced from server)

  last_edited_overall_timestamp: number; // Unix timestamp of the most recent modification to messages or draft (for sorting)
  unread_count: number; // Number of unread messages in this chat for the user

  messages: Message[]; // Array of message objects belonging to this chat
  mates?: string[]; // Optional: List of mate identifiers involved in the chat

  createdAt: Date; // Timestamp of chat record creation (local or initial sync)
  updatedAt: Date; // Timestamp of last local update to the chat record
}

// Represents component versions for a chat, used in synchronization
export interface ChatComponentVersions {
  messages_v: number;
  draft_v: number;
  title_v: number;
}

// Represents a summarized chat item for display in a list (e.g., sidebar)
// Aligned with cache key user:{user_id}:chat:{chat_id}:list_item_data from chat_sync_architecture.md
export interface ChatListItem {
  chat_id: string;
  title: string | null; // Current chat title (decrypted)
  draft_content: TiptapJSON; // Current draft content (Tiptap JSON string, or null)
  unread_count: number; // Current unread message count
  last_edited_overall_timestamp: number; // For sorting chat list items by recency
}

// Represents an offline change queued by the client
export interface OfflineChange {
  change_id: string; // Unique UUID for this queued change
  chat_id: string;
  type: 'title' | 'draft'; // Type of change
  value: string | TiptapJSON; // New value (plain text for title, TiptapJSON for draft)
  version_before_edit: number; // Client's component version number *before* this offline edit was made
}
