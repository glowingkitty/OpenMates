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
    version: int                 # Current version for optimistic locking

# --- Database Representation (Directus) ---

class MessageInDB(BaseModel):
    id: str
    chat_id: str
    encrypted_content: str
    sender_name: str
    created_at: datetime

class ChatInDB(BaseModel):
    id: str
    hashed_user_id: str
    vault_key_reference: str
    encrypted_title: Optional[str] = None
    encrypted_draft: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime
    last_message_timestamp: Optional[datetime] = None

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

# --- Specific Payloads ---

class DraftUpdateRequestData(BaseModel):
    tempChatId: Optional[str] = None
    chatId: Optional[str] = None
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