from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel

# --- Core Message/Chat Models ---

class MessageBase(BaseModel):
    content: str  # Pure markdown content (never Tiptap JSON on server)
    role: Literal['user', 'assistant', 'system']
    category: Optional[str] = None # e.g., 'software_development', only if role is 'assistant'

class EncryptedMessageBase(BaseModel):
    """Base class for encrypted messages in zero-knowledge architecture"""
    encrypted_content: str  # Encrypted markdown content
    role: Literal['user', 'assistant', 'system']
    encrypted_category: Optional[str] = None # Encrypted category, only if role is 'assistant'
    encrypted_sender_name: Optional[str] = None # Encrypted sender name

class AIHistoryMessage(MessageBase):
    """Represents a message item specifically for AI history, including a creation timestamp."""
    created_at: int # Integer Unix timestamp

class ChatBase(BaseModel):
    title: Optional[str] = None  # Decrypted title
    # draft field here represents the current user's draft for the chat.
    # Its population will depend on fetching the specific user's draft.
    draft: Optional[Dict[str, Any]] = None  # Decrypted Tiptap JSON draft for the current user

# --- Database Representation (Directus) ---

class MessageInDB(BaseModel): # Represents the structure in Directus 'messages' table
    id: str # message_id
    chat_id: str
    encrypted_content: str # Tiptap JSON string, encrypted with chat-specific key
    role: Literal['user', 'assistant', 'system']
    category: Optional[str] = None
    created_at: datetime # timestamp

class ChatInDB(BaseModel): # Represents the structure in Directus 'chats' table
    id: str # chat_id
    hashed_user_id: str # Owner/creator of the chat context for this record
    vault_key_reference: str # For chat-specific encryption key
    encrypted_title: Optional[str] = None # Encrypted with chat-specific key
    messages_v: int
    title_v: int
    last_edited_overall_timestamp: datetime # Updated if chat's messages or any user's draft for this chat changes
    unread_count: int
    created_at: datetime
    updated_at: datetime
    last_message_timestamp: Optional[datetime] = None

# New DraftInDB model for the 'drafts' table
class DraftInDB(BaseModel):
    id: str # draft_id
    chat_id: str
    hashed_user_id: str # User who owns this draft
    encrypted_content: Optional[str] = None # Encrypted markdown, or null
    version: int # Draft version for this user/chat
    last_edited_timestamp: datetime
    created_at: datetime
    updated_at: datetime

# --- Cache Specific Models ---

class CachedChatVersions(BaseModel):
    """
    Versions for a chat stored in cache (user:{user_id}:chat:{chat_id}:versions).
    This key stores general chat versions. User-specific draft versions (user_draft_v:{user_id})
    are also stored in this hash dynamically or in a separate user-specific draft cache key.
    The 'draft_v' field here is removed as it's no longer a single version for the chat.
    """
    messages_v: int
    title_v: int
    # Example of how dynamic user draft versions might be represented if parsed from this key:
    # user_draft_versions: Optional[Dict[str, int]] = None # e.g., {"user_draft_v:some_user_id": 5}
    
    # For Pydantic v2 to allow extra fields like user_draft_v:xxxx
    model_config = {"extra": "allow"}
    # For Pydantic v1:
    # class Config:
    #     extra = "allow"


class CachedChatListItemData(BaseModel):
    """Data for chat list item stored in cache (user:{user_id}:chat:{chat_id}:list_item_data)"""
    title: str  # Encrypted with chat-specific key
    unread_count: int
    created_at: int
    updated_at: int
    encrypted_chat_key: Optional[str] = None  # Encrypted chat-specific key for decryption
    # draft_json is removed as it's now user-specific and in a different cache key

class CachedUserDraftData(BaseModel):
    """Data for a user's specific draft in a chat (user:{user_id}:chat:{chat_id}:draft)"""
    encrypted_draft_md: Optional[str] = None # Encrypted markdown string (user-specific key), or "null" string
    draft_v: int # Version of this user's draft for this chat

# --- Cache/Transient Representation (includes status) ---

class MessageInCache(MessageBase):
    id: str
    chat_id: str
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered']
    created_at: int

# --- API/WebSocket Responses (decrypted for client, includes status) ---

class MessageResponse(MessageBase):
    id: str
    chat_id: str
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered']
    created_at: int

class EncryptedMessageResponse(EncryptedMessageBase):
    """Response model for encrypted messages in zero-knowledge architecture"""
    id: str
    chat_id: str
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered']
    created_at: int

class ChatResponse(ChatBase):
    id: str
    created_at: int
    updated_at: int
    last_message_timestamp: Optional[int] = None
    messages: List[MessageResponse] = []

class ChatListItem(BaseModel):
    # Structure for sending summarized chat data for the list view (e.g., in initial_sync_data)
    # Corresponds to data points needed by frontend's ChatListItem type.
    id: str  # chat_id (formerly client_uuid in some contexts, now consistently chat_id)
    user_hash_suffix: Optional[str] = None # Last 10 chars of hashed user ID
    title: Optional[str] = None # Decrypted title
    lastMessageTimestamp: Optional[datetime] = None # For sorting/display
    draft: Optional[Dict[str, Any]] = None # Decrypted Tiptap JSON draft content
    unread_count: Optional[int] = None # Number of unread messages
    deleted: Optional[bool] = False # Tombstone status
    # Note: Frontend's ChatListItem also has lastMessageSnippet and hasUnread.
    # hasUnread can be derived from unread_count > 0.
    # lastMessageSnippet would require fetching/decrypting last message, handled by client or more detailed sync.

class DraftUpdateRequestData(BaseModel):
    client_id: str  # This is the client-generated UUID for the chat, which forms part of the server-side chat_id
    user_hash_suffix: Optional[str] = None  # 10-char server hash if known by client for existing chat
    content: Dict[str, Any]
    basedOnVersion: int

class WebSocketMessage(BaseModel):
    type: str
    payload: Dict[str, Any]

class ChatInitiatedPayload(BaseModel):
    tempChatId: str
    finalChatId: str
    version: int

class NewMessagePayload(BaseModel):
    message: MessageResponse

# --- WebSocket Payloads for Sync ---

class ClientChatComponentVersions(BaseModel):
    """Component versions structure expected by the client."""
    messages_v: int
    title_v: int
    draft_v: Optional[int] = None

class ChatSyncData(BaseModel):
    """Data for a single chat in the initial_sync_response."""
    chat_id: str
    versions: ClientChatComponentVersions # Changed from CachedChatVersions
    draft_v: Optional[int] = None # User-specific draft version for THIS user, for the client (can be redundant if client uses versions.draft_v)
    last_edited_overall_timestamp: int
    type: Literal['new_chat', 'updated_chat']
    created_at: int
    updated_at: int
    encrypted_title: Optional[str] = None # Encrypted title from cache
    encrypted_draft_md: Optional[str] = None # Encrypted markdown for the user's draft
    encrypted_chat_key: Optional[str] = None # Encrypted chat-specific key for decryption
    unread_count: Optional[int] = None
    messages: Optional[List[EncryptedMessageResponse]] = None # List of encrypted messages, typically for priority chat

class InitialSyncResponsePayloadSchema(BaseModel):
    """Structure of the 'initial_sync_response' payload."""
    chat_ids_to_delete: List[str]
    chats_to_add_or_update: List[ChatSyncData]
    server_chat_order: List[str]
    server_timestamp: int # Unix timestamp
# --- Forward reference rebuilds if needed ---
try:
    ChatResponse.model_rebuild()
except Exception:
    pass
