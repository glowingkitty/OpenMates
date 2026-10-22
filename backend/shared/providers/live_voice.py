"""Provider boundary for call-local speech transcription only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LiveVoiceCapabilities:
    audio_input: bool = True
    text_input: bool = False
    audio_output: bool = False
    transcripts: bool = True
    tools: bool = False
    video_input: bool = False


class LiveVoiceSession(Protocol):
    capabilities: LiveVoiceCapabilities
    model: str

    async def open(self) -> None: ...
    async def send_audio(self, encoded_pcm: str) -> None: ...
    async def end_audio(self) -> None: ...
    async def receive(self) -> dict[str, Any]: ...
    async def close(self) -> None: ...
