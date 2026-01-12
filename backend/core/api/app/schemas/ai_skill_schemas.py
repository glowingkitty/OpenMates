# backend/core/api/app/schemas/ai_skill_schemas.py
# This file contains Pydantic models for AI skill requests and responses
# that might be shared between the core API and the AI app services.

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.core.api.app.schemas.chat import AIHistoryMessage

class AskSkillRequest(BaseModel):
    chat_id: str = Field(..., description="The ID of the chat session.")
    message_id: str = Field(..., description="The ID of the user's most recent message in the history.")
    user_id: str = Field(..., description="Actual ID of the user.")
    user_id_hash: str = Field(..., description="Hashed ID of the user.")
    message_history: List[AIHistoryMessage] = Field(..., description="The complete history of messages in the chat, ordered chronologically. The last message is the current one.")
    chat_has_title: bool = Field(default=False, description="Whether the chat already has a title. Used to determine if metadata (title, category, icon) should be generated.")
    mate_id: Optional[str] = Field(default=None, description="The ID of the Mate to use. If None, AI will select.")
    active_focus_id: Optional[str] = Field(default=None, description="The ID of the currently active focus, if any.")
    user_preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="User-specific preferences.")
    app_settings_memories_metadata: Optional[List[str]] = Field(default=None, description="List of available app settings/memories keys from client in 'app_id-item_type' format (e.g., ['code-preferred_technologies', 'travel-trips']). Client is source of truth since only client can decrypt.")

# Add other shared AI skill-related schemas here if needed in the future.
