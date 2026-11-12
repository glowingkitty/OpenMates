"""AskSkill dispatch forwards the client Memory catalog to the AI task as metadata only."""

import hashlib

import pytest

import backend.shared.python_utils.recent_work_summary_client as summary_client
from backend.apps.ai.processing.rule_context import request_personal_catalog
from backend.apps.ai.skills.ask_skill import AskSkill, AskSkillRequest
from backend.apps.ai.tasks import ask_skill_task


def _request(**extra):
    return AskSkillRequest(
        chat_id="chat", message_id="first", user_id="owner",
        user_id_hash=hashlib.sha256(b"owner").hexdigest(),
        is_incognito=False, is_external=False, is_anonymous=False,
        message_history=[{"role": "user", "message_id": "first",
                          "content": "Write my cover letter", "created_at": 1}],
        **extra,
    )


def _skill():
    skill = AskSkill.__new__(AskSkill)
    skill.parsed_default_config = None
    skill.celery_producer = object()
    skill.skill_name = "ask"
    return skill


async def _dispatched(monkeypatch, request):
    published = []

    async def seal(payload, *, request_id):
        return payload

    monkeypatch.setattr(summary_client, "seal_private_context_payload", seal)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async",
                        lambda **kwargs: published.append(kwargs))
    await _skill()._handle_internal_request(request)
    assert len(published) == 1
    return published[0]["kwargs"]["request_data_dict"]


CATALOG = [{"id": "career-profile", "title": "Career profile",
            "when_to_use": "Job applications and CVs.", "load_mode": "auto_include",
            "source": "personal"}]


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.selection.source-scoped
@pytest.mark.anyio
async def test_first_turn_dispatch_keeps_the_memory_catalog_for_selection(monkeypatch):
    data = await _dispatched(monkeypatch, _request(memory_catalog=CATALOG))
    # Plain JSON rows, so the broker can serialize them; bodies never travel.
    assert data["memory_catalog"] == CATALOG
    restored = AskSkillRequest(**data)
    assert [entry.id for entry in request_personal_catalog(restored)] == ["career-profile"]


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.selection.source-scoped
@pytest.mark.anyio
async def test_dispatch_without_catalog_sends_none(monkeypatch):
    data = await _dispatched(monkeypatch, _request())
    assert "memory_catalog" not in data
