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
  created_at: number; // Creation Unix timestamp of the message
  status: MessageStatus; // Status of the message sending process
  user_message_id?: string; // Optional: ID of the user message that this AI message is a response to
  current_chat_title?: string; // Optional: Current title of the chat when this message is sent (for AI context)
  client_message_id?: string; // Optional: Client-generated ID, used to match with server's message_id upon confirmation
  
  // Encrypted fields for zero-knowledge architecture (stored in IndexedDB)
  encrypted_content: string; // Encrypted markdown content, encrypted using chat-specific key
  encrypted_sender_name?: string; // Encrypted sender name, encrypted using chat-specific key
  encrypted_category?: string; // Encrypted category, encrypted using chat-specific key
  
  // Decrypted fields (computed on-demand, never stored)
  content?: string; // Decrypted markdown content (computed from encrypted_content)
  category?: string; // Decrypted category (computed from encrypted_category)
  sender_name?: string; // Decrypted sender name (computed from encrypted_sender_name)
  
  // Truncation fields for performance optimization (only for user messages)
  is_truncated?: boolean; // Flag indicating if content is truncated for display
  truncated_content?: string; // Truncated markdown content for display
  full_content_length?: number; // Length of full content for reference
}


// Represents the state of a full chat on the client, aligned with chat_sync_architecture.md
export interface Chat {
  chat_id: string; // Unique identifier for the chat
  user_id?: string; // Optional: User identifier associated with the chat on the client side (owner/creator)
  encrypted_title: string | null; // Encrypted title (ONLY used for storage/transmission, NEVER for display)
  
  encrypted_draft_md?: string | null; // User's encrypted draft content (markdown) for this chat
  encrypted_draft_preview?: string | null; // User's encrypted draft preview (truncated text for chat list display)
  draft_v?: number;              // Version of the user's draft for this chat

  messages_v: number; // Client's current version for messages for this chat
  title_v: number; // Client's current version for title for this chat

  last_edited_overall_timestamp: number; // Unix timestamp of the most recent modification to messages or the user's draft for this chat (for sorting)
  unread_count: number; // Number of unread messages in this chat for the current user

  // Scroll position tracking
  last_visible_message_id?: string | null; // Message ID of the last message visible in viewport

  created_at: number; // Unix timestamp of chat record creation (local or initial sync)
  updated_at: number; // Unix timestamp of last local update to the chat record
  
  // Processing state flag for new chats
  processing_metadata?: boolean; // True when waiting for metadata (title, icon, category) from server after sending first message
  
  // New encrypted fields for zero-knowledge architecture from message processing
  encrypted_chat_summary?: string | null; // Encrypted chat summary (2-3 sentences) generated during post-processing
  encrypted_chat_tags?: string | null; // Encrypted array of max 10 tags for categorizing the chat
  encrypted_follow_up_request_suggestions?: string | null; // Encrypted array of 6 follow-up request suggestions
  encrypted_chat_key?: string | null; // Chat-specific encryption key, encrypted with user's master key for device sync
  encrypted_icon?: string | null; // Encrypted icon name from Lucide library, generated during pre-processing
  encrypted_category?: string | null; // Encrypted category name, generated during pre-processing
}

export interface ChatComponentVersions {
    messages_v: number;
    title_v: number;
    draft_v?: number; 
}

// Interface for decrypted chat data (computed on-demand, never stored)
export interface DecryptedChatData {
    icon?: string; // Decrypted icon name
    category?: string; // Decrypted category name
}

// Separate interface for new_chat_request_suggestions
// According to message_processing.md, new_chat_request_suggestions should be stored separately
// (50 most recent suggestions stored in IndexedDB under separate key, not per chat)
export interface NewChatSuggestion {
  id: string; // Unique suggestion ID
  encrypted_suggestion: string; // Encrypted suggestion text (encrypted with master key)
  chat_id: string; // Associated chat ID for deletion when chat is deleted
  created_at: number; // Unix timestamp
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
    // REQUIRED: Explicit list of chat IDs client has (sorted)
    chat_ids: string[];
    // REQUIRED: Number of chats client has (for validation)
    chat_count: number;
    // REQUIRED: Version information for each chat
    chat_versions: Record<string, ChatComponentVersions>;
    // Optional: Last sync timestamp for incremental updates
    last_sync_timestamp?: number;
    // Optional: Pending messages that need confirmation
    pending_message_ids?: Record<string, string[]>; 
    // Optional: Chat ID to prioritize for immediate viewing
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
    encrypted_chat_key?: string | null; // Encrypted chat key for server storage (device sync)
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
    provider_name?: string | null; // Added to include the name of the AI provider
    title?: string | null; // Added to include the chat title
    icon_names?: string[]; // Added to include the icon names from AI preprocessing
    // DUAL-PHASE: task_id for tracking
    task_id?: string;
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

export interface AIBackgroundResponseCompletedPayload {
    chat_id: string;
    message_id: string; // AI's message ID
    user_message_id: string;
    task_id: string;
    full_content: string;
    interrupted_by_soft_limit?: boolean;
    interrupted_by_revocation?: boolean;
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
        encrypted_chat_key?: string | null; // Encrypted chat-specific key for decryption
        encrypted_icon?: string | null; // Encrypted icon name from Lucide library
        encrypted_category?: string | null; // Encrypted category name
        unread_count?: number;
        messages?: Message[];
    }>;
    server_chat_order: string[];
    server_timestamp: number;
}

export interface Phase1LastChatPayload {
    chat_id: string;
    chat_details: any;
    messages: Message[];
    new_chat_suggestions?: NewChatSuggestion[];  // New chat suggestions for Phase 1
    phase: 'phase1';
    already_synced?: boolean;  // Version-aware: true if client already has up-to-date version
}

export interface CachePrimedPayload {
    status: "full_sync_ready";
}

export interface CacheStatusResponsePayload {
    is_primed: boolean;
    chat_count: number; // Number of chats available in cache (REQUIRED - no silent failures!)
    timestamp: number; // Unix timestamp of the response (REQUIRED - no silent failures!)
}

// Define the structure of messages as they come from the server in the batch
// This is used for device sync - server only sends encrypted content (zero-knowledge architecture)
export interface ServerBatchMessageFormat {
    message_id: string; // Server's primary key for the message
    chat_id: string;
    role: MessageRole;
    created_at: number; // Server's creation timestamp
    client_message_id?: string; // The ID the client might have sent for this message
    user_message_id?: string; // If it's an AI response, the ID of the user message it's responding to
    
    // Only encrypted fields for device sync (zero-knowledge architecture)
    encrypted_content: string; // Encrypted markdown content, encrypted using chat-specific key
    encrypted_sender_name?: string; // Encrypted sender name, encrypted using chat-specific key
    encrypted_category?: string; // Encrypted category, encrypted using chat-specific key
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

// --- New Phased Sync Payloads ---
export interface PhasedSyncRequestPayload {
    phase: 'phase1' | 'phase2' | 'phase3' | 'all';
    // Version-aware delta sync: client sends current state to avoid receiving duplicates
    client_chat_versions?: Record<string, {messages_v: number, title_v: number, draft_v: number}>;
    client_chat_ids?: string[];
    client_suggestions_count?: number;
}

export interface PhasedSyncCompletePayload {
    phase: string;
    timestamp: number;
}

export interface SyncStatusResponsePayload {
    is_primed: boolean;  // Backend sends 'is_primed' (matches CacheStatusResponsePayload)
    chat_count: number;
    timestamp: number;
}

export interface Phase2RecentChatsPayload {
    chats: any[];
    chat_count: number;
    phase: 'phase2';
}

export interface Phase3FullSyncPayload {
  chats: any[];
  chat_count: number;
  new_chat_suggestions?: NewChatSuggestion[];
  phase: 'phase3';
}

// Scroll position and read status payloads
export interface ScrollPositionUpdatePayload {
  chat_id: string;
  message_id: string;
}

export interface ChatReadStatusUpdatePayload {
  chat_id: string;
  unread_count: number;
}

// --- End Core Sync Payloads ---
