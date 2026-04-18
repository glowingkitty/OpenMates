# backend/shared/python_schemas/message_highlights.py
#
# Pydantic payload schemas for the 3 message-highlight WebSocket ops.
# Mirrors the TypeScript types in frontend/packages/ui/src/types/chat.ts
# (AddMessageHighlightPayload / UpdateMessageHighlightPayload /
# RemoveMessageHighlightPayload). See docs/architecture and the plan file
# for the rationale behind per-row E2EE storage.

from typing import Optional

from pydantic import BaseModel, Field


class AddMessageHighlightPayload(BaseModel):
    """Client → server: INSERT a new highlight row."""
    chat_id: str
    message_id: str
    id: str = Field(
        ...,
        description="Client-generated uuid — server uses as primary key.",
    )
    author_user_id: str
    key_version: Optional[int] = None
    encrypted_payload: str = Field(
        ...,
        description="E2EE blob (AES-GCM with chat key) of MessageHighlightPayload JSON.",
    )
    created_at: int


class UpdateMessageHighlightPayload(BaseModel):
    """Client → server: UPDATE the encrypted payload of an existing highlight (author only)."""
    chat_id: str
    message_id: str
    id: str
    encrypted_payload: str
    updated_at: int


class RemoveMessageHighlightPayload(BaseModel):
    """Client → server: DELETE a highlight (author only)."""
    chat_id: str
    message_id: str
    id: str
