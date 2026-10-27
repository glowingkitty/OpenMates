"""Speech provider protocol tests; no network or paid inference."""
import base64
import asyncio
from contextlib import aclosing
import json

import httpx
import pytest

from backend.shared.providers import mistral_speech as provider
from backend.shared.providers.mistral_speech import MistralSpeechClient


# contract-test: supporting surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_sends_only_segment_and_voice_and_decodes_mp3(monkeypatch):
    original = httpx.AsyncClient
    async def handle(request):
        import json
        assert str(request.url) == "https://api.mistral.ai/v1/audio/speech"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {"model": "voxtral-mini-tts-3-0",
            "input": "Hello.", "voice_id": "voice_3150", "response_format": "mp3", "stream": False}
        return httpx.Response(200, json={"audio_data": base64.b64encode(b"ID3sample").decode()})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    result = await MistralSpeechClient(api_key="test-key").text_to_speech(text="Hello.", voice_id="voice_3150")
    assert result.audio_bytes == b"ID3sample"
    assert result.mime_type == "audio/mpeg"


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(429, {"secret": "private diagnostic"}),
    (200, {"audio_data": "invalid!"}), (200, {"audio_data": ""}), (200, {}),
    (200, {"audio_data": base64.b64encode(b"not audio").decode()})])
async def test_provider_errors_are_safe_and_never_implicitly_retried(monkeypatch, status, payload):
    original = httpx.AsyncClient
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    with pytest.raises(RuntimeError, match="^Mistral speech generation failed$"):
        await MistralSpeechClient(api_key="test-key").text_to_speech(text="Hello.", voice_id="voice_3150")
    assert len(calls) == 1


def speech_event(name, payload):
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


def audio_event(audio):
    return speech_event("speech.audio.delta", {"audio_data": base64.b64encode(audio).decode()})


DONE = speech_event("speech.audio.done", {"usage": {"input_tokens": 1}})


class SpeechStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, stall=False):
        self.chunks = chunks
        self.closed = False
        self.stall = stall
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.stall:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def mock_stream(monkeypatch, chunks, *, status=200, content_type="text/event-stream", stall=False,
                stream_type=SpeechStream):
    original = httpx.AsyncClient
    stream = stream_type(chunks, stall=stall)
    calls = []
    clients = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"content-type": content_type}, stream=stream)
    def client(**kwargs):
        result = original(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(result)
        return result
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return stream, calls, clients


# contract-test: supporting surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
@pytest.mark.parametrize("audio_parts", [[b"ID3first", b"second"], [b"I", b"D", b"3first", b"second"],
                                        [b"\xff", b"\xfb", b"\x90frame"]])
async def test_stream_posts_full_text_once_and_preserves_ordered_mp3_bytes(monkeypatch, audio_parts):
    body = b": keepalive\r\n\r\n" + b"".join(audio_event(audio) for audio in audio_parts) + DONE
    # Network boundaries can split field names, UTF-8, CRLF and JSON/base64.
    stream, calls, clients = mock_stream(monkeypatch, [body[i:i+7] for i in range(0, len(body), 7)])
    chunks = [chunk async for chunk in MistralSpeechClient(api_key="test-key").stream_text_to_speech(
        text="Complete text. Another sentence.", voice_id="gb_jane_neutral")]
    assert b"".join(chunks) == b"".join(audio_parts)
    assert all(chunks)
    assert len(calls) == 1
    assert json.loads(calls[0].content) == {"model": "voxtral-mini-tts-3-0", "input": "Complete text. Another sentence.",
        "voice_id": "gb_jane_neutral", "response_format": "mp3", "stream": True}
    assert calls[0].headers["authorization"] == "Bearer test-key"
    assert stream.closed and clients[0].is_closed


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
async def test_stream_yields_before_completion_and_early_close_releases_http(monkeypatch):
    stream, calls, clients = mock_stream(monkeypatch, [audio_event(b"ID3first")], stall=True)
    async with aclosing(MistralSpeechClient(api_key="key").stream_text_to_speech(text="Hi.", voice_id="voice")) as audio:
        assert await asyncio.wait_for(anext(audio), 1) == b"ID3first"
        assert not stream.waiting.is_set() and not stream.closed
    assert stream.closed and clients[0].is_closed and len(calls) == 1


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
async def test_stream_cancellation_closes_inflight_response_and_client(monkeypatch):
    stream, calls, clients = mock_stream(monkeypatch, [], stall=True)
    audio = MistralSpeechClient(api_key="key").stream_text_to_speech(text="Hi.", voice_id="voice")
    consumer = asyncio.create_task(anext(audio))
    await asyncio.wait_for(stream.waiting.wait(), 1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert stream.closed and clients[0].is_closed and len(calls) == 1


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    b"", DONE, audio_event(b"ID3partial"), audio_event(b"ID") + DONE,
    audio_event(b"not MP3") + DONE, audio_event(b"\xffwrong") + DONE,
    audio_event(b"") + DONE, speech_event("speech.audio.delta", {"audio_data": "invalid!"}) + DONE,
    speech_event("speech.audio.delta", {}) + DONE,
    speech_event("speech.audio.delta", {"audio_data": 123}) + DONE,
    speech_event("speech.audio.error", {"message": "PRIVATE TEXT KEY AUDIO"}),
    b"event: speech.audio.delta\ndata: PRIVATE INVALID JSON\n\n",
    b"event: speech.audio.delta\ndata: []\n\n",
    b"event: speech.audio.delta\ndata: {}\n",  # missing terminating blank line
    b"event: speech.audio.delta\n\n",
    b"event: speech.audio.delta\ndata: {\xff}\n\n",
    speech_event("speech.audio.delta", {"type": "PRIVATE", "audio_data": "SUQz"}),
])
# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
async def test_invalid_streams_fail_safely_once_and_release_resources(monkeypatch, body, caplog):
    stream, calls, clients = mock_stream(monkeypatch, [body])
    with pytest.raises(RuntimeError, match="^Mistral speech generation failed$"):
        _ = [part async for part in MistralSpeechClient(api_key="PRIVATE KEY").stream_text_to_speech(
            text="PRIVATE INPUT", voice_id="voice")]
    assert stream.closed and clients[0].is_closed and len(calls) == 1
    assert "PRIVATE" not in caplog.text


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
@pytest.mark.parametrize("status,content_type", [(429, "text/event-stream"), (200, "application/json")])
async def test_stream_rejects_request_errors_and_non_sse_without_retry(monkeypatch, status, content_type):
    stream, calls, clients = mock_stream(monkeypatch, [b"PRIVATE PROVIDER BODY"], status=status, content_type=content_type)
    with pytest.raises(RuntimeError, match="^Mistral speech generation failed$"):
        _ = [part async for part in MistralSpeechClient(api_key="key").stream_text_to_speech(text="Hi.", voice_id="voice")]
    assert stream.closed and clients[0].is_closed and len(calls) == 1


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
@pytest.mark.parametrize("limit,body", [
    ("MAX_SPEECH_EVENT_BYTES", b"data: " + b"A" * 512),
    ("MAX_SPEECH_EVENT_BYTES", b"data: " + b"A\n" * 512 + b"\n"),
    ("MAX_SPEECH_STREAM_BYTES", b": comment\n\n" * 32),
    ("MAX_SPEECH_AUDIO_BYTES", audio_event(b"ID3" + b"A" * 64) + DONE),
])
async def test_stream_bounds_unfinished_lines_events_wire_and_decoded_audio(monkeypatch, limit, body):
    monkeypatch.setattr(provider, limit, 64)
    stream, calls, clients = mock_stream(monkeypatch, [body[i:i+16] for i in range(0, len(body), 16)])
    with pytest.raises(RuntimeError, match="^Mistral speech generation failed$"):
        _ = [part async for part in MistralSpeechClient(api_key="key").stream_text_to_speech(text="Hi.", voice_id="voice")]
    assert stream.closed and clients[0].is_closed and len(calls) == 1


# contract-test: supporting surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_stream_resolves_vault_secret_without_chat_dependencies(monkeypatch):
    class Secrets:
        async def get_secret(self, path, name):
            assert (path, name) == (provider.MISTRAL_SECRET_PATH, "api_key")
            return "vault-key"
    stream, calls, _ = mock_stream(monkeypatch, [audio_event(b"ID3sample") + DONE])
    _ = [part async for part in MistralSpeechClient(secrets_manager=Secrets()).stream_text_to_speech(text="Hi.", voice_id="voice")]
    assert calls[0].headers["authorization"] == "Bearer vault-key" and stream.closed


# contract-test: supporting surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
@pytest.mark.parametrize("newline", [b"\n", b"\r", b"\r\n"])
async def test_stream_accepts_sse_line_endings_multiline_json_and_data_event_type(monkeypatch, newline):
    body = (b'data: {"type": "speech.audio.delta",\ndata: "audio_data": "SUQzc2FtcGxl"}\n\n' + DONE).replace(b"\n", newline)
    stream, _, _ = mock_stream(monkeypatch, [body[i:i+1] for i in range(len(body))])
    chunks = [part async for part in MistralSpeechClient(api_key="key").stream_text_to_speech(text="Hi.", voice_id="voice")]
    assert b"".join(chunks) == b"ID3sample" and stream.closed


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
@pytest.mark.parametrize("text,voice,key,error", [(" ", "voice", "key", ValueError),
    ("Hi.", "", "key", ValueError), ("Hi.", "voice", "IMPORTED_TO_VAULT", RuntimeError)])
async def test_invalid_stream_input_and_unavailable_key_do_not_start_http(monkeypatch, text, voice, key, error):
    _, calls, clients = mock_stream(monkeypatch, [])
    with pytest.raises(error):
        _ = [part async for part in MistralSpeechClient(api_key=key).stream_text_to_speech(text=text, voice_id=voice)]
    assert not calls and not clients


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
async def test_http_failure_after_first_audio_discards_completion_and_releases_http(monkeypatch):
    class FailingStream(SpeechStream):
        async def __aiter__(self):
            yield audio_event(b"ID3partial")
            raise httpx.ReadError("PRIVATE UPSTREAM AUDIO")
    stream, calls, clients = mock_stream(monkeypatch, [], stream_type=FailingStream)
    async with aclosing(MistralSpeechClient(api_key="key").stream_text_to_speech(text="Hi.", voice_id="voice")) as audio:
        assert await anext(audio) == b"ID3partial"
        with pytest.raises(RuntimeError, match="^Mistral speech generation failed$"):
            await anext(audio)
    assert stream.closed and clients[0].is_closed and len(calls) == 1
