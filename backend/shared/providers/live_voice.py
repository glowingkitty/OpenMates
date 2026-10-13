"""Provider boundary for an ephemeral, chat-bound voice session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LiveVoiceCapabilities:
    audio_input: bool
    text_input: bool
    audio_output: bool
    transcripts: bool
    tools: bool = False
    video_input: bool = False


class LiveVoiceSession(Protocol):
    capabilities: LiveVoiceCapabilities
    model: str

    async def open(self, *, summary: str, messages: list[dict[str, str]]) -> None: ...
    async def send_audio(self, encoded_pcm: str) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def receive(self) -> dict[str, Any]: ...
    async def resume(self, handle: str) -> None: ...
    async def close(self) -> None: ...
