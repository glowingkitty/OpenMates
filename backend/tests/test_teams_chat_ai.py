"""Teams V1 chat AI trigger and attribution tests.

Team chat AI must be explicit: ordinary team messages are collaboration-only,
while @openmates messages can trigger AI and carry team billing context through
the shared AI request schemas.
"""

import sys
import types


if "celery" not in sys.modules:
    celery_module = types.ModuleType("celery")
    signals_module = types.ModuleType("celery.signals")
    schedules_module = types.ModuleType("celery.schedules")

    class FakeCelery:
        pass

    def fake_crontab(*_args, **_kwargs):
        return None

    celery_module.Celery = FakeCelery
    celery_module.signals = signals_module
    schedules_module.crontab = fake_crontab
    sys.modules["celery"] = celery_module
    sys.modules["celery.signals"] = signals_module
    sys.modules["celery.schedules"] = schedules_module

from backend.apps.ai.skills.ask_skill import AskSkillRequest as AppAskSkillRequest
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreAskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.team_chat_ai_service import extract_team_ai_context, format_sender_attributed_content, should_trigger_team_ai


def test_team_chat_requires_openmates_mention_to_trigger_ai() -> None:
    assert should_trigger_team_ai("hello everyone", is_team_chat=False) is True
    assert should_trigger_team_ai("hello everyone", is_team_chat=True) is False
    assert should_trigger_team_ai("@OpenMates summarize this", is_team_chat=True) is True


def test_ai_history_message_preserves_team_sender_name() -> None:
    message = AIHistoryMessage(role="user", content="I prefer option A", sender_name="Alice", created_at=100)

    assert message.sender_name == "Alice"


def test_sender_attribution_formats_team_history_for_llm_content() -> None:
    assert format_sender_attributed_content("I prefer option A", "Alice") == "[Alice]: I prefer option A"
    assert format_sender_attributed_content("I prefer option A", None) == "I prefer option A"


def test_team_ai_context_defaults_chat_object_hash() -> None:
    context = extract_team_ai_context(
        {"chat_id": "chat-1", "team_id": "team-1"},
        {"chat_id": "chat-1"},
    )

    assert context["team_id"] == "team-1"
    assert context["team_id_hash"] == hash_id("team-1")
    assert context["team_workspace_type"] == "chat"
    assert context["team_object_id_hash"] == hash_id("chat-1")


def test_core_and_app_ask_skill_requests_carry_team_billing_context() -> None:
    base_payload = {
        "chat_id": "chat-1",
        "message_id": "message-1",
        "user_id": "alice",
        "user_id_hash": hash_id("alice"),
        "message_history": [{"role": "user", "content": "@openmates help", "sender_name": "Alice", "created_at": 100}],
        "team_id": "team-1",
        "team_id_hash": hash_id("team-1"),
        "team_workspace_type": "chat",
        "team_object_id_hash": hash_id("chat-1"),
    }

    core_request = CoreAskSkillRequest(**base_payload)
    app_request = AppAskSkillRequest(**base_payload)

    assert core_request.team_id == "team-1"
    assert core_request.team_object_id_hash == hash_id("chat-1")
    assert app_request.team_id == "team-1"
    assert app_request.team_workspace_type == "chat"
