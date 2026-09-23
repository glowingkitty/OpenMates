"""Strict wire schemas for client-encrypted remote Project commands."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemoteCommandPolicy(_StrictModel):
    argv: list[str] = Field(min_length=1, max_length=128)
    cwd: str = Field(min_length=1, max_length=1024)
    mode: Literal["foreground", "background"] = "foreground"
    source_access: Literal["read_only", "read_write"] = "read_only"
    deadline_ms: int = Field(ge=100, le=86_400_000)
    writable_profiles: list[str] = Field(default_factory=list, max_length=32)
    network_profile: str | None = Field(default=None, max_length=128)
    credential_profiles: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_exact_request(self) -> "RemoteCommandPolicy":
        if any(not value or "\x00" in value or len(value.encode("utf-8")) > 16_384 for value in self.argv):
            raise ValueError("argv entries must be non-empty and bounded")
        if "\x00" in self.cwd or self.cwd.startswith("/") or any(part == ".." for part in self.cwd.replace("\\", "/").split("/")):
            raise ValueError("cwd must be Project-relative")
        if self.mode == "background" and self.source_access == "read_write":
            raise ValueError("background commands cannot write Project source")
        for values in (self.writable_profiles, self.credential_profiles):
            if len(values) != len(set(values)) or any(not value or len(value) > 128 for value in values):
                raise ValueError("resource profile ids must be unique and bounded")
        return self


class RemoteCommandApproval(_StrictModel):
    kind: Literal["one_run", "preset"]
    preset_id: str | None = Field(default=None, max_length=128)
    definition_digest: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_kind(self) -> "RemoteCommandApproval":
        if self.kind == "preset":
            if not self.preset_id or not self.definition_digest:
                raise ValueError("preset approval requires preset_id and definition_digest")
        elif self.preset_id is not None or self.definition_digest is not None:
            raise ValueError("one_run approval cannot include preset metadata")
        return self


class RemoteCommandPrepare(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    review_token: str = Field(min_length=32, max_length=512)
    encrypted_request: str = Field(min_length=1, max_length=1_048_576)
    request_digest: str = Field(min_length=32, max_length=512)
    approval: RemoteCommandApproval


class RemoteCommandReject(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    review_token: str = Field(min_length=32, max_length=512)


class RemoteCommandClaim(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_session_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)


class RemoteCommandDiscover(_StrictModel):
    protocol_version: Literal[1]
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_session_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)


class RemoteCommandRecover(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_session_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    last_sequence: int = Field(ge=-1)
    runtime_status: Literal["running", "stopping", "terminal_pending"]


class RemoteCommandRuntimeEvent(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_session_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    lease_token: str = Field(min_length=16, max_length=512)
    lease_generation: int = Field(ge=1)
    sequence: int = Field(ge=0)
    event_kind: Literal["status", "output", "output_truncated", "terminal"]
    status: Literal[
        "authorizing", "running", "succeeded", "failed", "stopped", "timed_out"
    ]
    encrypted_event: str = Field(min_length=1, max_length=1_048_576)


class RemoteCommandSourceCompletion(_StrictModel):
    """Terminal ciphertext plus transient plaintext inference excerpt from its source."""

    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_session_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    lease_token: str = Field(min_length=16, max_length=512)
    lease_generation: int = Field(ge=1)
    sequence: int = Field(ge=0)
    status: Literal["succeeded", "failed", "stopped", "timed_out"]
    encrypted_event: str = Field(min_length=1, max_length=1_048_576)
    model_text: str = Field(max_length=524_288)
    upstream_truncated: bool = False
    omitted_chars: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_truncation_metadata(self) -> "RemoteCommandSourceCompletion":
        if not self.upstream_truncated and self.omitted_chars not in {None, 0}:
            raise ValueError("omitted_chars requires upstream_truncated")
        return self


class RemoteCommandRevalidate(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_session_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    lease_token: str = Field(min_length=16, max_length=512)
    lease_generation: int = Field(ge=1)


class RemoteCommandStop(_StrictModel):
    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)


class RemoteCommandOriginCompletion(_StrictModel):
    """Guarded plaintext completion submitted by the originating first-party client."""

    protocol_version: Literal[1]
    execution_id: str = Field(min_length=1, max_length=128)
    chat_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    result_status: Literal["succeeded", "failed", "stopped", "timed_out"]
    model_text: str = Field(max_length=524_288)
    upstream_truncated: bool = False
    omitted_chars: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_truncation_metadata(self) -> "RemoteCommandOriginCompletion":
        if not self.upstream_truncated and self.omitted_chars not in {None, 0}:
            raise ValueError("omitted_chars requires upstream_truncated")
        return self
