# backend/shared/python_schemas/notebook_run_outputs.py
#
# Pydantic payload schemas for notebook-run output sidecar WebSocket ops. The
# rich cell output payload is encrypted client-side with the notebook embed key;
# the server stores routing/auth metadata and ciphertext only.

from typing import Optional

from pydantic import BaseModel, Field


class UpsertNotebookRunOutputPayload(BaseModel):
    """Client -> server: create/update the latest output row for a notebook embed."""

    chat_id: str
    notebook_embed_id: str
    id: Optional[str] = Field(default=None, description="Client-generated uuid, optional on first sync.")
    source_version: Optional[str] = None
    key_version: Optional[int] = None
    encrypted_payload: str = Field(..., description="Client-side encrypted JSON blob encrypted with the notebook embed key.")
    created_at: int
    updated_at: int


class RequestNotebookRunOutputPayload(BaseModel):
    """Client -> server: request the latest output row for a notebook embed."""

    chat_id: str
    notebook_embed_id: str
