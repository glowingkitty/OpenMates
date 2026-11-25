"""Voxtral realtime provider handshake, endpoint lifecycle and privacy boundary."""
from types import SimpleNamespace
import asyncio
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


class HTTP:
    def __init__(self, *sockets):
        self.sockets = iter(sockets)
        self.connections = []
        self.closed = False

    async def ws_connect(self, url, **kwargs):
        self.connections.append({"url": url, **kwargs})
        return next(self.sockets)

    async def close(self):
        self.closed = True


def speech_window(*events):
    return Socket({"type": "session.created"}, {"type": "session.updated"}, *events)


def open_transport(monkeypatch, *sockets):
    http = HTTP(*sockets)
    monkeypatch.setattr(provider.aiohttp, "ClientSession", lambda **_: http)
    return provider.VoxtralVoiceSession("server-secret"), http


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.audio.complete-turn-admission
async def test_first_audio_negotiates_voxtral_turn_detection_and_hints(monkeypatch):
    socket = speech_window()
    session, http = open_transport(monkeypatch, socket)
    await session.open()
    await session.set_context_bias(["Kyiv"])
    assert not http.connections
    await session.send_audio("first-captured-frame")
    assert http.connections[0]["url"].endswith("?model=voxtral-mini-transcribe-realtime-3-0")
    assert http.connections[0]["headers"] == {"Authorization": "Bearer server-secret"}
    assert socket.sent == [
        {"type": "session.update", "session": {
            "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
            "target_streaming_delay_ms": 240, "turn_detection": {}, "context_bias": ["Kyiv"],
        }},
        {"type": "input_audio.append", "audio": "first-captured-frame"},
    ]
    await session.close()
    assert socket.closed and http.closed and session._key == ""


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
async def test_quiet_parks_provider_without_pcm_and_resumes_the_same_logical_call(monkeypatch):
    first = speech_window({"type": "transcription.text.delta", "text": "Book for"},
                          {"type": "transcription.done", "text": "Book for two."})
    second = speech_window({"type": "turn.start"}, {"type": "transcription.text.delta", "text": "Thanks."})
    session, http = open_transport(monkeypatch, first, second)
    await session.open()
    await session.end_audio()
    assert not http.connections
    await session.send_audio("first-speech")
    await session.end_audio()
    await session.end_audio()
    assert await session.receive() == {"type": "transcription.text.delta", "text": "Book for"}
    assert await session.receive() == {"type": "transcription.text.delta", "text": " two."}
    assert await session.receive() == {"type": "turn.end"}
    assert first.closed and not http.closed
    idle_receive = asyncio.create_task(session.receive())
    await asyncio.sleep(0)
    assert not idle_receive.done() and len(http.connections) == 1
    assert first.sent[1:] == [{"type": "input_audio.append", "audio": "first-speech"},
                             {"type": "input_audio.end"}]
    await session.send_audio("resumed-speech")
    assert await asyncio.wait_for(idle_receive, 1) == {"type": "turn.start"}
    assert await session.receive() == {"type": "transcription.text.delta", "text": "Thanks."}
    assert second.sent[1:] == [{"type": "input_audio.append", "audio": "resumed-speech"}]
    await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.lifecycle.recovery-and-billing
async def test_speech_resuming_during_flush_keeps_events_in_audio_order(monkeypatch):
    first = speech_window({"type": "turn.end"}, {"type": "transcription.text.delta", "text": "First."},
                          {"type": "transcription.done", "text": "First."})
    second = speech_window({"type": "turn.start"})
    session, _ = open_transport(monkeypatch, first, second)
    await session.open()
    await session.send_audio("first")
    await session.end_audio()
    await session.send_audio("second")
    events = [await session.receive() for _ in range(4)]
    assert [event["type"] for event in events] == ["turn.end", "transcription.text.delta", "turn.end", "turn.start"]
    assert first.closed and not second.closed
    await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
@pytest.mark.parametrize("provider_notifies", [True, False])
async def test_provider_idle_expiry_is_recoverable_without_replaying_audio(monkeypatch, provider_notifies):
    if provider_notifies:
        first = speech_window({"type": "error", "error": {"code": 3804}})
    else:
        first = speech_window()
        monkeypatch.setattr(provider, "STREAM_RECEIVE_TIMEOUT", 0.01)

        async def stalled_close() -> None:
            first.closed = True
            await asyncio.Event().wait()

        monkeypatch.setattr(provider, "STREAM_CLOSE_TIMEOUT", 0.01)
        monkeypatch.setattr(first, "close", stalled_close)
    second = speech_window({"type": "turn.start"})
    session, http = open_transport(monkeypatch, first, second)
    await session.open()
    await session.send_audio("before-expiry")
    assert await session.receive() == {"type": "turn.end"}
    assert first.closed and len(http.connections) == 1
    await session.send_audio("after-expiry")
    assert await session.receive() == {"type": "turn.start"}
    assert second.sent[1:] == [{"type": "input_audio.append", "audio": "after-expiry"}]
    await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.privacy
async def test_setup_failure_closes_socket_without_exposing_provider_text(monkeypatch):
    socket = Socket({"type": "error", "error": {"message": "PRIVATE PROVIDER DATA"}})
    session, http = open_transport(monkeypatch, socket)
    await session.open()
    with pytest.raises(RuntimeError) as error:
        await session.send_audio("frame")
    assert "PRIVATE" not in str(error.value) and socket.closed
    await session.close()
    assert http.closed


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.privacy
@pytest.mark.parametrize("code, expected", [(3804, 3804), (1234, 1234), (True, None),
                                           ("PRIVATE", None), (1000000, None), ({}, None)])
async def test_provider_errors_expose_only_safe_bounded_diagnostics(code, expected, caplog):
    socket = Socket({"type": "error", "error": {"code": code, "message": "PRIVATE USER TRANSCRIPT"}})
    try:
        with pytest.raises(provider.VoxtralVoiceError) as failure:
            await provider.VoxtralVoiceSession._read(socket)
        assert failure.value.provider_code == expected
        assert failure.value.provider_category == ("idle_timeout" if expected == 3804 else "provider_error")
        assert "PRIVATE" not in str(failure.value) + caplog.text
    finally:
        await socket.close()
