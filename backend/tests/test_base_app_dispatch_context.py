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
