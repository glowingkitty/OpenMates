# backend/shared/python_schemas/code_run_outputs.py
#
# Pydantic payload schemas for Code Run output sidecar WebSocket ops. The
# terminal output payload is encrypted client-side with the embed key; the server
# only stores routing/auth metadata and the ciphertext.

from typing import Optional

from pydantic import BaseModel, Field


class UpsertCodeRunOutputPayload(BaseModel):
    """Client → server: create/update the latest output row for a code embed."""

    chat_id: str
    embed_id: str
    id: Optional[str] = Field(default=None, description="Client-generated uuid, optional on first sync.")
    key_version: Optional[int] = None
    encrypted_payload: str = Field(
        ...,
        description="E2EE JSON blob of CodeRunOutputPayload encrypted with the embed key.",
    )
    inference_payload: Optional[dict] = Field(
        default=None,
        description="Plaintext CodeRunOutputPayload for transient vault-encrypted LLM inference cache.",
    )
    created_at: int
    updated_at: int


class RequestCodeRunOutputPayload(BaseModel):
    """Client → server: request the latest output row for a code embed."""

    chat_id: str
    embed_id: str
