"""Pure provider protocol checks: no network, credentials or paid inference."""
# contract-test-file: tooling
from __future__ import annotations

import asyncio
import base64
from contextlib import aclosing
import json
from types import SimpleNamespace

import aiohttp
import pytest

from backend.shared.providers.elevenlabs import realtime as provider


class Socket:
    def __init__(self):
        self.sent = []
        self.frames = asyncio.Queue()
        self.closed = False
        self.on_send = None
        self.send_error = False

    async def send_json(self, payload):
        if self.send_error:
            raise RuntimeError("PRIVATE INPUT KEY AUDIO BODY")
        self.sent.append(payload)
        if self.on_send:
            self.on_send(payload)

    async def receive(self):
        return await self.frames.get()

    def emit(self, payload, *, kind=aiohttp.WSMsgType.TEXT):
        self.frames.put_nowait(SimpleNamespace(type=kind, data=json.dumps(payload)))

    async def close(self):
        self.closed = True
        self.emit({}, kind=aiohttp.WSMsgType.CLOSED)


@pytest.fixture
def transport(monkeypatch):
    socket = Socket()
    calls, http_clients = [], []

    class HTTP:
        def __init__(self, **kwargs):
            self.closed = False
            http_clients.append(self)

        async def ws_connect(self, url, **kwargs):
            calls.append((url, kwargs))
            return socket

        async def close(self):
            self.closed = True

    monkeypatch.setattr(aiohttp, "ClientSession", HTTP)
    monkeypatch.delenv("SECRET__ELEVENLABS__API_KEY", raising=False)
    return socket, calls, http_clients


def session(**kwargs):
    return provider.ElevenLabsRealtimeSession(voice_id="curated-voice", api_key="PRIVATE_KEY", **kwargs)


def audio(data=b"ID3public-fixture"):
    return {"audio": base64.b64encode(data).decode()}


@pytest.mark.asyncio
async def test_audio_arrives_before_input_iterator_finishes_and_exact_characters_are_sent(transport):
    socket, calls, clients = transport
    connection = session()
    await connection.open()
    first_audio = asyncio.Event()
    input_finished = False
    pieces = [" Hello café. ", "Another line 🙂.  "]

    async def inputs():
        nonlocal input_finished
        yield pieces[0]
        await first_audio.wait()
        yield pieces[1]
        input_finished = True

    async def writer():
        async for piece in inputs():
            await connection.append_text(piece)
            await connection.flush()
        await connection.finish_input()

    socket.on_send = lambda payload: socket.emit(audio()) if "inputs" in payload else None
    writer_task = asyncio.create_task(writer())
    async with aclosing(connection.audio_events()) as events:
        event = await asyncio.wait_for(anext(events), 1)
        assert event.audio_bytes == b"ID3public-fixture"
        assert not input_finished
        first_audio.set()
        await writer_task
        assert (await anext(events)).audio_bytes
        socket.emit({"is_final_audio_for_turn": True})
        assert (await anext(events)).final_for_turn
        socket.emit({"is_final": True})
        assert (await anext(events)).final
    assert connection.input_count == 2
    assert connection.submitted_characters == sum(map(len, pieces))
    assert [item["inputs"][0]["text"] for item in socket.sent if "inputs" in item] == pieces
    assert socket.sent[0] == {"voices": ["curated-voice"]}
    assert all(item["inputs"][0]["new_turn"] is False for item in socket.sent if "inputs" in item)
    assert socket.sent[-1] == {"close_socket": True}
    assert calls[0][0] == provider.ELEVENLABS_REALTIME_URL
    assert calls[0][1]["headers"] == {"xi-api-key": "PRIVATE_KEY"}
    assert "PRIVATE_KEY" not in json.dumps(socket.sent)
    assert len(calls) == 1 and socket.closed and clients[0].closed


@pytest.mark.asyncio
async def test_cancel_never_flushes_or_drains_and_releases_pending_read(transport):
    socket, calls, clients = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved text. ")
    pending = asyncio.create_task(connection.receive())
    await asyncio.sleep(0)
    await connection.cancel()
    with pytest.raises(provider.ElevenLabsRealtimeError):
        await pending
    await connection.cancel()
    assert not any("flush" in item or "close_socket" in item for item in socket.sent)
    assert len(calls) == 1 and socket.closed and clients[0].closed
    with pytest.raises(provider.ElevenLabsRealtimeError):
        await connection.append_text("Never replay.")


@pytest.mark.asyncio
async def test_consumer_close_and_task_cancel_abort_without_generation_control(transport):
    socket, _, clients = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved text.")
    socket.emit(audio())
    async with aclosing(connection.audio_events()) as events:
        assert (await anext(events)).audio_bytes
    assert socket.closed and clients[0].closed
    assert not any("close_socket" in item for item in socket.sent)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {}, [], "PRIVATE", {"audio": "bad!PRIVATE"}, {"audio": "", "unknown": None}, {"audio": 1},
    {"error": "PRIVATE BODY KEY INPUT"}, {"error_message": "PRIVATE"},
    {"is_final": "true"}, {"is_final_audio_for_turn": 1}, {"is_final": True},
    {"alignment": {}}, {"alignment": {"chars": ["x"], "char_start_times_ms": [float("nan")], "char_durations_ms": [1]}},
    {"alignment": {"chars": ["x"], "char_start_times_ms": [False], "char_durations_ms": [1]}},
    {"alignment": {"chars": ["x"], "char_start_times_ms": [], "char_durations_ms": [1]}},
])
async def test_bad_provider_frames_fail_safely_once_and_close(transport, payload, caplog):
    socket, calls, clients = transport
    connection = session()
    await connection.open()
    socket.emit(payload)
    with pytest.raises(provider.ElevenLabsRealtimeError) as failure:
        await connection.receive()
    assert "PRIVATE" not in str(failure.value) + repr(failure.value) + caplog.text
    assert failure.value.__cause__ is None
    assert len(calls) == 1 and socket.closed and clients[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.BINARY])
async def test_stream_requires_final_before_disconnect(transport, kind):
    socket, _, clients = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved.")
    await connection.finish_input()
    socket.emit({}, kind=kind)
    with pytest.raises(provider.ElevenLabsRealtimeError, match="truncated_stream"):
        await connection.receive()
    assert socket.closed and clients[0].closed


@pytest.mark.asyncio
async def test_invalid_json_oversized_wire_audio_and_cumulative_audio_are_bounded(transport, monkeypatch):
    socket, _, clients = transport
    connection = session(max_audio_bytes=4)
    await connection.open()
    socket.frames.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data="PRIVATE INVALID JSON"))
    with pytest.raises(provider.ElevenLabsRealtimeError, match="invalid_event"):
        await connection.receive()
    assert clients[0].closed
    # Normalization checks are pure and cannot trigger another provider attempt.
    for raw in [" " * (provider.MAX_EVENT_BYTES + 1), json.dumps(audio(b"x" * (provider.MAX_AUDIO_CHUNK_BYTES + 1)))]:
        with pytest.raises(provider.ElevenLabsRealtimeError):
            connection._normalize(raw)
    assert connection._normalize(json.dumps(audio(b"1234"))).audio_bytes == b"1234"
    with pytest.raises(provider.ElevenLabsRealtimeError, match="audio_limit"):
        connection._normalize(json.dumps(audio(b"5")))


@pytest.mark.asyncio
async def test_alignment_is_bounded_and_does_not_claim_a_timebase(transport):
    socket, _, _ = transport
    connection = session()
    await connection.open()
    socket.emit({**audio(), "alignment": {"chars": ["H", "i"], "char_start_times_ms": [0, 50], "char_durations_ms": [50, 60]}})
    event = await connection.receive()
    assert event.alignment.char_start_times_ms == (0, 50)
    assert event.alignment.timebase == "provider_unspecified"
    assert "ID3" not in repr(event) and "chars=" not in repr(event)
    await connection.cancel()


@pytest.mark.asyncio
async def test_input_limits_and_send_failure_never_count_unsent_text_or_retry(transport):
    socket, calls, clients = transport
    connection = session(max_input_characters=4, max_input_count=1)
    await connection.open()
    for text in ("", "   ", "12345"):
        with pytest.raises(provider.ElevenLabsRealtimeError):
            await connection.append_text(text)
    with pytest.raises(provider.ElevenLabsRealtimeError):
        await connection.append_text("1", new_turn=True)
    socket.send_error = True
    with pytest.raises(provider.ElevenLabsRealtimeError, match="send_failed"):
        await connection.append_text("1234")
    assert connection.input_count == connection.submitted_characters == 0
    assert len(calls) == 1 and clients[0].closed


@pytest.mark.asyncio
async def test_cumulative_input_limits_remain_exact_with_concurrent_writers(transport):
    socket, _, _ = transport
    connection = session(max_input_characters=5, max_input_count=2)
    await connection.open()
    await asyncio.gather(connection.append_text(" a "), connection.append_text("🙂 "))
    assert connection.submitted_characters == 5 and connection.input_count == 2
    with pytest.raises(provider.ElevenLabsRealtimeError, match="input_limit"):
        await connection.append_text("x")
    assert len([item for item in socket.sent if "inputs" in item]) == 2
    await connection.cancel()


@pytest.mark.asyncio
async def test_receive_stall_and_cancelled_receive_release_transport(transport):
    socket, _, clients = transport
    connection = session(receive_timeout_seconds=0.01)
    await connection.open()
    with pytest.raises(provider.ElevenLabsRealtimeError, match="receive_timeout"):
        await connection.receive()
    assert socket.closed and clients[0].closed


@pytest.mark.asyncio
async def test_keepalive_uses_control_only_and_stops_after_finish_input(transport):
    socket, _, _ = transport
    connection = session(keepalive_seconds=0.005)
    await connection.open()
    await asyncio.sleep(0.02)
    assert {"keep_alive": True} in socket.sent
    assert not any("inputs" in item or "flush" in item for item in socket.sent)
    await connection.append_text("Approved.")
    await connection.finish_input()
    sent = len(socket.sent)
    await asyncio.sleep(0.02)
    assert len(socket.sent) == sent
    await connection.cancel()


@pytest.mark.asyncio
async def test_vault_first_credentials_and_safe_failure(transport, monkeypatch, caplog):
    _, calls, _ = transport
    monkeypatch.setenv("SECRET__ELEVENLABS__API_KEY", "environment-key")

    class Vault:
        async def get_secret(self, **kwargs):
            assert kwargs == {"secret_path": "kv/data/providers/elevenlabs", "secret_key": "api_key"}
            return "vault-key"

    connection = provider.ElevenLabsRealtimeSession(voice_id="curated", secrets_manager=Vault())
    await connection.open()
    assert calls[0][1]["headers"] == {"xi-api-key": "vault-key"}
    await connection.cancel()
    assert "vault-key" not in caplog.text


@pytest.mark.asyncio
async def test_cancel_during_vault_lookup_never_opens_transport(transport):
    _, calls, _ = transport
    entered = asyncio.Event()

    class Vault:
        async def get_secret(self, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    connection = provider.ElevenLabsRealtimeSession(voice_id="curated", secrets_manager=Vault())
    opening = asyncio.create_task(connection.open())
    await entered.wait()
    await connection.cancel()
    assert opening.cancelled()
    assert calls == []


@pytest.mark.asyncio
async def test_cancel_receive_task_and_concurrent_reader_fail_safely(transport):
    socket, _, clients = transport
    connection = session()
    await connection.open()
    pending = asyncio.create_task(connection.receive())
    await asyncio.sleep(0)
    with pytest.raises(provider.ElevenLabsRealtimeError, match="concurrent_receive"):
        await connection.receive()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert socket.closed and clients[0].closed
    assert not any("flush" in item or "close_socket" in item for item in socket.sent)


@pytest.mark.asyncio
async def test_handshake_failure_is_safe_and_not_retried(transport, monkeypatch, caplog):
    _, calls, clients = transport

    async def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("PRIVATE AUTH KEY BODY")

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", fail)
    connection = session()
    with pytest.raises(provider.ElevenLabsRealtimeError, match="handshake_failed") as failure:
        await connection.open()
    assert failure.value.__cause__ is None
    assert "PRIVATE" not in str(failure.value) + caplog.text
    assert len(calls) == 1 and clients[0].closed


@pytest.mark.asyncio
async def test_stalled_send_is_not_counted_or_retried(transport):
    socket, calls, clients = transport
    connection = session(send_timeout_seconds=0.01)
    await connection.open()

    async def stall(payload):
        await asyncio.Event().wait()

    socket.send_json = stall
    with pytest.raises(provider.ElevenLabsRealtimeError, match="send_failed"):
        await connection.append_text("Approved input.")
    assert connection.input_count == connection.submitted_characters == 0
    assert len(calls) == 1 and socket.closed and clients[0].closed


@pytest.mark.asyncio
async def test_premature_final_and_empty_drained_final_fail(transport):
    socket, _, _ = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved.")
    await connection.finish_input()
    socket.emit({"is_final": True})
    with pytest.raises(provider.ElevenLabsRealtimeError, match="unexpected_final"):
        await connection.receive()
    assert socket.closed


@pytest.mark.asyncio
async def test_session_deadline_ends_idle_transport(transport):
    socket, _, clients = transport
    connection = session(max_session_seconds=0.01, keepalive_seconds=0.005)
    await connection.open()
    await asyncio.sleep(0.03)
    assert socket.closed and clients[0].closed
    with pytest.raises(provider.ElevenLabsRealtimeError):
        await connection.receive()


@pytest.mark.asyncio
async def test_no_credentials_never_opens_and_vault_errors_do_not_log_payload(transport, caplog):
    _, calls, _ = transport

    class Vault:
        async def get_secret(self, **kwargs):
            raise RuntimeError("PRIVATE KEY BODY")

    connection = provider.ElevenLabsRealtimeSession(voice_id="curated", secrets_manager=Vault())
    with pytest.raises(provider.ElevenLabsRealtimeError, match="credentials_unavailable"):
        await connection.open()
    assert calls == [] and "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_audio", [None, ""])
async def test_nullable_terminal_audio_drains_only_with_explicit_final(transport, empty_audio):
    socket, _, clients = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved.")
    socket.emit(audio())
    assert (await connection.receive()).audio_bytes
    socket.emit({"audio": empty_audio, "alignment": None, "is_final_audio_for_turn": True})
    marker = await connection.receive()
    assert marker.final_for_turn and not marker.final and not marker.audio_bytes
    assert not socket.closed
    await connection.finish_input()
    socket.emit({"audio": empty_audio, "alignment": None, "error": None, "error_message": None, "is_final": True})
    final = await connection.receive()
    assert final.final and not final.audio_bytes
    assert socket.closed and clients[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"audio": None}, {"audio": ""}, {"audio": None, "is_final": False},
    {"audio": "", "is_final_audio_for_turn": False}, {"audio": None, "is_final": True},
    {"audio": "", "is_final": True},
])
async def test_empty_audio_without_successful_drain_does_not_establish_final(transport, payload):
    socket, _, _ = transport
    connection = session()
    await connection.open()
    socket.emit(payload)
    if payload.get("audio") == "" and payload.get("is_final") is not True:
        event = await connection.receive()
        assert not event.audio_bytes and not event.final and not event.final_for_turn
        assert connection.audio_bytes_received == 0
        socket.emit({}, kind=aiohttp.WSMsgType.CLOSED)
    with pytest.raises(provider.ElevenLabsRealtimeError):
        await connection.receive()
    assert socket.closed


@pytest.mark.asyncio
async def test_diagnostic_shape_contains_only_allowlisted_names_types_and_lengths(transport):
    socket, _, _ = transport
    connection = session()
    await connection.open()
    socket.emit({"error": {"PRIVATE_PROVIDER_KEY": "PRIVATE_AUTH_BODY"}, "message": "PRIVATE_TEXT",
                 "PRIVATE_UNKNOWN_FIELD": "PRIVATE_AUDIO"})
    with pytest.raises(provider.ElevenLabsRealtimeError, match="provider_error"):
        await connection.receive()
    diagnostic = json.dumps(connection.last_event_shape)
    assert "PRIVATE" not in diagnostic
    assert connection.last_event_shape["fields"] == {
        "error": {"type": "object", "length": 1}, "message": {"type": "string", "length": 12}}
    assert connection.last_event_shape["unknown_field_count"] == 1


@pytest.mark.asyncio
async def test_real_empty_audio_frame_between_chunks_and_during_drain_requires_real_final(transport):
    socket, _, clients = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved.")
    socket.emit(audio(b"ID3first"))
    # Exact safe shape captured by the authorized real-provider probe.
    socket.frames.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data='{"audio":""}'))
    socket.emit(audio(b"next-audio"))
    assert (await connection.receive()).audio_bytes == b"ID3first"
    empty = await connection.receive()
    assert empty == provider.ElevenLabsRealtimeEvent()
    assert connection.audio_bytes_received == len(b"ID3first")
    assert not socket.closed
    assert (await connection.receive()).audio_bytes == b"next-audio"
    await connection.finish_input()
    socket.emit({"audio": "", "alignment": None, "error": None, "is_final": False})
    assert not (await connection.receive()).final
    assert not socket.closed
    socket.emit({"is_final": True})
    assert (await connection.receive()).final
    assert connection.audio_bytes_received == len(b"ID3firstnext-audio")
    assert socket.closed and clients[0].closed


@pytest.mark.asyncio
async def test_noop_stream_cannot_extend_session_lifetime_or_prove_generated_output(transport, monkeypatch):
    socket, _, clients = transport
    clock = [100.0]
    monkeypatch.setattr(provider, "monotonic", lambda: clock[0])
    connection = session(max_session_seconds=1)
    await connection.open()
    await connection.append_text("Approved.")
    for _ in range(3):
        clock[0] += 0.2
        socket.emit({"audio": ""})
        assert not (await connection.receive()).audio_bytes
    assert connection.audio_bytes_received == 0
    clock[0] += 1
    socket.emit({"audio": ""})
    with pytest.raises(provider.ElevenLabsRealtimeError, match="session_timeout"):
        await connection.receive()
    assert socket.closed and clients[0].closed


@pytest.mark.asyncio
async def test_noop_followed_by_empty_drained_final_is_still_not_success(transport):
    socket, _, _ = transport
    connection = session()
    await connection.open()
    await connection.append_text("Approved.")
    socket.emit({"audio": ""})
    assert not (await connection.receive()).final
    await connection.finish_input()
    socket.emit({"is_final": True})
    with pytest.raises(provider.ElevenLabsRealtimeError, match="unexpected_final"):
        await connection.receive()
