"""Single-request transient speech delivery and cancellation contracts."""
import asyncio
import base64
import json
from dataclasses import asdict
from uuid import UUID

import httpx
import pytest

from backend.apps.audio.assistant_speech import live_stream
from backend.shared.python_utils.assistant_speech_audio import validate_assistant_speech_audio_event


CONTEXT = {
    "chat_id": "11111111-1111-4111-8111-111111111111",
    "message_id": "d" * 64,
    "voice_call_id": "c" * 32, "segment_id": "a" * 64, "user_id_hash": "b" * 64,
    "sequence": 3, "kind": "voice_prose_clause", "source_version": 7, "execution_version": 11,
    # Private execution identity must never enter a client-facing event.
    "lease_id": "PRIVATE-LEASE", "attempt_id": "PRIVATE-ATTEMPT",
}


class SpeechClient:
    def __init__(self, chunks=(), *, stall=False, failure=None):
        self.chunks = chunks
        self.stall = stall
        self.failure = failure
        self.calls = []
        self.closed = False
        self.waiting = asyncio.Event()
        self.read_cancelled = False
        self.chunks_read = 0

    async def stream_text_to_speech(self, **request):
        self.calls.append(request)
        try:
            for chunk in self.chunks:
                self.chunks_read += 1
                yield chunk
            if self.failure:
                raise self.failure
            if self.stall:
                self.waiting.set()
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.read_cancelled = True
            raise
        finally:
            self.closed = True


class Events:
    def __init__(self):
        self.items = []

    async def publish(self, channel, event):
        validate_assistant_speech_audio_event(event, channel=channel)
        self.items.append(event)
        return True


async def active():
    return None


async def generate(client, events, *, context=None, ensure_active=active):
    return await live_stream.generate_live_speech(
        client=client, text="PRIVATE COMPLETE TEXT", voice_id="test-voice",
        context=CONTEXT if context is None else context,
        publish_event=events.publish, ensure_active=ensure_active,
    )


# contract-test: direct surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.privacy.transient-plaintext-encrypted-audio
async def test_one_synthesis_delivers_exact_bytes_and_returns_only_completion_accounting(caplog):
    audio = b"ID3" + b"A" * (live_stream.MAX_AUDIO_CHUNK_BYTES + 41)
    client = SpeechClient([audio, b"tail"])
    events = Events()
    result = await generate(client, events)
    payloads = [event["payload"] for event in events.items]
    assert [item["phase"] for item in payloads] == ["start", "chunk", "chunk", "chunk", "end"]
    assert [item["chunk_index"] for item in payloads] == [0, 0, 1, 2, 3]
    chunks = [base64.b64decode(item["audio_data"], validate=True) for item in payloads if item["phase"] == "chunk"]
    assert all(0 < len(chunk) <= 32 * 1024 for chunk in chunks)
    assert b"".join(chunks) == audio + b"tail"
    assert asdict(result) == {"submitted_characters": len("PRIVATE COMPLETE TEXT"),
        "generated_audio_bytes": len(audio + b"tail"), "chunk_count": 3}
    assert len(client.calls) == 1 and client.closed
    assert client.calls[0] == {"text": "PRIVATE COMPLETE TEXT", "voice_id": "test-voice", "model": "voxtral-mini-tts-3-0"}
    attempt = payloads[0]["attempt_id"]
    assert str(UUID(attempt)) == attempt
    assert all(item["attempt_id"] == attempt and item["source_version"] == 7
               and item["execution_version"] == 11 and item["sequence"] == 3 for item in payloads)
    assert all("audio_data" not in item for item in payloads if item["phase"] != "chunk")
    assert "PRIVATE" not in str(events.items) + caplog.text


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.parametrize("failure_at", [1, 2, 5])
@pytest.mark.parametrize("failure", ["false", "exception", "timeout"])
async def test_live_publication_failure_aborts_without_continuing_or_retrying(monkeypatch, failure_at, failure, caplog):
    monkeypatch.setattr(live_stream, "PUBLISH_TIMEOUT_SECONDS", 0.01)
    class FailedEvents(Events):
        async def publish(self, channel, event):
            await super().publish(channel, event)
            if len(self.items) == failure_at:
                if failure == "exception":
                    raise RuntimeError("PRIVATE CACHE PAYLOAD")
                if failure == "timeout":
                    await asyncio.Event().wait()
                return False
            return True
    client = SpeechClient([b"ID3first", b"second", b"third"])
    events = FailedEvents()
    with pytest.raises(live_stream.LiveSpeechDeliveryUnavailable, match="^Live speech delivery unavailable$"):
        await generate(client, events)
    if failure_at == 1:
        assert not client.calls and client.chunks_read == 0
    else:
        assert len(client.calls) == 1 and client.closed
        assert client.chunks_read == (1 if failure_at == 2 else 3)
    assert len(events.items) == failure_at
    assert "PRIVATE" not in caplog.text


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.failure.nonblocking-visible-resumable
async def test_cancelling_stalled_provider_cancels_read_before_close_and_emits_error():
    client, events = SpeechClient([b"ID3first"], stall=True), Events()
    task = asyncio.create_task(generate(client, events))
    await asyncio.wait_for(client.waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.read_cancelled and client.closed and len(client.calls) == 1
    assert [item["payload"]["phase"] for item in events.items] == ["start", "chunk", "error"]
    assert events.items[-1]["payload"]["chunk_index"] == 1


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.failure.nonblocking-visible-resumable
async def test_lease_loss_during_stalled_provider_is_polled_and_closes_pending_read(monkeypatch):
    monkeypatch.setattr(live_stream, "ACTIVE_CHECK_INTERVAL_SECONDS", 0.01)
    class LeaseLost(Exception):
        pass
    checks = 0
    async def ensure_active():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise LeaseLost
    client, events = SpeechClient(stall=True), Events()
    with pytest.raises(LeaseLost):
        await asyncio.wait_for(generate(client, events, ensure_active=ensure_active), 1)
    assert client.closed and client.read_cancelled and checks == 2 and len(client.calls) == 1
    assert [item["payload"]["phase"] for item in events.items] == ["start", "error"]


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive
async def test_fast_provider_deltas_check_lease_at_start_and_end_without_per_delta_queries(monkeypatch):
    monkeypatch.setattr(live_stream, "monotonic", lambda: 0)
    checks = 0
    async def ensure_active():
        nonlocal checks
        checks += 1
    client, events = SpeechClient([b"ID3"] + [b"x"] * 50), Events()
    result = await generate(client, events, ensure_active=ensure_active)
    assert checks == 2 and result.generated_audio_bytes == 53 and result.chunk_count == 51
    assert events.items[-1]["payload"]["phase"] == "end"


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.parametrize("at_end", [False, True])
async def test_inactive_execution_never_returns_completion_or_end(at_end):
    checks = 0
    async def ensure_active():
        nonlocal checks
        checks += 1
        if checks == (2 if at_end else 1):
            raise RuntimeError("Execution inactive")
    client, events = SpeechClient([b"ID3sample"]), Events()
    with pytest.raises(RuntimeError, match="Execution inactive"):
        await generate(client, events, ensure_active=ensure_active)
    assert not any(item["payload"]["phase"] == "end" for item in events.items)
    assert events.items[-1]["payload"]["phase"] == "error"
    assert len(client.calls) == (1 if at_end else 0)
    assert client.closed is at_end


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.execution.first-segment-progressive
@pytest.mark.parametrize("chunks", [[], [b""], ["PRIVATE NON-BYTES"]])
async def test_empty_or_invalid_provider_audio_returns_no_completion(chunks, caplog):
    client, events = SpeechClient(chunks), Events()
    with pytest.raises(RuntimeError, match="(Empty|Invalid) live speech audio"):
        await generate(client, events)
    assert client.closed and len(client.calls) == 1
    assert events.items[-1]["payload"]["phase"] == "error"
    assert "PRIVATE" not in str(events.items) + caplog.text


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.execution.first-segment-progressive
async def test_partial_provider_failure_closes_stream_without_completing_or_retrying(caplog):
    client = SpeechClient([b"ID3partial"], failure=RuntimeError("PRIVATE UPSTREAM ERROR"))
    events = Events()
    with pytest.raises(RuntimeError):
        await generate(client, events)
    assert client.closed and len(client.calls) == 1
    assert [item["payload"]["phase"] for item in events.items] == ["start", "chunk", "error"]
    assert "PRIVATE" not in str(events.items) + caplog.text


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.parametrize("extra", [b"", b"x"])
async def test_cumulative_audio_limit_is_four_mib_without_retaining_an_asset(extra):
    audio = b"ID3" + b"x" * (4 * 1024 * 1024 - 3)
    client, events = SpeechClient([audio] + ([extra] if extra else [])), Events()
    if extra:
        with pytest.raises(RuntimeError, match="Live speech audio limit exceeded"):
            await generate(client, events)
        assert events.items[-1]["payload"]["phase"] == "error"
    else:
        result = await generate(client, events)
        assert result.generated_audio_bytes == len(audio) and result.chunk_count == 128
        assert set(asdict(result)) == {"submitted_characters", "generated_audio_bytes", "chunk_count"}
        assert events.items[-1]["payload"]["phase"] == "end"
    assert client.closed and len(client.calls) == 1
    assert len([event for event in events.items if event["payload"]["phase"] == "chunk"]) == 128


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.privacy.transient-plaintext-encrypted-audio
async def test_chunk_count_is_bounded_at_4096_without_a_second_generation():
    client, events = SpeechClient([b"ID3"] + [b"x"] * 4096), Events()
    with pytest.raises(RuntimeError, match="Live speech chunk limit exceeded"):
        await generate(client, events)
    assert client.closed and len(client.calls) == 1
    assert len(events.items) == 4098  # start, 4096 valid chunks, error
    assert events.items[-1]["payload"]["phase"] == "error"
    assert events.items[-1]["payload"]["chunk_index"] == 4096


# contract-test: supporting surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.parametrize("field,value", [("source_version", 0), ("execution_version", True),
    ("sequence", -1), ("voice_call_id", "invalid"), ("user_id_hash", "PRIVATE")])
async def test_invalid_metadata_is_rejected_before_generation_or_live_publication(field, value):
    client, events = SpeechClient([b"ID3sample"]), Events()
    with pytest.raises(ValueError):
        await generate(client, events, context={**CONTEXT, field: value})
    assert not client.calls and not events.items


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive
async def test_each_generation_has_a_new_attempt_identity_independent_of_private_lease():
    events = Events()
    await generate(SpeechClient([b"ID3sample"]), events)
    await generate(SpeechClient([b"ID3sample"]), events)
    attempts = [item["payload"]["attempt_id"] for item in events.items if item["payload"]["phase"] == "start"]
    assert len(set(attempts)) == 2
    assert all(str(UUID(attempt)) == attempt for attempt in attempts)
    assert "PRIVATE" not in str(events.items)


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.parametrize("complete", [False, True])
async def test_http_sse_provider_and_live_helper_share_one_request_and_require_done(monkeypatch, complete):
    original_client = httpx.AsyncClient
    calls = []
    class Body(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            for audio in (b"I", b"D", b"3first", b"second"):
                data = json.dumps({"audio_data": base64.b64encode(audio).decode()})
                yield f"event: speech.audio.delta\ndata: {data}\n\n".encode()
            if complete:
                yield b'event: speech.audio.done\ndata: {"usage": {}}\n\n'
        async def aclose(self):
            self.closed = True
    body = Body()
    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs))
    client, events = live_stream.MistralSpeechClient(api_key="test-key"), Events()
    if complete:
        result = await generate(client, events)
        assert asdict(result) == {"submitted_characters": len("PRIVATE COMPLETE TEXT"),
            "generated_audio_bytes": len(b"ID3firstsecond"), "chunk_count": 2}
        assert events.items[-1]["payload"]["phase"] == "end"
    else:
        with pytest.raises(RuntimeError, match="^Mistral speech generation failed$"):
            await generate(client, events)
        assert events.items[-1]["payload"]["phase"] == "error"
    delivered = b"".join(base64.b64decode(event["payload"]["audio_data"])
        for event in events.items if event["payload"]["phase"] == "chunk")
    assert delivered == b"ID3firstsecond"
    assert len(calls) == 1 and body.closed
    assert json.loads(calls[0].content)["stream"] is True


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.first-segment-progressive
async def test_waiting_confirmation_is_streamed_transiently_with_exact_negative_sequence():
    client, events = SpeechClient([b"ID3waiting"]), Events()
    result = await generate(client, events, context={**CONTEXT, "kind": "waiting_confirmation", "sequence": -1})
    assert result.generated_audio_bytes == len(b"ID3waiting") and result.chunk_count == 1
    assert [item["payload"]["phase"] for item in events.items] == ["start", "chunk", "end"]
    assert all(item["payload"]["kind"] == "waiting_confirmation" and item["payload"]["sequence"] == -1
               for item in events.items)
    assert client.closed and len(client.calls) == 1


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.first-segment-progressive
@pytest.mark.parametrize("kind,sequence", [("waiting_confirmation", 0), ("voice_prose_clause", -1), ("prose_paragraph", 0)])
async def test_live_helper_rejects_unsupported_kind_sequence_pairs_before_provider(kind, sequence):
    client, events = SpeechClient([b"ID3sample"]), Events()
    with pytest.raises(ValueError):
        await generate(client, events, context={**CONTEXT, "kind": kind, "sequence": sequence})
    assert not client.calls and not events.items
