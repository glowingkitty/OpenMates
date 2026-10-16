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

    async def open(self, *, summary: str, messages: list[dict[str, Any]],
                   base_instruction: str = "", app_catalogue: str = "",
                   mate_instruction: str = "", voice_name: str | None = None,
                   active_focus: dict[str, Any] | None = None) -> None: ...
    async def send_audio(self, encoded_pcm: str) -> None: ...
    async def end_audio(self) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def send_tool_response(self, function_call_id: str, response: dict[str, Any]) -> None: ...
    async def update_context(self, *, summary: str, messages: list[dict[str, Any]],
                             active_focus: dict[str, Any] | None = None) -> None: ...
    async def receive(self) -> dict[str, Any]: ...
    async def resume(self, handle: str) -> None: ...
    async def close(self) -> None: ...
