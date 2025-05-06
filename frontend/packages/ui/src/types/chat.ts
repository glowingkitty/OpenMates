// Represents the state of a message on the client
export interface Message {
  id: string; // Unique message identifier
  chatId: string; // ID of the parent chat
  content: Record<string, any>; // Decrypted Tiptap JSON object for rendering
  sender_name: string; // Holds 'user' or the specific AI name (e.g., "Gemini")
  status: 'sending' | 'sent' | 'error' | 'streaming' | 'delivered'; // Crucial for UI state rendering
  createdAt: Date; // Timestamp of creation/completion
}

// Represents the state of a full chat on the client, including its messages
export interface Chat {
  id: string; // Unique chat identifier (client-generated UUID)
  user_id?: string; // Last 10 characters of the hashed user ID (from server)
  title: string | null; // Decrypted title
  draft: Record<string, any> | null; // Decrypted Tiptap JSON draft object
  version: number; // Last known version from server (for conflict checks)
  mates?: string[]; // Optional: List of mate identifiers involved in the chat
  messages: Message[]; // Array of message objects belonging to this chat
  createdAt: Date; // Timestamp of chat initiation
  updatedAt: Date; // Timestamp of last known update (draft, message, etc.)
  lastMessageTimestamp: Date | null; // Timestamp of the actual last completed message
  unreadCount?: number; // Optional: Count of unread messages
  isLoading?: boolean; // Optional flag for UI loading state
  isPersisted: boolean; // Derived flag: true if chat has messages and exists in Directus, false if draft-only
}

// Represents a summarized chat item for display in the sidebar list
export interface ChatListItem {
  id: string; // client-generated UUID
  user_id?: string; // Last 10 characters of the hashed user ID (from server)
  title: string | null;
  lastMessageSnippet: string | null; // Short preview derived from the last message's content
  lastMessageTimestamp: Date | null; // Timestamp for sorting
  draft: Record<string, any> | null; // Add optional draft content
  hasUnread?: boolean; // Optional flag for UI state indication
}

// Keep MessageStatus type if used elsewhere, although Message interface now defines its own status literals
export type MessageStatus = 'sending' | 'sent' | 'error' | 'streaming' | 'delivered';

// Keep MessagePart if it's used elsewhere, although not in the core Chat/Message models from spec
export interface MessagePart {
    type: 'text' | 'app-cards';
    content: string | any[];
}

// Remove old ChatListEntry as ChatListItem replaces it
// export interface ChatListEntry { ... }
