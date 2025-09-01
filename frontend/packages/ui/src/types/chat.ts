// frontend/packages/ui/src/types/chat.ts
// Defines the core data structures for chat, messages, and related entities.

// Alias for Tiptap JSON content
export type TiptapJSON = Record<string, any> | null;

// Represents the state of a message on the client, aligned with chat_sync_architecture.md
export type MessageStatus = 'sending' | 'synced' | 'failed' | 'waiting_for_internet' | 'streaming' | 'processing';

export type MessageRole = 'user' | 'assistant' | 'system'; // Added system for potential future use

export interface Message {
  message_id: string; // Unique message identifier (Format: {last_10_chars_of_chat_id}-{uuid_v4})
  chat_id: string; // Identifier of the chat this message belongs to
  role: MessageRole; // 'user' for user messages, 'assistant' for AI/mate messages
  category?: string; // e.g., 'software_development', 'medical_health', only if role is 'assistant'
  sender_name?: string; // Optional: actual name of the mate, if different from category-based name
  content: TiptapJSON; // Decrypted Tiptap JSON content of the message
  created_at: number; // Creation Unix timestamp of the message
  status: MessageStatus; // Status of the message sending process
  user_message_id?: string; // Optional: ID of the user message that this AI message is a response to
  current_chat_title?: string; // Optional: Current title of the chat when this message is sent (for AI context)
  client_message_id?: string; // Optional: Client-generated ID, used to match with server's message_id upon confirmation
}


// Represents the state of a full chat on the client, aligned with chat_sync_architecture.md
export interface Chat {
  chat_id: string; // Unique identifier for the chat
  user_id?: string; // Optional: User identifier associated with the chat on the client side (owner/creator)
  title: string | null; // Cleartext title for in-memory display (NEVER stored to IndexedDB)
  encrypted_title: string | null; // Encrypted title (ONLY used for storage/transmission, NEVER for display)
  
  encrypted_draft_md?: string | null; // User's encrypted draft content (markdown) for this chat
  encrypted_draft_preview?: string | null; // User's encrypted draft preview (truncated text for chat list display)
  draft_v?: number;              // Version of the user's draft for this chat

  messages_v: number; // Client's current version for messages for this chat
  title_v: number; // Client's current version for title for this chat

  last_edited_overall_timestamp: number; // Unix timestamp of the most recent modification to messages or the user's draft for this chat (for sorting)
  unread_count: number; // Number of unread messages in this chat for the current user
  mates: string[] | null;

  created_at: number; // Unix timestamp of chat record creation (local or initial sync)
  updated_at: number; // Unix timestamp of last local update to the chat record
}

export interface ChatComponentVersions {
    messages_v: number;
    title_v: number;
    draft_v?: number; 
}

export interface ChatListItem {
    chat_id: string;
    title: string | null; 
    unread_count: number; 
    last_edited_overall_timestamp: number; 
}

export interface OfflineChange {
  change_id: string; 
  chat_id: string;
  type: 'title' | 'draft' | 'delete_draft'; 
  value: string | TiptapJSON | null; 
  version_before_edit: number; 
}

// --- Client to Server Payloads ---
export interface InitialSyncRequestPayload {
    chat_versions: Record<string, ChatComponentVersions>;
    last_sync_timestamp?: number;
    pending_message_ids?: Record<string, string[]>; 
    immediate_view_chat_id?: string;
}

export interface UpdateTitlePayload {
    chat_id: string;
    encrypted_title: string;
}

export interface UpdateDraftPayload {
    chat_id: string;
    encrypted_draft_md: string | null;
    encrypted_draft_preview?: string | null;
}

export interface SyncOfflineChangesPayload {
    changes: OfflineChange[];
}

export interface RequestChatContentBatchPayload {
    chat_ids: string[];
}

export interface DeleteChatPayload {
    chatId: string; 
}

export interface DeleteDraftPayload { 
    chatId: string; 
}

export interface SendChatMessagePayload { 
    chat_id: string;
    message: Message;
}

export interface RequestCacheStatusPayload { 
    // No payload needed, just the type
}

export interface SetActiveChatPayload { 
    chat_id: string | null;
}

export interface CancelAITaskPayload { 
    task_id: string;
}
// --- End Client to Server Payloads ---


// --- AI Task and Stream related event payloads (Server to Client) ---
export interface AITaskInitiatedPayload { 
    chat_id: string;
    user_message_id: string; 
    ai_task_id: string;      
    status: "processing_started";
}

export interface AIMessageUpdatePayload { 
    type: "ai_message_chunk";
    task_id: string; 
    chat_id: string;
    message_id: string; 
    user_message_id: string;
    full_content_so_far: string;
    sequence: number;
    is_final_chunk: boolean;
    interrupted_by_soft_limit?: boolean; 
    interrupted_by_revocation?: boolean; 
}

export interface AITypingStartedPayload { 
    chat_id: string;
    message_id: string; 
    user_message_id: string; 
    category: string; 
    model_name?: string | null; // Added to include the name of the AI model
    title?: string | null; // Added to include the chat title
}

export interface AIMessageReadyPayload {
    chat_id: string;
    message_id: string;
    user_message_id: string;
}

export interface AITaskCancelRequestedPayload { 
    task_id: string;
    status: "revocation_sent" | "already_completed" | "not_found" | "error";
    message?: string; 
}
// --- End AI Task and Stream related event payloads ---

// --- Chat Update Payloads (Server to Client) ---
export interface ChatTitleUpdatedPayload {
    event: string; 
    chat_id: string;
    data: { encrypted_title: string };
    versions: { title_v: number };
}

export interface ChatDraftUpdatedPayload {
    event: string; 
    chat_id: string;
    data: { 
        encrypted_draft_md: string | null;
        encrypted_draft_preview?: string | null;
    };
    versions: { draft_v: number }; 
    last_edited_overall_timestamp: number;
}

export interface ChatMessageReceivedPayload { 
    event: string; 
    chat_id: string;
    message: Message; 
    versions: { messages_v: number };
    last_edited_overall_timestamp: number;
}

export interface ChatMessageConfirmedPayload { 
    chat_id: string;
    message_id: string; 
    temp_id?: string; 
    new_messages_v: number; 
    new_last_edited_overall_timestamp: number; 
}

export interface ChatDeletedPayload {
    chat_id: string;
    tombstone: boolean; 
}
// --- End Chat Update Payloads ---

// --- Core Sync Payloads (Server to Client) ---
export interface InitialSyncResponsePayload {
    chat_ids_to_delete: string[];
    chats_to_add_or_update: Array<{
        chat_id: string;
        versions: ChatComponentVersions;
        last_edited_overall_timestamp: number;
        type: 'new_chat' | 'updated_chat';
        created_at: number;
        updated_at: number;
        encrypted_title?: string;
        encrypted_draft_md?: string | null;
        encrypted_draft_preview?: string | null;
        unread_count?: number;
        messages?: Message[];
        mates?: string[] | null;
    }>;
    server_chat_order: string[];
    server_timestamp: number;
}

export interface PriorityChatReadyPayload {
    chat_id: string;
}

export interface CachePrimedPayload {
    status: "full_sync_ready";
}

export interface CacheStatusResponsePayload {
    is_primed: boolean;
}

// Define the structure of messages as they come from the server in the batch
export interface ServerBatchMessageFormat {
    message_id: string; // Server's primary key for the message
    chat_id: string;
    role: MessageRole;
    content: TiptapJSON;
    created_at: number; // Server's creation timestamp
    category?: string;
    client_message_id?: string; // The ID the client might have sent for this message
    user_message_id?: string; // If it's an AI response, the ID of the user message it's responding to
    // Add any other fields that might come from the server message in the batch
}

export interface ChatContentBatchResponsePayload {
    messages_by_chat_id: Record<string, ServerBatchMessageFormat[]>; // Use the new specific type here
}

export interface OfflineSyncCompletePayload {
    processed: number;
    conflicts: number;
    errors: number;
}
// --- End Core Sync Payloads ---
