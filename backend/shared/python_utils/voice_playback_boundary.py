"""Bounded first-party delivery data, never tool or provider authority."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

SequenceNumber = Annotated[int, Field(strict=True, ge=0, le=65535)]


class VoiceHeardBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant_message_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    completed_sequences: list[SequenceNumber] = Field(default_factory=list, max_length=256)
    active_sequence: SequenceNumber | None = None
    active_offset_ms: int = Field(default=0, strict=True, ge=0, le=3_600_000)

    @field_validator("completed_sequences")
    @classmethod
    def unique_sequences(cls, value: list[int]) -> list[int]:
        return sorted(set(value))
