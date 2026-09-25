"""Wire schemas for client-executed Project file operations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


ProjectFileOperation = Literal[
    "list",
    "search",
    "read_text",
    "create_file",
    "update_file",
]


class ProjectFileOperationClaim(BaseModel):
    protocol_version: Literal[1]
    operation_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)


class ProjectFileOperationResult(BaseModel):
    protocol_version: Literal[1]
    operation_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    lease_token: str = Field(min_length=16, max_length=256)
    lease_generation: int = Field(ge=1)
    status: Literal[
        "completed",
        "conflict",
        "failed",
        "awaiting_approval",
        "waiting_for_executor",
    ]
    result: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result_shape(self) -> "ProjectFileOperationResult":
        # Approval is a client-owned decision. The server retains only the
        # commitment; the concrete proposal is forwarded transiently to UI.
        if self.status == "awaiting_approval":
            commitment = self.result.get("proposal_commitment")
            proposal = self.result.get("proposal")
            if not isinstance(commitment, str) or len(commitment) < 32:
                raise ValueError("awaiting_approval requires proposal_commitment")
            if not isinstance(proposal, dict) or not proposal:
                raise ValueError("awaiting_approval requires a concrete proposal")
        if self.status == "waiting_for_executor" and self.result.get("reason") not in {
            "source_offline",
            "protocol_timeout",
            "file_key_unavailable",
        }:
            raise ValueError("waiting_for_executor requires a bounded reason")
        return self


class ProjectFileOperationReject(BaseModel):
    protocol_version: Literal[1]
    operation_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
