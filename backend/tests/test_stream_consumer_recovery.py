"""
Regression tests for AI stream recovery metadata.

Saved CLI chats require final AI frames to include a sealed recovery job so the
client can persist encrypted assistant messages locally without trusting streamed
plaintext. These tests cover non-LLM fake-stream paths that bypass normal stream
aggregation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer
from backend.core.api.app.schemas.chat import AIHistoryMessage


class _StubCacheService:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish_event(self, channel: str, payload: dict) -> None:
        self.events.append((channel, payload))


def test_harmful_fake_stream_includes_recovery_job_before_final_marker(monkeypatch) -> None:
    task_id = "11111111-1111-4111-8111-111111111111"
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="unsafe image", created_at=1)],
        recovery_task_id=task_id,
        recovery_preflight_id="55555555-5555-4555-8555-555555555555",
        recovery_turn_id="66666666-6666-4666-8666-666666666666",
        recovery_public_key="public-key",
        chat_key_version=1,
    )
    preprocessing_result = PreprocessingResult(
        can_proceed=False,
        rejection_reason="misuse_detected",
    )
    cache_service = _StubCacheService()

    async def fake_charge(*_args, **_kwargs) -> dict:
        return {"prompt_tokens": 0, "completion_tokens": 4, "total_credits": 1}

    async def fake_persist(**kwargs) -> dict:
        assert kwargs["task_id"] == task_id
        assert kwargs["content"] == "I can't help with that request."
        assert kwargs["category"] == "general_knowledge"
        return {"job_id": "77777777-7777-4777-8777-777777777777"}

    async def fake_update_metadata(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)
    monkeypatch.setattr(stream_consumer, "_persist_sealed_recovery_job", fake_persist)
    monkeypatch.setattr(stream_consumer, "_update_chat_metadata", fake_update_metadata)
    monkeypatch.setattr(
        stream_consumer.celery_config.app,
        "AsyncResult",
        lambda _task_id: SimpleNamespace(state="PENDING"),
    )

    asyncio.run(
        stream_consumer._generate_fake_stream_for_harmful_content(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            predefined_response="I can't help with that request.",
            cache_service=cache_service,
            directus_service=object(),
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )
    )

    final_chunks = [
        payload
        for _channel, payload in cache_service.events
        if payload.get("is_final_chunk") is True
    ]
    assert len(final_chunks) == 1
    assert final_chunks[0]["recovery_job_id"] == "77777777-7777-4777-8777-777777777777"
    assert final_chunks[0]["recovery_protocol_version"] == 1
    assert final_chunks[0]["category"] == "general_knowledge"
