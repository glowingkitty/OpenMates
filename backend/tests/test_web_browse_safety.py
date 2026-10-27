"""Browse uses the inherited output boundary with metered, fail-closed decisions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils import app_skill_output_safety as safety
from backend.shared.python_utils.strict_output_safety import (
    strict_output_safety,
    StrictSafetyUnavailable,
)


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content,web-browse.cost-accounting,app-skills.output.external-semantic
@pytest.mark.asyncio
async def test_strict_scope_uses_the_supplied_accounting_evaluator_and_never_generative_fallback(
    monkeypatch,
):
    from backend.shared.python_utils import (
        structured_content_sanitization as classifier,
    )
    from backend.shared.providers.typesafe.models import NoulAnswer

    evaluator = AsyncMock(
        return_value=SimpleNamespace(
            answers={"prompt_injection": NoulAnswer(type="noul", noul=0.01)}
        )
    )
    forbidden = AsyncMock(side_effect=AssertionError("Unmetered fallback was invoked"))
    monkeypatch.setattr(classifier, "call_preprocessing_llm", forbidden)
    with strict_output_safety(evaluator):
        result = await safety.sanitize_app_skill_output(
            {"text": "An observed public fact."},
            safety.AppSkillOutputSafetyContext(
                app_id="web",
                skill_id="browse",
                surface="assistant",
                request_body={},
                external_data=True,
            ),
        )
    assert result == {"text": "An observed public fact."}
    evaluator.assert_awaited_once()
    assert evaluator.await_args.kwargs["state"]["units"]
    forbidden.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content,web-browse.budgets-and-stop,app-skills.output.bounded-failure
@pytest.mark.asyncio
async def test_required_safety_failure_propagates_without_source_text_and_scope_is_restored(
    monkeypatch,
):
    scanner = AsyncMock(side_effect=RuntimeError("private page sentinel"))
    monkeypatch.setattr(safety, "sanitize_long_text_fields_in_payload", scanner)
    context = safety.AppSkillOutputSafetyContext(
        app_id="web",
        skill_id="browse",
        surface="assistant",
        request_body={},
        external_data=True,
    )
    with strict_output_safety(AsyncMock()):
        with pytest.raises(StrictSafetyUnavailable) as exc:
            await safety.sanitize_app_skill_output(
                {"text": "private page sentinel"}, context
            )
        assert "sentinel" not in str(exc.value)
    # Other skills retain the existing fail-open ASCII-cleaned behavior.
    assert await safety.sanitize_app_skill_output({"text": "clean text"}, context) == {
        "text": "clean text"
    }


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content,app-skills.output.external-semantic
@pytest.mark.asyncio
async def test_request_cannot_disable_a_code_owned_strict_scan(monkeypatch):
    scanner = AsyncMock(return_value={"text": "scanned"})
    monkeypatch.setattr(safety, "sanitize_long_text_fields_in_payload", scanner)
    context = safety.AppSkillOutputSafetyContext(
        app_id="web",
        skill_id="browse",
        surface="rest",
        request_body={"security": {"prompt_injection_protection": "disabled"}},
        external_data=True,
    )
    with strict_output_safety(AsyncMock()):
        assert await safety.sanitize_app_skill_output({"text": "raw"}, context) == {
            "text": "scanned"
        }
    scanner.assert_awaited_once()
