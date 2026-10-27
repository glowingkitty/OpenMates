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
    idle_task = session._idle_audio_task
    assert idle_task is not None
    assert connection["url"].endswith("?model=voxtral-mini-transcribe-realtime-3-0")
    assert connection["headers"] == {"Authorization": "Bearer server-secret"}
    assert socket.sent == [{"type": "session.update", "session": {
        "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
        "target_streaming_delay_ms": 240, "turn_detection": {},
    }}]
    assert "systemInstruction" not in str(socket.sent) and "messages" not in str(socket.sent)
    await session.close()
    assert socket.closed and http.closed and session._key == ""
    assert idle_task.done() and session._idle_audio_task is None


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
    assert session._idle_audio_task is None


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


class IdleClock:
    """Advance only the provider's monotonic clock and sleep, without wall waits."""

    def __init__(self):
        self.now = 100.0
        self.sleeps = asyncio.Queue()

    async def sleep(self, delay):
        wake = asyncio.get_running_loop().create_future()
        self.sleeps.put_nowait((delay, wake))
        await wake

    async def next_sleep(self):
        return await asyncio.wait_for(self.sleeps.get(), 1)


async def open_idle_session(monkeypatch, socket):
    clock = IdleClock()
    monkeypatch.setattr(provider, "monotonic", lambda: clock.now)
    monkeypatch.setattr(provider, "asyncio", SimpleNamespace(
        Lock=asyncio.Lock, create_task=asyncio.create_task, wait_for=asyncio.wait_for,
        CancelledError=asyncio.CancelledError, sleep=clock.sleep,
    ))
    class HTTP:
        closed = False
        async def ws_connect(self, *args, **kwargs):
            return socket
        async def close(self):
            self.closed = True
    http = HTTP()
    monkeypatch.setattr(provider.aiohttp, "ClientSession", lambda **_: http)
    session = provider.VoxtralVoiceSession("key")
    await session.open()
    return session, clock, http


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.audio.complete-turn-admission
async def test_idle_audio_is_periodic_bounded_silence_without_an_extra_flush(monkeypatch):
    socket = Socket({"type": "session.created"}, {"type": "session.updated"})
    session, clock, http = await open_idle_session(monkeypatch, socket)
    try:
        await session.send_audio("real-microphone-pcm")
        await session.end_audio()
        for _ in range(3):
            delay, wake = await clock.next_sleep()
            assert delay == provider.IDLE_AUDIO_INTERVAL_SECONDS
            clock.now += delay
            wake.set_result(None)
            await asyncio.sleep(0)
            assert not session._unflushed_audio
            count = len(socket.sent)
            await session.end_audio()
            assert len(socket.sent) == count
        assert [event["type"] for event in socket.sent] == ["session.update"] + ["input_audio.append"] * 5
        silence = [base64.b64decode(event["audio"]) for event in socket.sent[3:]]
        assert len(silence) == 3
        assert all(len(pcm) == 6400 and not any(pcm) for pcm in silence)
    finally:
        idle_task = session._idle_audio_task
        await session.close()
    assert idle_task.done() and session._idle_audio_task is None
    assert http.closed and socket.closed


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.lifecycle.recovery-and-billing
@pytest.mark.parametrize("flush", [False, True])
async def test_actual_audio_and_flush_postpone_idle_append(monkeypatch, flush):
    socket = Socket({"type": "session.created"}, {"type": "session.updated"})
    session, clock, _ = await open_idle_session(monkeypatch, socket)
    try:
        delay, wake = await clock.next_sleep()
        clock.now += 9
        await session.send_audio("real-microphone-pcm")
        if flush:
            clock.now += 0.5
            await session.end_audio()
        clock.now = 100 + delay
        wake.set_result(None)
        delay, wake = await clock.next_sleep()
        assert delay == (9.5 if flush else 9)
        assert len(socket.sent) == (3 if flush else 2)
        clock.now += delay
        wake.set_result(None)
        await clock.next_sleep()
        assert socket.sent[-1]["audio"] == provider.IDLE_SILENCE_PCM
        assert session._unflushed_audio is (not flush)
    finally:
        await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.lifecycle.recovery-and-billing
async def test_idle_append_rechecks_real_audio_after_waiting_for_send_lock(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    class SlowMicSocket(Socket):
        async def send_json(self, event):
            if event.get("audio") == "real-microphone-pcm":
                started.set()
                await release.wait()
            await super().send_json(event)
    socket = SlowMicSocket({"type": "session.created"}, {"type": "session.updated"})
    session, clock, _ = await open_idle_session(monkeypatch, socket)
    try:
        delay, wake = await clock.next_sleep()
        clock.now += delay - 1
        microphone = asyncio.create_task(session.send_audio("real-microphone-pcm"))
        await asyncio.wait_for(started.wait(), 1)
        clock.now += 1
        wake.set_result(None)
        await asyncio.sleep(0)
        assert session._send_lock.locked() and len(socket.sent) == 1
        release.set()
        await asyncio.wait_for(microphone, 1)
        delay, _ = await clock.next_sleep()
        assert delay == provider.IDLE_AUDIO_INTERVAL_SECONDS
        assert socket.sent[-1]["audio"] == "real-microphone-pcm" and len(socket.sent) == 2
    finally:
        release.set()
        await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.audio.complete-turn-admission
async def test_delayed_idle_timer_never_accumulates_a_silence_backlog(monkeypatch):
    socket = Socket({"type": "session.created"}, {"type": "session.updated"})
    session, clock, _ = await open_idle_session(monkeypatch, socket)
    try:
        _, wake = await clock.next_sleep()
        clock.now += 100
        wake.set_result(None)
        delay, _ = await clock.next_sleep()
        assert delay == provider.IDLE_AUDIO_INTERVAL_SECONDS
        assert len(socket.sent) == 2 and socket.sent[-1]["audio"] == provider.IDLE_SILENCE_PCM
    finally:
        await session.close()


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.audio.complete-turn-admission
async def test_close_cancels_inflight_idle_send_and_releases_send_lock(monkeypatch):
    started, never_finish = asyncio.Event(), asyncio.Event()
    class SlowIdleSocket(Socket):
        async def send_json(self, event):
            if event.get("audio") == provider.IDLE_SILENCE_PCM:
                started.set()
                await never_finish.wait()
            await super().send_json(event)
    socket = SlowIdleSocket({"type": "session.created"}, {"type": "session.updated"})
    session, clock, http = await open_idle_session(monkeypatch, socket)
    _, wake = await clock.next_sleep()
    clock.now += provider.IDLE_AUDIO_INTERVAL_SECONDS
    wake.set_result(None)
    await asyncio.wait_for(started.wait(), 1)
    idle_task = session._idle_audio_task
    assert session._send_lock.locked()
    await asyncio.wait_for(session.close(), 1)
    assert idle_task.cancelled() and session._idle_audio_task is None
    assert socket.closed and http.closed and not session._send_lock.locked()
    with pytest.raises(RuntimeError, match="Voice transcription unavailable"):
        await session.send_audio("real-microphone-pcm")


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.privacy
async def test_keepalive_send_failure_disconnects_receiver_without_private_error_logs(monkeypatch, caplog):
    class FailingSocket(Socket):
        async def send_json(self, event):
            if event["type"] == "input_audio.append":
                raise OSError("PRIVATE PROVIDER AUDIO SECRET")
            await super().send_json(event)
        async def close(self):
            await super().close()
            self.events.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.CLOSED))
    socket = FailingSocket({"type": "session.created"}, {"type": "session.updated"})
    session, clock, http = await open_idle_session(monkeypatch, socket)
    try:
        delay, wake = await clock.next_sleep()
        receiver = asyncio.create_task(session.receive())
        clock.now += delay
        wake.set_result(None)
        with pytest.raises(RuntimeError, match="Voice transcription disconnected"):
            await asyncio.wait_for(receiver, 1)
        assert session._idle_audio_task.done()
        assert session._idle_audio_task.exception() is None
        assert "PRIVATE" not in caplog.text
    finally:
        await session.close()
    assert socket.closed and http.closed


# contract-test: supporting surface=gui.web assertions=video-call.provider.boundary,video-call.privacy
@pytest.mark.parametrize("code, expected", [(3804, 3804), (1234, 1234), (True, None),
                                           ("PRIVATE", None), (1000000, None), ({}, None)])
async def test_provider_errors_expose_only_safe_bounded_diagnostics(code, expected, caplog):
    socket = Socket({"type": "error", "error": {"code": code, "message": "PRIVATE USER TRANSCRIPT"}})
    session = provider.VoxtralVoiceSession("PRIVATE KEY")
    session._socket = socket
    try:
        with pytest.raises(provider.VoxtralVoiceError) as failure:
            await session.receive()
        assert failure.value.provider_code == expected
        assert failure.value.provider_category == ("idle_timeout" if expected == 3804 else "provider_error")
        assert "PRIVATE" not in str(failure.value) + caplog.text
    finally:
        await session.close()
