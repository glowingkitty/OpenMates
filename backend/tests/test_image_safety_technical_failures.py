# backend/tests/test_image_safety_technical_failures.py
#
# A safety check that cannot reach a decision (provider error, missing
# configuration) refuses the request but is never a user violation: no strike,
# no violation audit entry, no account deletion, and a localized
# "temporarily unavailable" message. A violation counts exactly once, so no
# single request can delete an account.
#
# Run: python -m pytest backend/tests/test_image_safety_technical_failures.py -v

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.apps.images.tasks import generate_task
from backend.core.api.app.routes.internal_api import (
    ContentSafetyRejectRequest,
    content_safety_reject,
)
from backend.shared.providers.google.vision_safety import VisionSafetyFindings
from backend.shared.providers.sightengine.client import SightengineFindings
from backend.shared.python_utils.image_safety.messages import (
    TECHNICAL_CATEGORIES,
    build_rejection_payload,
)
from backend.shared.python_utils.image_safety.pipeline import (
    ImageSafetyPipeline,
    SafetyRejection,
)
from backend.shared.python_utils.image_safety.unavailable import unavailable_message

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCALES = REPO_ROOT / "frontend/packages/ui/src/i18n/locales"
GERMAN_UNAVAILABLE = (
    "Die Sicherheitsprüfung ist vorübergehend nicht verfügbar, deshalb konnte die "
    "Anfrage nicht verarbeitet werden. Bitte versuche es gleich noch einmal."
)


def _rejection(category: str, *, technical: bool = False) -> SafetyRejection:
    return SafetyRejection(
        category=category,
        severity="severe",
        reason=f"test:{category}",
        user_facing_message="This image couldn't be generated.",
        tool_response=build_rejection_payload(category),
        stage="input",
        technical=technical,
    )


def _task(language: str = "de") -> SimpleNamespace:
    cache = MagicMock()
    cache.get_user_by_id = AsyncMock(return_value={"language": language})
    return SimpleNamespace(_cache_service=cache, _directus_service=MagicMock())


async def _handle(task: SimpleNamespace, rejection: SafetyRejection) -> dict:
    return await generate_task._handle_safety_rejection(
        task,
        rejection,
        user_id="user-1",
        prompt="a cat",
        assistant_response_id="resp-1",
        source_embed_id=None,
        output_embed_id="embed-1",
        provider="test",
        model="test-model",
        log_prefix="[test]",
    )


class TestTechnicalClassification:
    @pytest.mark.parametrize("category", sorted(TECHNICAL_CATEGORIES))
    def test_technical_categories_are_marked(self, category):
        assert _rejection(category).technical

    def test_policy_category_is_not_technical(self):
        assert not _rejection("S1_csam").technical

    @pytest.mark.asyncio
    async def test_classifier_api_error_is_technical(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        se_client = MagicMock()
        se_client.analyze = AsyncMock(
            return_value=SightengineFindings(
                hard_block=True,
                hard_block_reason="sightengine_api_error",
                error="HTTP 503",
            )
        )
        with patch(
            "backend.shared.python_utils.image_safety.pipeline.get_sightengine_safety_client",
            return_value=se_client,
        ), patch(
            "backend.shared.python_utils.image_safety.pipeline.analyze_image_gemini",
            new=AsyncMock(return_value=VisionSafetyFindings()),
        ):
            decision = await pipeline._validate_single_image(
                prompt="edit this",
                image_bytes=b"bytes",
                mime_type="image/webp",
                stage="input",
                secrets_manager=MagicMock(),
            )
        assert not decision.allowed
        assert decision.rejection.technical

    @pytest.mark.asyncio
    async def test_classifier_content_block_is_not_technical(self):
        pipeline = ImageSafetyPipeline()
        pipeline._initialized = True
        se_client = MagicMock()
        se_client.analyze = AsyncMock(
            return_value=SightengineFindings(
                hard_block=True,
                hard_block_reason="sexual_activity=0.95",
                category_hint="S3_sexual_other",
                sexual_activity=0.95,
            )
        )
        with patch(
            "backend.shared.python_utils.image_safety.pipeline.get_sightengine_safety_client",
            return_value=se_client,
        ), patch(
            "backend.shared.python_utils.image_safety.pipeline.analyze_image_gemini",
            new=AsyncMock(return_value=VisionSafetyFindings()),
        ):
            decision = await pipeline._validate_single_image(
                prompt="edit this",
                image_bytes=b"bytes",
                mime_type="image/webp",
                stage="input",
                secrets_manager=MagicMock(),
            )
        assert not decision.rejection.technical


class TestTechnicalFailureNeverStrikes:
    @pytest.mark.asyncio
    async def test_safeguard_error_records_nothing_and_returns_localized_message(self):
        strike_counter = MagicMock()
        strike_counter.record_strike = AsyncMock()
        with patch.object(
            generate_task, "get_strike_counter", return_value=strike_counter
        ), patch.object(
            generate_task, "write_audit_entry", new=AsyncMock()
        ) as audit, patch.object(
            generate_task, "_trigger_safety_ban", new=AsyncMock()
        ) as ban:
            response = await _handle(_task("de"), _rejection("safeguard_error"))

        strike_counter.record_strike.assert_not_called()
        audit.assert_not_called()
        ban.assert_not_called()
        assert response["error"] == "safety_check_unavailable"
        assert response["user_facing_message"] == GERMAN_UNAVAILABLE
        assert "severity" not in response

    @pytest.mark.asyncio
    async def test_policy_rejection_still_records_one_strike(self):
        strike_counter = MagicMock()
        strike_counter.record_strike = AsyncMock(
            return_value=SimpleNamespace(
                recorded=True, debounced=False, new_count=1, ban_triggered=False
            )
        )
        cache_client = AsyncMock()
        task = _task("en")
        type(task._cache_service).client = property(lambda self: _value(cache_client))
        with patch.object(
            generate_task, "get_strike_counter", return_value=strike_counter
        ), patch.object(
            generate_task, "write_audit_entry", new=AsyncMock()
        ) as audit, patch.object(
            generate_task, "_trigger_safety_ban", new=AsyncMock()
        ) as ban:
            response = await _handle(task, _rejection("S1_csam"))

        strike_counter.record_strike.assert_awaited_once()
        assert audit.await_args.kwargs["strike_weight"] == 1
        ban.assert_not_called()
        assert response["error"] == "safety_rejection"

    def test_message_is_translated_in_built_locales(self):
        for lang in ("en", "de", "fr"):
            data = json.loads((LOCALES / f"{lang}.json").read_text())
            assert data["safety_strikes"]["unavailable"]["text"]
        assert unavailable_message("de") == GERMAN_UNAVAILABLE
        assert unavailable_message("xx").startswith("The safety check is temporarily unavailable")


async def _value(v):
    return v


def _reject_deps(current_count: int = 0):
    cache = MagicMock()
    cache.get = AsyncMock(return_value=current_count or None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    cache.delete_user_cache = AsyncMock()
    directus = MagicMock()
    directus.delete_user = AsyncMock()
    return cache, directus


class TestContentSafetyRejectEndpoint:
    @pytest.mark.asyncio
    async def test_unavailable_check_is_not_counted(self):
        cache, directus = _reject_deps(current_count=3)
        result = await content_safety_reject(
            ContentSafetyRejectRequest(
                user_id="user-1",
                rejection_reason="safety_service_unavailable",
                upload_type="profile_image",
            ),
            directus_service=directus,
            cache_service=cache,
        )
        assert result["result"] == "not_counted"
        cache.set.assert_not_called()
        directus.delete_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_generation_count_is_not_incremented_again(self):
        cache, directus = _reject_deps(current_count=4)
        result = await content_safety_reject(
            ContentSafetyRejectRequest(
                user_id="user-1",
                rejection_reason="image_generation_safety:S3_sexual_other",
                strike_count=4,
            ),
            directus_service=directus,
            cache_service=cache,
        )
        cache.get.assert_not_called()
        cache.set.assert_not_called()
        assert result["reject_count"] == 4
        assert result["result"] == "account_deleted"

    @pytest.mark.asyncio
    async def test_upload_rejection_counts_one(self):
        cache, directus = _reject_deps(current_count=1)
        result = await content_safety_reject(
            ContentSafetyRejectRequest(
                user_id="user-1",
                rejection_reason="sexual_activity=0.95",
            ),
            directus_service=directus,
            cache_service=cache,
        )
        cache.set.assert_awaited_once_with("chat_image_rejects:user-1", 2, ttl=86400)
        assert result == {"result": "tracked", "reject_count": 2}
        directus.delete_user.assert_not_called()


class _ToolCallRejected(Exception):
    """Shape of Groq's 400 when the forced tool call misses the schema."""

    def __init__(self, failed_generation: str):
        super().__init__("Error code: 400 - tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed", "failed_generation": failed_generation}}


def _completion(arguments: dict):
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments)))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))])


def _safeguard(*outcomes):
    from backend.shared.providers.groq.safeguard import GroqSafeguardClient

    client = GroqSafeguardClient()
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(side_effect=list(outcomes))
    return client


async def _verdict(client):
    return await client.reason(
        policy_markdown="policy", stage="INPUT_VALIDATION_TEXT_ONLY",
        user_prompt="a watercolor of a lighthouse", sightengine_json={}, vlm_json={},
    )


# contract-test: supporting surface=rest_api assertions=safety-strikes.technical-failure-no-strike
class TestSafeguardToolCallRecovery:
    """Groq rejects ~half of the verdicts for schema noise (an "allow" with an empty
    severity); the model's verdict in failed_generation is used instead of
    refusing the request as unavailable."""

    @pytest.mark.asyncio
    async def test_schema_rejected_verdict_is_recovered_with_reasoning(self):
        generation = json.dumps({
            "name": "functions.report_safeguard_verdict",
            "arguments": {"decision": "allow", "category": "ALLOW_GENERAL",
                          "severity": "", "reasoning": "stylized, non-sexual", "discrepancies": ""},
        })
        client = _safeguard(_ToolCallRejected(generation))
        verdict = await _verdict(client)
        assert verdict.decision == "allow"
        assert verdict.category == "ALLOW_GENERAL"
        assert verdict.reasoning == "stylized, non-sexual"
        assert client._client.chat.completions.create.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_failed_generation_retries_once(self):
        client = _safeguard(
            _ToolCallRejected(""),
            _completion({"decision": "block", "category": "S5_minor_restricted_edit",
                         "severity": "severe", "reasoning": "photo of a minor", "discrepancies": ""}),
        )
        verdict = await _verdict(client)
        assert verdict.decision == "block"
        assert verdict.category == "S5_minor_restricted_edit"
        assert client._client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_two_unreadable_answers_are_a_technical_error(self):
        client = _safeguard(_ToolCallRejected(""), _ToolCallRejected(""))
        verdict = await _verdict(client)
        assert verdict.category == "safeguard_error"
        assert verdict.decision == "block"

    @pytest.mark.asyncio
    async def test_other_api_errors_are_not_retried(self):
        client = _safeguard(RuntimeError("HTTP 503"))
        verdict = await _verdict(client)
        assert verdict.category == "safeguard_error"
        assert client._client.chat.completions.create.await_count == 1

    def test_reasoning_budget_leaves_room_for_the_tool_call(self):
        source = (REPO_ROOT / "backend/shared/providers/groq/safeguard.py").read_text()
        reason_body = source.split("async def reason(", 1)[1].split("async def report_malicious_urls(", 1)[0]
        assert "max_tokens=2000" in reason_body
