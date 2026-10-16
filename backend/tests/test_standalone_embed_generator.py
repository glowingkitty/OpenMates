# contract-test-file: infrastructure
"""Standalone REST generators keep their authenticated detached-task identity."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from celery import Celery
from celery.exceptions import Ignore

from backend.apps.images.tasks import generate_task as image_task
from backend.shared.python_utils.chat_recovery_context import (
    VerifiedOutputProducer,
    active_verified_output_producer,
)
from backend.shared.python_utils.embed_producer_worker import ProducerHold, _checked_context
from backend.shared.python_utils import embed_producer_worker
from backend.shared.python_utils.embed_producer_dispatch import PRODUCER_HEADER
from backend.shared.python_utils.image_safety import PipelineDecision
from backend.core.api.app.tasks.base_task import BaseServiceTask


OWNER_ID = "owner-uuid"
OWNER_HASH = hashlib.sha256(OWNER_ID.encode()).hexdigest()
EMBED_ID = "88888888-8888-4888-8888-888888888888"
TASK_ID = "66666666-6666-4666-8666-666666666666"
TASK_NAME = "apps.images.tasks.skill_generate"


class _AvailableStorage:
    async def check_availability(self) -> str:
        return "available"


class _AllowingSafetyPipeline:
    async def validate_input(self, **_kwargs) -> PipelineDecision:
        return PipelineDecision(allowed=True)


class _StandaloneTask:
    request = SimpleNamespace(id=TASK_ID)

    def __init__(self) -> None:
        self._secrets_manager = object()
        self._cache_service = object()
        self._directus_service = object()
        self._encryption_service = object()
        self._s3_service = _AvailableStorage()

    async def initialize_core_services(self) -> None:
        return None

    async def cleanup_services(self) -> None:
        return None


def _resolved_direct() -> dict:
    return {
        "status": "DIRECT_AUTHORIZED",
        "intent_kind": "direct_skill",
        "context": {
            "hashed_user_id": OWNER_HASH,
            "hashed_team_id": None,
            "target_chat_id": None,
            "primary_message_id": None,
            "primary_embed_id": EMBED_ID,
        },
    }


def _direct_producer() -> VerifiedOutputProducer:
    producer, recovery = _checked_context(
        _resolved_direct(),
        {"user_id": OWNER_ID, "embed_id": EMBED_ID, "chat_id": "", "message_id": ""},
        TASK_ID,
        TASK_NAME,
        "f" * 64,
    )
    assert recovery is None
    return producer


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_standalone_direct_generator_reaches_provider_without_chat_identity(monkeypatch):
    provider = AsyncMock(side_effect=RuntimeError("provider boundary reached"))
    monkeypatch.setattr(image_task, "generate_vector_recraft", provider)
    monkeypatch.setattr(image_task, "get_pipeline", lambda: _AllowingSafetyPipeline())
    monkeypatch.setattr(image_task, "_estimate_image_generation_credits", AsyncMock(return_value=100))
    monkeypatch.setattr(image_task, "ensure_credit_headroom", AsyncMock(return_value=None))

    token = active_verified_output_producer.set(_direct_producer())
    try:
        with pytest.raises(RuntimeError, match="provider boundary reached"):
            await image_task._async_generate_image(
                _StandaloneTask(),
                "images",
                "generate",
                {
                    "prompt": "a small vector test image",
                    "user_id": OWNER_ID,
                    "embed_id": EMBED_ID,
                    "external_request": True,
                    "output_filetype": "svg",
                },
            )
    finally:
        active_verified_output_producer.reset(token)

    provider.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.parametrize("changed_identity", [
    {"user_id": "other-owner"},
    {"embed_id": "99999999-9999-4999-8999-999999999999"},
])
def test_standalone_direct_worker_rejects_changed_owner_or_embed(changed_identity):
    identity = {
        "user_id": OWNER_ID,
        "embed_id": EMBED_ID,
        "chat_id": "",
        "message_id": "",
        **changed_identity,
    }
    with pytest.raises(ProducerHold, match="producer_identity_mismatch"):
        _checked_context(_resolved_direct(), identity, TASK_ID, TASK_NAME, "f" * 64)


class _SuccessfulStandaloneTask(BaseServiceTask):
    name = TASK_NAME

    def run(self, *_args, **_kwargs):
        raise AssertionError("task body must not run from success callback")


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_celery_success_closes_standalone_asset_after_result_is_stored(monkeypatch):
    task = _SuccessfulStandaloneTask()
    task.bind(Celery("standalone-completion-test"))
    task.push_request(headers={PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}})
    complete = AsyncMock(return_value=None)
    monkeypatch.setattr(task, "_complete_successful_standalone_asset", complete)
    kwargs = {"arguments": {
        "user_id": OWNER_ID, "embed_id": EMBED_ID, "chat_id": None, "message_id": None,
    }}

    task.on_success({"embed_id": EMBED_ID, "status": "finished"}, TASK_ID, (), kwargs)

    complete.assert_awaited_once_with(
        task_id=TASK_ID, args=(), kwargs=kwargs, asset_id=EMBED_ID,
    )
    task.pop_request()


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_completed_direct_intent_holds_redelivery_without_reclassification():
    with pytest.raises(ProducerHold, match="producer_already_completed"):
        _checked_context(
            {"status": "COMPLETED", "reason_code": "direct_skill_already_completed"},
            {"user_id": OWNER_ID, "embed_id": EMBED_ID, "chat_id": "", "message_id": ""},
            TASK_ID, TASK_NAME, "f" * 64,
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_completed_redelivery_does_not_overwrite_existing_success(monkeypatch):
    task = _SuccessfulStandaloneTask()
    task.bind(Celery("standalone-redelivery-test"))
    task.push_request(id=TASK_ID, headers={PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}})
    update_state = Mock()
    monkeypatch.setattr(task, "update_state", update_state)

    async def already_completed(**_kwargs):
        raise ProducerHold("producer_already_completed")

    monkeypatch.setattr(embed_producer_worker, "verify_output_producer", already_completed)
    with pytest.raises(Ignore):
        task._call_with_output_producer((), {"arguments": {
            "user_id": OWNER_ID, "embed_id": EMBED_ID,
        }})

    update_state.assert_not_called()
    task.pop_request()
