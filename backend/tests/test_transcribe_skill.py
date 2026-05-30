# backend/tests/test_transcribe_skill.py
#
# Unit tests for TranscribeSkill with automatic Gemini transcript correction.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.apps.audio.skills.transcribe_skill import TranscribeSkill

class DummyApp:
    def __init__(self):
        # Mock credits methods
        self.get_user_credits = AsyncMock(return_value=100)
        self.charge_user_credits = AsyncMock()


@pytest.mark.anyio
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
                    "text": json.dumps({"corrected_transcript": "Search for green boxes."})
                }]
            }
        }]
    })

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        raw = "umm search for yellow actually no let's search for green boxes"
        corrected = await skill._correct_transcript_with_gemini(raw, "fake-api-key")

        assert corrected == "Search for green boxes."
        mock_post.assert_called_once()
        # Verify the payload contains our raw transcript and responseMimeType config
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.anyio
async def test_correct_transcript_with_gemini_api_failure_fallback():
    """Test that _correct_transcript_with_gemini falls back to the original transcript on API error."""
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
        corrected = await skill._correct_transcript_with_gemini(raw, "fake-api-key")

        assert corrected == raw


@pytest.mark.anyio
async def test_correct_transcript_with_gemini_invalid_json_fallback():
    """Test that _correct_transcript_with_gemini falls back to the original transcript on invalid json."""
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
        corrected = await skill._correct_transcript_with_gemini(raw, "fake-api-key")

        assert corrected == raw


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
    }
    skill._transcribe_with_mistral = AsyncMock(return_value=mock_mistral_result)

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
    skill._correct_transcript_with_gemini = AsyncMock(return_value="Search for green boxes.")

    # Execute
    requests = [
        {
            "id": "embed-1",
            "s3_base_url": "http://api:8000/s3",
            "s3_key": "uploads/1/original.webm.enc",
            "aes_nonce": "bm9uY2U=",
            "vault_wrapped_aes_key": "vault:wrapped:key",
            "filename": "recording.webm",
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
    assert result_entry["transcript"] == "Search for green boxes."
    assert result_entry["transcript_original"] == "umm yeah so search for yellow actually no let's search for green boxes"
    assert result_entry["transcript_corrected"] == "Search for green boxes."
    assert result_entry["use_corrected"] is True
    assert result_entry["correction_model"] == "gemini-3.5-flash"
    assert result_entry["duration_seconds"] == 5.2

    # Verify user was charged (1 billed minute minimum = 3 credits)
    app.charge_user_credits.assert_called_once()
    _, kwargs = app.charge_user_credits.call_args
    assert kwargs["credits_to_charge"] == 3
    assert kwargs["usage_details"]["duration_seconds"] == 5.2
