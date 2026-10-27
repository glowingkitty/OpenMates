"""Audio provider selection, conservative failure and Mercury contract checks."""
# contract-test-file: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers import gemini_transcript_correction as gemini_correction
from backend.shared.providers import transcript_correction as correction


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["stop", "tool_calls"])
async def test_mercury_correction_preserves_forced_function_contract(monkeypatch, finish_reason):
    complete = AsyncMock(return_value=SimpleNamespace(choices=[{
        "finish_reason": finish_reason, "message": {"tool_calls": [{"function": {
            "name": "finalize_transcript", "arguments": json.dumps({
                "title": '  "Grüne Boxen" ', "corrected_transcript": "Suche grüne Boxen unter 50 Euro.",
            }),
        }}]},
    }]))
    monkeypatch.setattr(correction, "InceptionClient", lambda *_args, **kwargs: SimpleNamespace(complete=complete))
    result = await correction.correct_transcript_with_mercury("ähm grüne boxen unter 50 euro", "private-key", "de")
    assert result == {"title": "Grüne Boxen", "corrected_transcript": "Suche grüne Boxen unter 50 Euro."}
    request = complete.call_args.args[0]
    assert request.reasoning_effort == "low"
    assert request.temperature == 0.5
    assert request.tool_choice["function"]["name"] == "finalize_transcript"
    assert request.messages[0]["content"] == gemini_correction.build_transcript_correction_prompt("de")
    assert request.messages[1]["content"] == 'Raw Transcript:\n"ähm grüne boxen unter 50 euro"'


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
@pytest.mark.parametrize("finish", [
    {"finish_reason": "length"}, {"finish_reason": "content_filter"},
    {"finish_reason": None}, {"finish_reason": "unknown"}, {},
], ids=["truncated", "blocked", "null", "unknown", "missing"])
async def test_incomplete_mercury_finish_is_rejected_even_with_valid_tool(monkeypatch, finish):
    complete = AsyncMock(return_value=SimpleNamespace(choices=[{
        **finish, "message": {"tool_calls": [{"function": {
            "name": "finalize_transcript", "arguments": json.dumps({
                "title": "Boxes", "corrected_transcript": "Green boxes.",
            }),
        }}]},
    }]))
    monkeypatch.setattr(correction, "InceptionClient", lambda *_args, **kwargs: SimpleNamespace(complete=complete))
    with pytest.raises(RuntimeError, match="did not finish"):
        await correction.correct_transcript_with_mercury("green boxes", "key")


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["stop", "tool_calls"])
@pytest.mark.parametrize("names", [[], ["finalize_transcript", "finalize_transcript"], ["unexpected_function"]],
                         ids=["no-tool", "multiple-tools", "wrong-function"])
async def test_successful_finish_requires_exactly_one_transcript_function(monkeypatch, finish_reason, names):
    calls = [{"function": {"name": name, "arguments": json.dumps({
        "title": "Boxes", "corrected_transcript": "Green boxes.",
    })}} for name in names]
    complete = AsyncMock(return_value=SimpleNamespace(choices=[{
        "finish_reason": finish_reason, "message": {"tool_calls": calls},
    }]))
    monkeypatch.setattr(correction, "InceptionClient", lambda *_args, **kwargs: SimpleNamespace(complete=complete))
    with pytest.raises(RuntimeError, match="unexpected tool call"):
        await correction.correct_transcript_with_mercury("green boxes", "key")


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
async def test_mercury_credential_lookup_shares_total_deadline_and_is_cancelled(monkeypatch):
    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(correction, "MERCURY_CORRECTION_TIMEOUT_SECONDS", 0.01)
    cancelled = asyncio.Event()

    async def unavailable_credentials(_manager):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(correction, "resolve_api_key", unavailable_credentials)
    mercury = AsyncMock()
    google = AsyncMock(return_value={"title": "Boxes", "corrected_transcript": "Green boxes."})
    monkeypatch.setattr(correction, "correct_transcript_with_mercury", mercury)
    monkeypatch.setattr(correction, "correct_transcript_with_gemini", google)
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value="google-key"))
    result = await asyncio.wait_for(correction.correct_transcript("um green boxes", secrets, "en"), 1)
    assert cancelled.is_set()
    mercury.assert_not_awaited()
    google.assert_awaited_once_with("um green boxes", "google-key", "en")
    assert result["model"] == "gemini-3.8-flash"


# contract-test: supporting surface=rest_api assertions=videos.transcript.audio-timestamps-and-correction
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE TRANSCRIPT"), httpx.ConnectError("PRIVATE TRANSCRIPT")],
                         ids=["mercury-timeout", "mercury-outage"])
async def test_mercury_network_failure_uses_actual_gemini38_low_request(monkeypatch, caplog, failure):
    monkeypatch.setenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "true")
    monkeypatch.setattr(correction, "resolve_api_key", AsyncMock(return_value="mercury-key"))
    mercury_complete = AsyncMock(side_effect=failure)
    monkeypatch.setattr(correction, "InceptionClient", lambda *_args, **kwargs: SimpleNamespace(complete=mercury_complete))
    response = httpx.Response(200, json={"candidates": [{"content": {"parts": [{
        "functionCall": {"name": "finalize_transcript", "args": {
            "title": '  "Green boxes" ', "corrected_transcript": "  Search for green boxes.  ",
        }},
    }]}}]})
    google_post = AsyncMock(return_value=response)
    monkeypatch.setattr(gemini_correction.httpx.AsyncClient, "post", google_post)
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value="google-key"))

    result = await correction.correct_transcript("um green boxes", secrets, "en")

    assert result == {"model": "gemini-3.8-flash", "title": "Green boxes",
                      "corrected_transcript": "Search for green boxes."}
    mercury_complete.assert_awaited_once()
    google_post.assert_awaited_once()
    secrets.get_secret.assert_awaited_once_with("kv/data/providers/google_ai_studio", "api_key")
    assert google_post.call_args.args == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
    )
    assert google_post.call_args.kwargs["params"] == {"key": "google-key"}
    body = google_post.call_args.kwargs["json"]
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low", "includeThoughts": False}
    assert body["toolConfig"]["functionCallingConfig"] == {
        "mode": "ANY", "allowedFunctionNames": ["finalize_transcript"],
    }
    assert body["contents"][0]["parts"][1]["text"] == 'Raw Transcript:\n"um green boxes"'
    assert "Detected or requested transcript language: en" in body["contents"][0]["parts"][0]["text"]
    assert "PRIVATE TRANSCRIPT" not in caplog.text


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
