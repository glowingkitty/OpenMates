# backend/tests/test_structured_content_sanitization.py
#
# Focused contract tests for structured external-content decisions.
# They enforce exact server-assigned coverage and reject malformed model output.
#
# Architecture: specifications/architecture/app-skill-execution/specification.yml

from types import SimpleNamespace

import pytest

from backend.shared.python_utils import structured_content_sanitization as scanner


# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent,app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_classify_text_units_accepts_one_safe_or_injection_decision_per_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_preprocessing_llm(**kwargs):
        return SimpleNamespace(
            error_message=None,
            arguments={"decisions": [{"id": "field-1", "decision": "safe"}, {"id": "field-2", "decision": "injection"}]},
        )

    monkeypatch.setattr(scanner, "call_preprocessing_llm", fake_call_preprocessing_llm)

    assert await scanner.classify_text_units(
        [{"id": "field-1", "path": "results[0].description", "text": "safe"}, {"id": "field-2", "path": "results[1].description", "text": "unsafe"}],
        task_id="test",
        secrets_manager=None,
    ) == {"field-1": "safe", "field-2": "injection"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "decisions",
    [
        [{"id": "field-1", "decision": "safe"}],
        [{"id": "field-1", "decision": "safe"}, {"id": "field-1", "decision": "injection"}],
        [{"id": "field-1", "decision": "safe"}, {"id": "unknown", "decision": "injection"}],
        [{"id": "field-1", "decision": "safe"}, {"id": "field-2", "decision": "rewritten text"}],
        [{"id": [], "decision": "safe"}, {"id": "field-2", "decision": "safe"}],
    ],
)
# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
async def test_classify_text_units_rejects_incomplete_duplicate_unknown_or_invalid_decisions(monkeypatch, decisions) -> None:
    async def fake_call_preprocessing_llm(**kwargs):
        return SimpleNamespace(error_message=None, arguments={"decisions": decisions})

    monkeypatch.setattr(scanner, "call_preprocessing_llm", fake_call_preprocessing_llm)

    with pytest.raises(scanner.StructuredScanError, match="OUTPUT_SAFETY_INVALID"):
        await scanner.classify_text_units(
            [{"id": "field-1", "path": "a", "text": "one"}, {"id": "field-2", "path": "b", "text": "two"}],
            task_id="test",
            secrets_manager=None,
        )


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
async def test_classify_text_units_maps_provider_timeout_without_retry(monkeypatch) -> None:
    calls = 0

    async def fake_call_preprocessing_llm(**kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError()

    monkeypatch.setattr(scanner, "call_preprocessing_llm", fake_call_preprocessing_llm)

    with pytest.raises(scanner.StructuredScanError, match="OUTPUT_SAFETY_TIMEOUT"):
        await scanner.classify_text_units(
            [{"id": "field-1", "path": "a", "text": "one"}], task_id="test", secrets_manager=None
        )
    assert calls == 1


# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
@pytest.mark.anyio
async def test_classify_text_units_accepts_a_12000_character_unicode_unit(monkeypatch) -> None:
    async def fake_call_preprocessing_llm(**kwargs):
        return SimpleNamespace(error_message=None, arguments={"decisions": [{"id": "field-1", "decision": "safe"}]})

    monkeypatch.setattr(scanner, "call_preprocessing_llm", fake_call_preprocessing_llm)

    assert await scanner.classify_text_units(
        [{"id": "field-1", "path": "content", "text": "😀" * 12_000}], task_id="test", secrets_manager=None
    ) == {"field-1": "safe"}


# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
@pytest.mark.anyio
async def test_classify_text_units_rejects_extra_top_level_arguments(monkeypatch) -> None:
    async def fake_call_preprocessing_llm(**kwargs):
        return SimpleNamespace(error_message=None, arguments={"decisions": [{"id": "field-1", "decision": "safe"}], "text": "rewritten"})

    monkeypatch.setattr(scanner, "call_preprocessing_llm", fake_call_preprocessing_llm)
    with pytest.raises(scanner.StructuredScanError, match="OUTPUT_SAFETY_INVALID"):
        await scanner.classify_text_units([{"id": "field-1", "path": "content", "text": "safe"}], task_id="test", secrets_manager=None)


# contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
@pytest.mark.anyio
async def test_classify_text_units_rejects_an_overlong_serialized_path_before_provider_call(monkeypatch) -> None:
    async def unexpected_provider(*args, **kwargs):
        raise AssertionError("invalid batch must not reach provider")

    monkeypatch.setattr(scanner, "call_preprocessing_llm", unexpected_provider)
    with pytest.raises(scanner.StructuredScanError, match="OUTPUT_SAFETY_INVALID"):
        await scanner.classify_text_units(
            [{"id": "field-1", "path": "x" * 50_000, "text": "safe"}], task_id="test", secrets_manager=None
        )
