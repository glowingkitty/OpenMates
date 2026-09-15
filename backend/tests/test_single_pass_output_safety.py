"""Shared single-pass behavior, independent of provider/model reliability."""
import asyncio
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import external_result_sanitizer as sanitizer
from backend.shared.python_utils import app_skill_helpers as helpers
from backend.shared.python_utils import app_skill_output_safety as safety
from backend.shared.python_utils import structured_content_sanitization as scanner


# contract-test: supporting surface=rest_api assertions=app-skills.output.single-boundary,app-skills.output.ascii-always
@pytest.mark.anyio
@pytest.mark.parametrize("app_id,skill_id", sorted(safety.ALWAYS_EXTERNAL_DATA_SKILLS))
async def test_all_registered_external_skills_share_one_scan_after_cleanup(monkeypatch, app_id, skill_id):
    calls = []
    async def provider(**kwargs):
        import json
        units = json.loads(kwargs["message_history"][1]["content"])["units"]
        assert all("\u200b" not in u["text"] for u in units)
        calls.append(units)
        return SimpleNamespace(error_message=None, arguments={"decisions": [
            {"id": u["id"], "verdict": "safe", "quotes": []} for u in units
        ]})
    monkeypatch.setattr(scanner, "call_preprocessing_llm", provider)
    with safety.central_app_skill_dispatch():
        text = await helpers.sanitize_external_content("Hello\u200b\nExternal tutorial.")
        payload = await helpers.sanitize_long_text_fields_in_payload({"text": text}, "test", None)
        assert calls == []
    result = await safety.sanitize_app_skill_output(payload, safety.AppSkillOutputSafetyContext(
        app_id, skill_id, safety.APP_SKILL_SURFACE_REST, {}, True,
    ))
    assert result == {"text": "Hello\nExternal tutorial."}
    assert len(calls) == 1


# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent,app-skills.output.bounded-failure
@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["uncertain", "timeout", "failure", "invalid", "oversize"])
async def test_fail_open_preserves_cleaned_data_without_retry(monkeypatch, caplog, mode):
    calls = []
    async def classify(units, **kwargs):
        calls.append(units)
        if mode == "timeout":
            raise TimeoutError()
        if mode == "failure":
            raise RuntimeError("private-provider-content")
        if mode == "invalid":
            return {}
        return {u["id"]: scanner.TextDecision("uncertain") for u in units}
    monkeypatch.setattr(sanitizer, "classify_text_units", classify)
    text = ("Benign.\n" * 8000 if mode == "oversize" else "Hello\nExternal content.") + "\u200b"
    result = await sanitizer.sanitize_long_text_fields_in_payload({"text": text}, "test", None, always_sanitize_field_names={"text"})
    assert result == {"text": text.replace("\u200b", "")}
    assert len(calls) == (0 if mode == "oversize" else 1)
    assert "private-provider-content" not in caplog.text
    if mode != "uncertain":
        assert "status=unscanned" in caplog.text


# contract-test: supporting surface=rest_api assertions=app-skills.output.single-boundary
@pytest.mark.anyio
async def test_background_helper_without_dispatch_scope_still_scans(monkeypatch):
    calls = []
    async def classify(units, **kwargs):
        calls.append(units)
        return {u["id"]: scanner.TextDecision("safe") for u in units}
    monkeypatch.setattr(sanitizer, "classify_text_units", classify)
    assert await helpers.sanitize_external_content("Tutorial\u200b\nRun the documented command.") == "Tutorial\nRun the documented command."
    assert len(calls) == 1


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_caller_cancellation_is_not_swallowed(monkeypatch):
    async def classify(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(sanitizer, "classify_text_units", classify)
    with pytest.raises(asyncio.CancelledError):
        await sanitizer.sanitize_long_text_fields_in_payload({"text": "External content"}, "test", None, always_sanitize_field_names={"text"})


# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
def test_overlapping_verified_spans_merge_without_loss_of_surrounding_text():
    assert sanitizer._redact_spans("abcDEFghi", scanner.TextDecision("injection", ((3, 5), (4, 6)))) == "abc" + sanitizer.PROMPT_INJECTION_PLACEHOLDER + "ghi"
