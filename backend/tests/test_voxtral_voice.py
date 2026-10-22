"""Voxtral realtime provider handshake, endpoint lifecycle and privacy boundary."""
from types import SimpleNamespace
import asyncio
import base64
import json

import aiohttp
import pytest

from backend.shared.providers import voxtral_voice as provider


class Socket:
    def __init__(self, *events):
        self.events = asyncio.Queue()
        self.sent = []
        self.closed = False
        for event in events:
            self.events.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(event)))

    async def receive(self):
        return await self.events.get()

    async def send_json(self, event):
        self.sent.append(event)

    async def close(self):
        self.closed = True


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.audio.complete-turn-admission
async def test_open_uses_voxtral3_turn_detection_low_delay_and_no_chat_prompt(monkeypatch):
    socket = Socket({"type": "session.created"}, {"type": "session.updated"})
    connection = {}
    class HTTP:
        closed = False
        async def ws_connect(self, url, **kwargs):
            connection.update(url=url, **kwargs)
            return socket
        async def close(self):
            self.closed = True
    http = HTTP()
    monkeypatch.setattr(provider.aiohttp, "ClientSession", lambda **_: http)
    session = provider.VoxtralVoiceSession("server-secret")
    await session.open()
    assert connection["url"].endswith("?model=voxtral-mini-transcribe-realtime-3-0")
    assert connection["headers"] == {"Authorization": "Bearer server-secret"}
    assert socket.sent == [{"type": "session.update", "session": {
        "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
        "target_streaming_delay_ms": 240, "turn_detection": {},
    }}]
    assert "systemInstruction" not in str(socket.sent) and "messages" not in str(socket.sent)
    await session.close()
    assert socket.closed and http.closed and session._key == ""


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.audio.complete-turn-admission
async def test_mute_flush_is_bounded_unbilled_padding_and_never_ends_provider_session():
    socket = Socket()
    session = provider.VoxtralVoiceSession("key")
    session._socket = socket
    chunk = base64.b64encode(bytes(320)).decode()
    await session.send_audio(chunk)
    await session.end_audio()
    await session.end_audio()
    await session.send_audio(chunk)
    assert [event["type"] for event in socket.sent] == ["input_audio.append"] * 3
    assert socket.sent[0]["audio"] == socket.sent[2]["audio"] == chunk
    padding = base64.b64decode(socket.sent[1]["audio"])
    assert len(padding) == provider.FLUSH_SILENCE_BYTES and not any(padding)
    assert not socket.closed
    await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.privacy
async def test_setup_failure_closes_both_resources_without_leaking_provider_payload(monkeypatch):
    socket = Socket({"type": "error", "message": "PRIVATE PROVIDER DATA"})
    class HTTP:
        closed = False
        async def ws_connect(self, *args, **kwargs):
            return socket
        async def close(self):
            self.closed = True
    http = HTTP()
    monkeypatch.setattr(provider.aiohttp, "ClientSession", lambda **_: http)
    session = provider.VoxtralVoiceSession("secret")
    with pytest.raises(RuntimeError) as error:
        await session.open()
    assert "PRIVATE" not in str(error.value)
    assert http.closed and socket.closed


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.audio.complete-turn-admission
async def test_turn_end_and_trailing_delta_reach_controller_in_provider_order():
    events = [{"type": "turn.end", "time_s": 1.2, "end_reason": "threshold"},
              {"type": "transcription.text.delta", "text": " no, Paris instead"}]
    socket = Socket(*events)
    session = provider.VoxtralVoiceSession("key")
    session._socket = socket
    assert [await session.receive(), await session.receive()] == events
    assert not session.capabilities.audio_output and not session.capabilities.tools and not session.capabilities.video_input
    await session.close()
