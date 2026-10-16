"""Completed response recommendation permits retain fresh Project authority."""

# contract-test-file: infrastructure

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService


def _load_availability_publisher():
    """Import the real worker without applying its logging setup to other tests."""
    root = logging.getLogger()
    existing = {"": (root, list(root.handlers), root.level, root.propagate, root.disabled)}
    for name, value in logging.Logger.manager.loggerDict.copy().items():
        if isinstance(value, logging.Logger):
            existing[name] = (value, list(value.handlers), value.level, value.propagate, value.disabled)
    try:
        from backend.apps.ai.tasks.ask_skill_task import _publish_project_authoring_availability
        return _publish_project_authoring_availability
    finally:
        for name, value in logging.Logger.manager.loggerDict.copy().items():
            if isinstance(value, logging.Logger) and name not in existing:
                value.handlers = []
                value.setLevel(logging.NOTSET)
                value.propagate = True
                value.disabled = False
        for value, handlers, level, propagate, disabled in existing.values():
            value.handlers = handlers
            value.setLevel(level)
            value.propagate = propagate
            value.disabled = disabled


_publish_project_authoring_availability = _load_availability_publisher()


def request(**overrides):
    fields = dict(user_id="owner", chat_id="chat", message_id="user-turn", team_id=None,
                  active_project_focus={"project_id": "project"})
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.asyncio
async def test_completed_response_mints_only_content_free_recommendation_permit(monkeypatch):
    cache = SimpleNamespace(get=AsyncMock(side_effect=lambda key: {"project_id": "project", "team_id": None} if "focus" in key else "user-turn"),
                            set=AsyncMock(return_value=True), publish_event=AsyncMock())
    monkeypatch.setattr(ProjectWriteAuthorizationService, "_require_chat_access", AsyncMock())
    monkeypatch.setattr(ProjectWriteAuthorizationService, "_require_project_access", AsyncMock())
    assert await _publish_project_authoring_availability(request(), "assistant-turn", cache, object())
    assert cache.set.await_args.args[1] == {"project_id": "project", "team_id": None}
    assert cache.set.await_args.kwargs == {"ttl": 1200}
    assert cache.publish_event.await_args.args == ("user_cache_events:owner", {
        "event_type": "project_authoring_available", "payload": {
            "chat_id": "chat", "project_id": "project", "user_message_id": "user-turn",
            "assistant_message_id": "assistant-turn",
        },
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["client_only", "stale_binding", "denied_project", "store_failed", "incognito"])
async def test_stale_or_unauthorized_context_never_claims_recommendations_available(monkeypatch, cause):
    cache = SimpleNamespace(get=AsyncMock(side_effect=lambda key: {"project_id": "other" if cause == "stale_binding" else "project", "team_id": None} if "focus" in key else "user-turn"),
                            set=AsyncMock(return_value=cause != "store_failed"), publish_event=AsyncMock())
    monkeypatch.setattr(ProjectWriteAuthorizationService, "_require_chat_access", AsyncMock())
    monkeypatch.setattr(ProjectWriteAuthorizationService, "_require_project_access", AsyncMock(
        side_effect=RuntimeError("denied") if cause == "denied_project" else None,
    ))
    kwargs = {"active_project_focus": None, "current_project": {"id": "project"}} if cause == "client_only" else {}
    if cause == "incognito":
        kwargs["is_incognito"] = True
    assert not await _publish_project_authoring_availability(request(**kwargs), "assistant-turn", cache, object())
    cache.publish_event.assert_not_awaited()
