"""Audio provider selection, conservative failure and Mercury contract checks."""
# contract-test-file: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.providers import transcript_correction as correction


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
async def test_mercury_correction_preserves_forced_function_contract(monkeypatch):
    complete = AsyncMock(return_value=SimpleNamespace(choices=[{
        "finish_reason": "tool_calls", "message": {"tool_calls": [{"function": {
            "name": "finalize_transcript", "arguments": json.dumps({
                "title": '  "Grüne Boxen" ', "corrected_transcript": "Suche grüne Boxen unter 50 Euro.",
            }),
        }}]},
    }]))
    monkeypatch.setattr(correction, "InceptionClient", lambda *_args, **kwargs: SimpleNamespace(complete=complete))
    result = await correction.correct_transcript_with_mercury("ähm grüne boxen unter 50 euro", "private-key", "de")
    assert result == {"title": "Grüne Boxen", "corrected_transcript": "Suche grüne Boxen unter 50 Euro."}
    request = complete.call_args.args[0]
    assert request.reasoning_effort == "instant"
    assert request.temperature == 0.5
    assert request.tool_choice["function"]["name"] == "finalize_transcript"
    assert "de" in request.messages[0]["content"]
    assert request.messages[1]["content"] == 'Raw Transcript:\n"ähm grüne boxen unter 50 euro"'


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"title": "Title", "corrected_transcript": ""}, {"title": "Title", "corrected_transcript": ["text"]}, {"title": 12, "corrected_transcript": "text"}])
async def test_invalid_mercury_fields_are_rejected(monkeypatch, args):
    complete = AsyncMock(return_value=SimpleNamespace(choices=[{
        "finish_reason": "tool_calls", "message": {"tool_calls": [{"function": {
            "name": "finalize_transcript", "arguments": json.dumps(args),
        }}]},
    }]))
    monkeypatch.setattr(correction, "InceptionClient", lambda *_args, **kwargs: SimpleNamespace(complete=complete))
    with pytest.raises(RuntimeError, match="invalid transcript fields"):
        await correction.correct_transcript_with_mercury("text", "key")


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
async def test_mercury_success_avoids_google_and_reports_actual_model(monkeypatch):
    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(correction, "resolve_api_key", AsyncMock(return_value="key"))
    mercury = AsyncMock(return_value={"title": "Boxes", "corrected_transcript": "Green boxes."})
    monkeypatch.setattr(correction, "correct_transcript_with_mercury", mercury)
    secrets = SimpleNamespace(get_secret=AsyncMock(side_effect=AssertionError("Google must not be called")))
    result = await correction.correct_transcript("um green boxes", secrets, "en")
    assert result["model"] == "mercury-3"
    secrets.get_secret.assert_not_called()


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
async def test_mercury_failure_falls_back_and_reports_gemini(monkeypatch, caplog):
    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(correction, "resolve_api_key", AsyncMock(return_value="key"))
    monkeypatch.setattr(correction, "correct_transcript_with_mercury", AsyncMock(side_effect=RuntimeError("PRIVATE TRANSCRIPT")))
    google = AsyncMock(return_value={"title": "Boxes", "corrected_transcript": "Green boxes."})
    monkeypatch.setattr(correction, "correct_transcript_with_gemini", google)
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value="google-key"))
    result = await correction.correct_transcript("um green boxes", secrets, "en")
    assert result["model"] == correction.GEMINI_CORRECTION_MODEL
    assert "PRIVATE TRANSCRIPT" not in caplog.text
    google.assert_awaited_once_with("um green boxes", "google-key", "en")


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
async def test_unverified_training_opt_out_keeps_user_text_on_google(monkeypatch):
    monkeypatch.delenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", raising=False)
    mercury = AsyncMock()
    monkeypatch.setattr(correction, "correct_transcript_with_mercury", mercury)
    monkeypatch.setattr(correction, "correct_transcript_with_gemini", AsyncMock(return_value={"title": "Boxes", "corrected_transcript": "Green boxes."}))
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value="google-key"))
    assert (await correction.correct_transcript("green boxes", secrets))["model"] == correction.GEMINI_CORRECTION_MODEL
    mercury.assert_not_called()


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
async def test_total_correction_failure_raises(monkeypatch):
    monkeypatch.delenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", raising=False)
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="unavailable"):
        await correction.correct_transcript("keep original", secrets)
