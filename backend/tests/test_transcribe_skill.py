# backend/tests/test_transcribe_skill.py
#
# Unit tests for TranscribeSkill with automatic Gemini transcript correction.

import httpx
import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock, patch

from backend.apps.audio.skills.transcribe_skill import (
    GEMINI_CORRECTION_MODEL,
    GEMINI_TRANSCRIPT_TOOL_NAME,
    TranscribeRequestItem,
    TranscribeSkill,
    _normalize_provider_timings,
    _resolve_timestamp_option,
)

class DummyApp:
    def __init__(self):
        # Mock credits methods
        self.get_user_credits = AsyncMock(return_value=100)
        self.charge_user_credits = AsyncMock()


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction,videos.transcript.speech-input-timestamps-off
def test_timestamp_negotiation_preserves_omission_and_explicit_overrides():
    """Version negotiation must distinguish omitted options from explicit none."""
    unversioned = TranscribeRequestItem.model_validate({
        "s3_base_url": "http://api:8000/s3",
        "s3_key": "uploads/1/audio.webm.enc",
        "aes_nonce": "bm9uY2U=",
        "vault_wrapped_aes_key": "vault:wrapped:key",
    })
    versioned = TranscribeRequestItem.model_validate({
        "s3_base_url": "http://api:8000/s3",
        "s3_key": "uploads/2/audio.webm.enc",
        "aes_nonce": "bm9uY2U=",
        "vault_wrapped_aes_key": "vault:wrapped:key",
        "transcription_contract_version": 1,
    })

    assert "timestamps" not in unversioned.model_dump(exclude_unset=True)
    assert _resolve_timestamp_option(unversioned.model_dump(exclude_unset=True)) == "none"
    assert _resolve_timestamp_option(versioned.model_dump(exclude_unset=True)) == "word"
    assert _resolve_timestamp_option({"timestamps": "segment"}) == "segment"
    assert _resolve_timestamp_option({"timestamps": "none"}) == "none"
    with pytest.raises(ValueError, match="Unknown transcription_contract_version"):
        _resolve_timestamp_option({"transcription_contract_version": 2})
    with pytest.raises(ValueError, match="timestamps must"):
        _resolve_timestamp_option({"timestamps": []})
    for invalid_version in (True, "1"):
        with pytest.raises(ValidationError):
            TranscribeRequestItem.model_validate({
                "s3_base_url": "http://api:8000/s3",
                "s3_key": "uploads/3/audio.webm.enc",
                "aes_nonce": "bm9uY2U=",
                "vault_wrapped_aes_key": "vault:wrapped:key",
                "transcription_contract_version": invalid_version,
            })


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.anyio
async def test_invalid_timing_options_fail_before_secret_lookup_or_audio_access():
    skill = object.__new__(TranscribeSkill)
    secrets_manager = AsyncMock()

    request_id, results, error = await skill._process_single_transcribe_request(
        {
            "s3_key": "uploads/1/audio.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "_vault_key_id": "user_test",
            "transcription_contract_version": 1,
            "timestamps": "word",
            "language": "en",
        },
        "recording-1",
        secrets_manager,
    )

    assert request_id == "recording-1"
    assert results == []
    assert error == "language cannot be used with word timestamps"
    secrets_manager.get_secret.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction,videos.transcript.speech-input-timestamps-off
@pytest.mark.anyio
async def test_legacy_unversioned_transcription_is_untimed():
    skill = object.__new__(TranscribeSkill)
    skill._unwrap_aes_key = AsyncMock(return_value=b"dummy_aes_key_32_bytes")
    skill._fetch_and_decrypt_audio = AsyncMock(return_value=b"decrypted_audio_bytes")
    skill._transcribe_with_mistral = AsyncMock(return_value={"text": "Hello", "duration": 1.0})
    skill._extract_waveform = AsyncMock(return_value=None)

    secrets_manager = AsyncMock()
    secrets_manager.get_secret = AsyncMock(side_effect=["mistral-key", None])
    _request_id, results, error = await skill._process_single_transcribe_request(
        {
            "s3_key": "uploads/1/audio.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "_vault_key_id": "user_test",
        },
        "recording-1",
        secrets_manager,
    )

    assert error is None
    assert "segments" not in results[0]
    assert "words" not in results[0]
    assert skill._transcribe_with_mistral.await_args.kwargs["timestamps"] == "none"


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-results-and-billing
@pytest.mark.anyio
async def test_timed_transcript_uses_decoded_duration_not_whole_second_usage():
    skill = object.__new__(TranscribeSkill)
    skill._unwrap_aes_key = AsyncMock(return_value=b"test-key")
    skill._fetch_and_decrypt_audio = AsyncMock(return_value=b"audio")
    skill._transcribe_with_mistral = AsyncMock(return_value={
        "text": "Hello", "duration": 1,
        "segments": [{"start": 0.0, "end": 1.25, "text": "Hello"}],
    })
    skill._extract_waveform = AsyncMock(return_value={"duration_seconds": 1.5})
    secrets_manager = AsyncMock()
    secrets_manager.get_secret = AsyncMock(side_effect=["test-key", None])
    _, results, error = await skill._process_single_transcribe_request({
        "s3_key": "fixture", "aes_nonce": "fixture", "vault_wrapped_aes_key": "fixture",
        "_vault_key_id": "fixture", "transcription_contract_version": 1,
    }, "fixture", secrets_manager)
    assert error is None
    assert results[0]["duration_seconds"] == 1.5
    assert results[0]["words"][0]["end_seconds"] == 1.25


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-results-and-billing
def test_null_nested_words_returns_controlled_timing_error():
    with pytest.raises(ValueError, match="Invalid provider timing entries"):
        _normalize_provider_timings({
            "duration": 1.0,
            "segments": [{"start": 0.0, "end": 0.5, "text": "Hello", "words": None}],
        }, "word")


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-results-and-billing
@pytest.mark.anyio
async def test_invalid_provider_timings_are_not_successes_or_billable():
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )
    skill._unwrap_aes_key = AsyncMock(return_value=b"dummy_aes_key_32_bytes")
    skill._fetch_and_decrypt_audio = AsyncMock(return_value=b"decrypted_audio_bytes")
    skill._transcribe_with_mistral = AsyncMock(return_value={
        "text": "Hello",
        "duration": 1.0,
        "words": [{"start": 0.0, "end": 2.0, "word": "Hello"}],
    })

    secrets_manager = AsyncMock()
    secrets_manager.get_secret = AsyncMock(return_value="test-key")
    response = await skill.execute(
        requests=[{
            "id": "recording-1",
            "s3_base_url": "http://api:8000/s3",
            "s3_key": "uploads/1/audio.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "transcription_contract_version": 1,
        }],
        secrets_manager=secrets_manager,
        user_id="user-1",
        user_vault_key_id="vault-key-1",
    )

    assert response.results[0]["results"] == []
    assert "Invalid transcription timing" in (response.results[0]["error"] or "")
    app.charge_user_credits.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-results-and-billing
@pytest.mark.anyio
async def test_empty_timed_silence_is_visible_and_not_billable():
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )
    skill._unwrap_aes_key = AsyncMock(return_value=b"dummy_aes_key_32_bytes")
    skill._fetch_and_decrypt_audio = AsyncMock(return_value=b"decrypted_audio_bytes")
    skill._transcribe_with_mistral = AsyncMock(return_value={"text": "", "duration": 1.0})

    secrets_manager = AsyncMock()
    secrets_manager.get_secret = AsyncMock(return_value="test-key")
    response = await skill.execute(
        requests=[{
            "id": "recording-1",
            "s3_base_url": "http://api:8000/s3",
            "s3_key": "uploads/1/audio.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "transcription_contract_version": 1,
        }],
        secrets_manager=secrets_manager,
        user_id="user-1",
        user_vault_key_id="vault-key-1",
    )

    assert response.results[0]["results"] == []
    assert "timestamps_empty_silence" in (response.results[0]["error"] or "")
    app.charge_user_credits.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-results-and-billing
@pytest.mark.anyio
async def test_nonempty_transcript_without_requested_words_is_unavailable():
    skill = object.__new__(TranscribeSkill)
    skill._unwrap_aes_key = AsyncMock(return_value=b"dummy_aes_key_32_bytes")
    skill._fetch_and_decrypt_audio = AsyncMock(return_value=b"decrypted_audio_bytes")
    skill._transcribe_with_mistral = AsyncMock(return_value={
        "text": "Hello world",
        "duration": 1.0,
        "words": [],
    })

    secrets_manager = AsyncMock()
    secrets_manager.get_secret = AsyncMock(return_value="mistral-key")
    _request_id, results, error = await skill._process_single_transcribe_request(
        {
            "s3_key": "uploads/1/audio.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "_vault_key_id": "user_test",
            "transcription_contract_version": 1,
        },
        "recording-1",
        secrets_manager,
    )

    assert results == []
    assert error == "timestamps_unavailable"


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-results-and-billing,videos.transcript.audio-timestamps-and-correction
def test_provider_timings_normalize_word_segments_without_fabrication():
    normalized = _normalize_provider_timings(
        {
            "duration": 3.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello world"},
            ],
            "words": [
                {"start": 0.0, "end": 0.5, "word": "Hello"},
                {"start": 0.5, "end": 1.0, "word": "world"},
            ],
        },
        timestamps="word",
    )

    assert normalized == {
        "segments": [
            {"start_seconds": 0.0, "end_seconds": 1.0, "text": "Hello world"},
        ],
        "words": [
            {"start_seconds": 0.0, "end_seconds": 0.5, "text": "Hello"},
            {"start_seconds": 0.5, "end_seconds": 1.0, "text": "world"},
        ],
    }
    with pytest.raises(ValueError, match="Invalid provider timing"):
        _normalize_provider_timings(
            {"duration": 3.0, "words": [{"start": True, "end": 1.0, "word": "bad"}]},
            timestamps="word",
        )
    with pytest.raises(ValueError, match="timestamps_unavailable"):
        _normalize_provider_timings(
            {"duration": 3.0, "segments": [{"start": 0.0, "end": 1.0, "text": "Hello world"}]},
            timestamps="word",
        )
    for invalid_entry in (
        {"start": float("nan"), "end": 1.0, "word": "bad"},
        {"start": -0.1, "end": 1.0, "word": "bad"},
        {"start": 1.0, "end": 1.0, "word": "bad"},
        {"start": 0.0, "end": 3.1, "word": "bad"},
    ):
        with pytest.raises(ValueError, match="Invalid provider timing"):
            _normalize_provider_timings(
                {"duration": 3.0, "words": [invalid_entry]}, timestamps="word"
            )

    hidden = chr(0xE0001) + chr(0xE0048) + chr(0xE0069) + chr(0xE007F) + "\u202e"
    sanitized = _normalize_provider_timings(
        {"duration": 1.0, "words": [{"start": 0.0, "end": 1.0, "word": f"Hi{hidden}"}]},
        timestamps="word",
    )
    assert sanitized["words"][0]["text"] == "Hi"


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.anyio
async def test_mistral_word_timestamps_use_multipart_array_field():
    skill = object.__new__(TranscribeSkill)
    requests = []
    real_async_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "Hello", "usage": {"prompt_audio_seconds": 1.0}})

    def client_factory(*args, **kwargs):
        return real_async_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    with patch("backend.apps.audio.skills.transcribe_skill.httpx.AsyncClient", client_factory):
        result = await skill._transcribe_with_mistral(
            audio_bytes=b"audio",
            filename="recording.webm",
            mime_type="audio/webm",
            language=None,
            timestamps="word",
            mistral_api_key="test-key",
        )

    body = requests[0].content.decode("utf-8")
    assert 'name="timestamp_granularities"' in body
    assert 'name="timestamp_granularities[]"' not in body
    assert "\r\nword\r\n" in body
    assert result["duration"] == 1.0


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
def test_build_waveform_from_pcm_u8_returns_compact_envelope():
    """Waveform metadata should be compact, numeric, and independent of the audio file."""
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )

    waveform = skill._build_waveform_from_pcm_u8(
        bytes([128, 128, 255, 0, 180, 76, 128, 128]),
        duration_seconds=2.5,
        sample_count=4,
    )

    assert waveform is not None
    assert waveform["version"] == 1
    assert waveform["kind"] == "rms-envelope"
    assert waveform["duration_seconds"] == 2.5
    assert len(waveform["samples"]) == 4
    assert all(isinstance(sample, int) and 0 <= sample <= 100 for sample in waveform["samples"])


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
async def test_correct_transcript_with_gemini_success():
    """Test that _correct_transcript_with_gemini successfully parses and refines transcripts."""
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": GEMINI_TRANSCRIPT_TOOL_NAME,
                        "args": {
                            "title": "Search for green boxes",
                            "corrected_transcript": "Search for green boxes.",
                        },
                    }
                }]
            }
        }]
    })

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        raw = "umm search for yellow actually no let's search for green boxes"
        result = await skill._correct_transcript_with_gemini(raw, "fake-api-key")

        assert result == {
            "title": "Search for green boxes",
            "corrected_transcript": "Search for green boxes.",
        }
        mock_post.assert_called_once()
        # Verify the payload forces a Gemini function call for structured output.
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["tools"][0]["functionDeclarations"][0]["name"] == GEMINI_TRANSCRIPT_TOOL_NAME
        assert kwargs["json"]["tools"][0]["functionDeclarations"][0]["parameters"]["required"] == [
            "title",
            "corrected_transcript",
        ]
        assert kwargs["json"]["toolConfig"] == {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": [GEMINI_TRANSCRIPT_TOOL_NAME],
            }
        }


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
async def test_correct_transcript_with_gemini_api_failure_raises():
    """Test that correction failures are visible and not labeled as corrected."""
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        raw = "umm search for yellow actually no let's search for green boxes"
        with pytest.raises(RuntimeError, match="Gemini correction API failed"):
            await skill._correct_transcript_with_gemini(raw, "fake-api-key")


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
async def test_correct_transcript_with_gemini_invalid_json_raises():
    """Test that invalid correction JSON is not treated as corrected transcript."""
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={
        "candidates": [{
            "content": {
                "parts": [{
                    "text": "not a json string"
                }]
            }
        }]
    })

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        raw = "umm search for yellow actually no let's search for green boxes"
        with pytest.raises(RuntimeError, match="did not call finalize_transcript"):
            await skill._correct_transcript_with_gemini(raw, "fake-api-key")


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction,videos.transcript.audio-results-and-billing
@pytest.mark.anyio
async def test_full_execute_flow_with_gemini_correction():
    """Test the full TranscribeSkill.execute pipeline including Mistral transcription and Gemini correction."""
    app = DummyApp()
    skill = TranscribeSkill(
        app=app,
        app_id="audio",
        skill_id="transcribe",
        skill_name="Transcribe",
        skill_description="Transcribe voice recording.",
    )

    # Mock internal methods
    skill._unwrap_aes_key = AsyncMock(return_value=b"dummy_aes_key_32_bytes")
    skill._fetch_and_decrypt_audio = AsyncMock(return_value=b"decrypted_audio_bytes")
    
    # Mock Mistral transcription
    mock_mistral_result = {
        "text": "umm yeah so search for yellow actually no let's search for green boxes",
        "language": "en",
        "duration": 5.2,
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "umm yeah"},
            {"start": 1.0, "end": 5.2, "text": "search for green boxes"},
        ],
        "words": [
            {"start": 0.0, "end": 0.5, "word": "umm"},
            {"start": 0.5, "end": 1.0, "word": "yeah"},
        ],
    }
    skill._transcribe_with_mistral = AsyncMock(return_value=mock_mistral_result)
    skill._extract_waveform = AsyncMock(return_value={
        "version": 1,
        "kind": "rms-envelope",
        "samples": [0, 25, 50, 25],
        "duration_seconds": 5.2,
    })

    # Mock SecretsManager
    mock_secrets_manager = AsyncMock()
    async def fake_get_secret(secret_path, secret_key):
        if "mistral" in secret_path:
            return "fake-mistral-key"
        if "google_ai_studio" in secret_path:
            return "fake-google-key"
        return "fake-key"
    mock_secrets_manager.get_secret = fake_get_secret

    # Mock Gemini correction helper
    skill._correct_transcript_with_gemini = AsyncMock(return_value={
        "title": "Search for green boxes",
        "corrected_transcript": "Search for green boxes.",
    })

    # Execute
    requests = [
        {
            "id": "embed-1",
            "s3_base_url": "http://api:8000/s3",
            "s3_key": "uploads/1/original.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "filename": "recording.webm",
            "transcription_contract_version": 1,
        }
    ]

    response = await skill.execute(
        requests=requests,
        secrets_manager=mock_secrets_manager,
        user_id="user-1",
        user_vault_key_id="vault-key-1",
    )

    assert response.error is None
    assert len(response.results) == 1
    
    result = response.results[0]
    assert result["id"] == "embed-1"
    
    result_entry = result["results"][0]
    assert result_entry["title"] == "Search for green boxes"
    assert result_entry["transcript"] == "Search for green boxes."
    assert result_entry["transcript_original"] == "umm yeah so search for yellow actually no let's search for green boxes"
    assert result_entry["transcript_corrected"] == "Search for green boxes."
    assert result_entry["use_corrected"] is True
    assert result_entry["correction_model"] == GEMINI_CORRECTION_MODEL
    assert result_entry["duration_seconds"] == 5.2
    assert result_entry["language"] == "en"
    assert result_entry["segments"] == [
        {"start_seconds": 0.0, "end_seconds": 1.0, "text": "umm yeah"},
        {"start_seconds": 1.0, "end_seconds": 5.2, "text": "search for green boxes"},
    ]
    assert result_entry["words"] == [
        {"start_seconds": 0.0, "end_seconds": 0.5, "text": "umm"},
        {"start_seconds": 0.5, "end_seconds": 1.0, "text": "yeah"},
    ]
    assert result_entry["waveform"] == {
        "version": 1,
        "kind": "rms-envelope",
        "samples": [0, 25, 50, 25],
        "duration_seconds": 5.2,
    }

    # Verify user was charged (1 billed minute minimum = 3 credits)
    app.charge_user_credits.assert_called_once()
    _, kwargs = app.charge_user_credits.call_args
    assert kwargs["credits_to_charge"] == 3
    assert kwargs["usage_details"]["duration_seconds"] == 5.2
    assert skill._transcribe_with_mistral.await_args.kwargs["timestamps"] == "word"
