# backend/tests/test_base_app_dispatch_context.py
#
# Regression tests for BaseApp's in-process app-skill dispatcher. Chat,
# REST, CLI, and SDK app-skill calls all converge here after registry
# resolution, so injected runtime context must be passed exactly once.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel as PydanticModel

celery_module = ModuleType("celery")
kombu_module = ModuleType("kombu")
rate_limiting_module = ModuleType("backend.apps.ai.processing.rate_limiting")


class FakeCelery:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.conf = {}


class FakeQueue:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class FakeRateLimitScheduledException(Exception):
    pass


celery_module.Celery = FakeCelery
kombu_module.Queue = FakeQueue
rate_limiting_module.RateLimitScheduledException = FakeRateLimitScheduledException


def _load_isolated_base_app() -> type:
    """Load the dispatch code without leaving import stubs in other tests."""

    module_name = "_base_app_dispatch_context_subject"
    module_path = Path(__file__).resolve().parents[1] / "apps" / "base_app.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load BaseApp from {module_path}")
    subject = importlib.util.module_from_spec(spec)
    missing = object()
    processing = sys.modules.get("backend.apps.ai.processing")
    previous_rate_limiting = (
        processing.__dict__.get("rate_limiting", missing) if processing is not None else missing
    )
    stubs = {
        "celery": sys.modules.get("celery", celery_module),
        "kombu": sys.modules.get("kombu", kombu_module),
        "backend.apps.ai.processing.rate_limiting": sys.modules.get(
            "backend.apps.ai.processing.rate_limiting", rate_limiting_module
        ),
    }
    previous_modules = {name: sys.modules.get(name, missing) for name in stubs}
    try:
        sys.modules.update(stubs)
        spec.loader.exec_module(subject)
    finally:
        for name, previous in previous_modules.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        processing = sys.modules.get("backend.apps.ai.processing")
        if processing is not None and processing.__dict__.get("rate_limiting") is rate_limiting_module:
            if previous_rate_limiting is missing:
                processing.__dict__.pop("rate_limiting", None)
            else:
                processing.rate_limiting = previous_rate_limiting
    return subject.BaseApp


BaseApp = _load_isolated_base_app()


class BatchRequestSkill:
    captured_requests: list[dict[str, Any]] | None = None
    captured_secrets_manager: Any = None
    captured_kwargs: dict[str, Any] | None = None

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def execute(
        self,
        requests: list[dict[str, Any]],
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.__class__.captured_requests = requests
        self.__class__.captured_secrets_manager = secrets_manager
        self.__class__.captured_kwargs = kwargs
        return {"success": True}


def _fake_base_app() -> BaseApp:
    app = BaseApp.__new__(BaseApp)
    app.app_id = "test_app"
    app.celery_producer = None
    app._resolve_translation_key = lambda key, lang="en": key
    return app


@pytest.mark.anyio
# contract-test: infrastructure
async def test_dispatch_list_skill_passes_injected_context_once() -> None:
    secrets_manager = object()
    app = _fake_base_app()
    skill_definition = SimpleNamespace(
        id="batch",
        name_translation_key="batch.name",
        description_translation_key="batch.description",
        full_model_reference=None,
        pricing=None,
        default_config={},
    )

    result = await app._dispatch_skill_with_class(
        skill_definition,
        BatchRequestSkill,
        {
            "requests": [{"query": "Berlin"}],
            "_secrets_manager": secrets_manager,
            "_user_id": "user-1",
        },
    )

    assert result == {"success": True}
    assert BatchRequestSkill.captured_requests == [{"query": "Berlin"}]
    assert BatchRequestSkill.captured_secrets_manager is secrets_manager
    assert BatchRequestSkill.captured_kwargs == {
        "external_request": False,
        "user_id": "user-1",
    }


def _batch_definition() -> SimpleNamespace:
    return SimpleNamespace(
        id="batch",
        name_translation_key="batch.name",
        description_translation_key="batch.description",
        full_model_reference=None,
        pricing=None,
        default_config={},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body_extra", "expected"),
    [
        ({"_rerank_candidates": 24}, {"rerank_candidates": 24}),  # in-process caller (PDF prefetch)
        ({"_rerank_candidates": 24, "_external_request": True}, {}),  # outside callers never choose it
        ({"_rerank_candidates": "24"}, {}),
        ({"_rerank_candidates": True}, {}),
    ],
)
# contract-test: supporting surface=rest_api assertions=pdf-processing.read.prefetch-relevant-pages
async def test_in_process_callers_can_widen_the_search_rerank_but_outside_callers_cannot(body_extra, expected) -> None:
    result = await _fake_base_app()._dispatch_skill_with_class(
        _batch_definition(),
        BatchRequestSkill,
        {"requests": [{"query": "speed"}], "_user_id": "user-1", **body_extra},
    )

    assert result == {"success": True}
    kwargs = BatchRequestSkill.captured_kwargs or {}
    assert kwargs.get("rerank_candidates") == expected.get("rerank_candidates")
    assert ("rerank_candidates" in kwargs) == bool(expected)


class RecoveryRejectingSkill:
    error: Exception = RuntimeError("unset")

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def execute(self, requests: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        raise self.__class__.error


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
async def test_recovery_rejection_keeps_its_status_through_skill_dispatch() -> None:
    """A 409 immutable-binding refusal from ai.ask must not become a generic 422.

    Production 2026-11-15: the wrapped 422 made the message handler tell the
    client "AI did not start, retry" for a turn whose retry can never bind.
    """
    from fastapi import HTTPException

    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    RecoveryRejectingSkill.error = ChatRecoveryProtocolError(409, "legacy_dispatch_mismatch")
    with pytest.raises(ChatRecoveryProtocolError) as rejected:
        await _fake_base_app()._dispatch_skill_with_class(
            _batch_definition(), RecoveryRejectingSkill, {"requests": [{"query": "x"}]},
        )
    assert (rejected.value.status_code, rejected.value.code) == (409, "legacy_dispatch_mismatch")

    # Ordinary skill errors are still wrapped as generic execution failures.
    RecoveryRejectingSkill.error = ValueError("bad input")
    with pytest.raises(HTTPException) as wrapped:
        await _fake_base_app()._dispatch_skill_with_class(
            _batch_definition(), RecoveryRejectingSkill, {"requests": [{"query": "x"}]},
        )
    assert wrapped.value.status_code == 500


class StrictRequest(PydanticModel):
    model_config = {"extra": "forbid"}
    command: str


class StrictSkill:
    fail_in_execute = False

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def execute(self, request: StrictRequest, **_kwargs: Any) -> dict[str, Any]:
        if self.__class__.fail_in_execute:
            raise RuntimeError("the job broke after it started")
        return {"success": True}


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
async def test_a_request_refused_at_validation_is_marked_as_dispatching_nothing() -> None:
    """Recipe proof 22 Nov: an extra field in a code-run call failed the whole same-turn reply.

    Only a refusal before execute() is a SkillRequestRejected (safe to hand back to the model
    as a tool error); a failure inside execute() stays a plain 422.
    """
    from fastapi import HTTPException

    from backend.shared.python_utils.chat_recovery_context import SkillRequestRejected

    definition = _batch_definition()
    StrictSkill.fail_in_execute = False
    with pytest.raises(SkillRequestRejected) as refused:
        await _fake_base_app()._dispatch_skill_with_class(
            definition, StrictSkill, {"command": "npm test", "ready_url": "http://127.0.0.1:5173/"})
    assert refused.value.status_code == 422
    StrictSkill.fail_in_execute = True
    with pytest.raises(HTTPException) as failed:
        await _fake_base_app()._dispatch_skill_with_class(definition, StrictSkill, {"command": "npm test"})
    assert failed.value.status_code == 422 and not isinstance(failed.value, SkillRequestRejected)
