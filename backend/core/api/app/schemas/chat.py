from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel

# --- Core Message/Chat Models ---

class MessageBase(BaseModel):
    content: Dict[str, Any]  # Decrypted Tiptap JSON object
    sender_name: str         # 'user' or specific AI name

class ChatBase(BaseModel):
    title: Optional[str] = None  # Decrypted title
    draft: Optional[Dict[str, Any]] = None  # Decrypted Tiptap JSON draft

# --- Database Representation (Directus) ---

class MessageInDB(BaseModel): # Represents the structure in Directus 'messages' table
    id: str # message_id
    chat_id: str
    encrypted_content: str # Tiptap JSON string
    sender_name: str # 'user' or AI mate name
    created_at: datetime # timestamp

class ChatInDB(BaseModel): # Represents the structure in Directus 'chats' table
    id: str # chat_id
    hashed_user_id: str
    vault_key_reference: str
    encrypted_title: Optional[str] = None
    encrypted_draft: Optional[str] = None # Encrypted Tiptap JSON string, or null
    draft_version_db: int
    messages_version: int
    title_version: int
    last_edited_overall_timestamp: datetime
    unread_count: int
    created_at: datetime
    updated_at: datetime
    last_message_timestamp: Optional[datetime] = None

# --- Cache Specific Models ---

class CachedChatVersions(BaseModel):
    """Versions for a chat stored in cache (user:{user_id}:chat:{chat_id}:versions)"""
    messages_v: int
    draft_v: int
    title_v: int

class CachedChatListItemData(BaseModel):
    """Data for chat list item stored in cache (user:{user_id}:chat:{chat_id}:list_item_data)"""
    title: str  # Encrypted
    unread_count: int
    draft_json: Optional[str] = None  # Encrypted Tiptap JSON string, or null

# --- Cache/Transient Representation (includes status) ---

class MessageInCache(MessageBase):
    id: str
    chat_id: str
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered']
    created_at: datetime

# --- API/WebSocket Responses (decrypted for client, includes status) ---

class MessageResponse(MessageBase):
    id: str
    chat_id: str
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered']
    created_at: datetime

class ChatResponse(ChatBase):
    id: str
    created_at: datetime
    updated_at: datetime
    last_message_timestamp: Optional[datetime] = None
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

# --- Forward reference rebuilds if needed ---
try:
    ChatResponse.model_rebuild()
except Exception:
    pass