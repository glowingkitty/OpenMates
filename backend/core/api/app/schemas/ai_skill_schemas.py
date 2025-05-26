# backend/core/api/app/schemas/ai_skill_schemas.py
# This file contains Pydantic models for AI skill requests and responses
# that might be shared between the core API and the AI app services.

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AskSkillRequest(BaseModel):
    chat_id: str = Field(..., description="The ID of the chat session.")
    message_id: str = Field(..., description="The ID of the user's most recent message in the history.")
    user_id_hash: str = Field(..., description="Hashed ID of the user.")
    message_history: List[Dict[str, Any]] = Field(..., description="The complete history of messages in the chat, ordered chronologically. The last message is the current one.")
    mate_id: Optional[str] = Field(default=None, description="The ID of the Mate to use. If None, AI will select.")
    active_focus_id: Optional[str] = Field(default=None, description="The ID of the currently active focus, if any.")
    user_preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="User-specific preferences.")

# Add other shared AI skill-related schemas here if needed in the future.