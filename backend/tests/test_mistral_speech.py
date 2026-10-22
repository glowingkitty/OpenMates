"""Speech provider protocol tests; no network or paid inference."""
import base64

import httpx
import pytest

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
