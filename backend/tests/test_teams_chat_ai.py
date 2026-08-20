"""Teams V1 chat AI trigger and attribution tests.

Team chat AI must be explicit: ordinary team messages are collaboration-only,
while @openmates messages can trigger AI and carry team billing context through
the shared AI request schemas.
"""

import sys
import types
import base64
from pathlib import Path


if "celery" not in sys.modules:
    celery_module = types.ModuleType("celery")
    exceptions_module = types.ModuleType("celery.exceptions")
    states_module = types.ModuleType("celery.states")
    signals_module = types.ModuleType("celery.signals")
    schedules_module = types.ModuleType("celery.schedules")

    class FakeCelery:
        pass

    def fake_crontab(*_args, **_kwargs):
        return None

    celery_module.Celery = FakeCelery
    celery_module.signals = signals_module
    exceptions_module.Ignore = Exception
    exceptions_module.SoftTimeLimitExceeded = TimeoutError
    states_module.REVOKED = "REVOKED"
    schedules_module.crontab = fake_crontab
    sys.modules["celery"] = celery_module
    sys.modules["celery.exceptions"] = exceptions_module
    sys.modules["celery.states"] = states_module
    sys.modules["celery.signals"] = signals_module
    sys.modules["celery.schedules"] = schedules_module

from backend.apps.ai.skills.ask_skill import AskSkillRequest as AppAskSkillRequest
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreAskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.team_chat_ai_service import (
    extract_team_ai_context,
    format_sender_attributed_content,
    parse_team_message_transport,
    should_trigger_team_ai,
)


CLIENT_CIPHERTEXT = base64.b64encode(b"x" * 29).decode("ascii")


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
def test_team_chat_requires_openmates_mention_to_trigger_ai() -> None:
    assert should_trigger_team_ai("hello everyone", is_team_chat=False) is True
    assert should_trigger_team_ai("hello everyone", is_team_chat=True) is False
    assert should_trigger_team_ai("@OpenMates summarize this", is_team_chat=True) is True


# contract-test: supporting surface=rest_api assertions=teams.chat.sender-identity-layout
def test_ai_history_message_preserves_team_sender_name() -> None:
    message = AIHistoryMessage(role="user", content="I prefer option A", sender_name="Alice", created_at=100)

    assert message.sender_name == "Alice"


# contract-test: supporting surface=rest_api assertions=teams.chat.sender-identity-layout
def test_sender_attribution_formats_team_history_for_llm_content() -> None:
    assert format_sender_attributed_content("I prefer option A", "Alice") == "[Alice]: I prefer option A"
    assert format_sender_attributed_content("I prefer option A", None) == "I prefer option A"


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
def test_team_ai_context_defaults_chat_object_hash() -> None:
    context = extract_team_ai_context(
        {"chat_id": "chat-1", "team_id": "team-1"},
        {"chat_id": "chat-1"},
    )

    assert context["team_id"] == "team-1"
    assert context["team_id_hash"] == hash_id("team-1")
    assert context["team_workspace_type"] == "chat"
    assert context["team_object_id_hash"] == hash_id("chat-1")


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
def test_team_ai_context_ignores_client_supplied_team_hash() -> None:
    context = extract_team_ai_context(
        {"chat_id": "chat-1", "team_id": "team-1", "team_id_hash": hash_id("other-team")},
        {"chat_id": "chat-1"},
    )

    assert context["team_id_hash"] == hash_id("team-1")


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
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


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
def test_team_ai_credit_charge_source_uses_team_endpoint_not_personal_billing() -> None:
    source = (Path(__file__).resolve().parents[1] / "apps/ai/tasks/stream_consumer.py").read_text(encoding="utf-8")
    team_branch = source.split('if team_id:', 1)[1].split('else:', 1)[0]

    assert 'charge_path = "/internal/billing/team/charge"' in team_branch
    assert '"team_id": team_id' in team_branch
    assert '"actor_user_id": request_data.user_id' in team_branch
    assert '"user_id_hash"' not in team_branch
    assert '"api_key_hash"' not in team_branch
    assert '"device_hash"' not in team_branch


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
def test_ordinary_team_message_accepts_ciphertext_without_plaintext_or_ai_history() -> None:
    transport = parse_team_message_transport(
        {"team_id": "team-1"},
        {
            "message_id": "message-1",
            "role": "user",
            "encrypted_content": CLIENT_CIPHERTEXT,
            "team_member_mentions": ["bob"],
        },
    )

    assert transport.encrypted_content == CLIENT_CIPHERTEXT
    assert transport.should_trigger_ai is False
    assert transport.inference_history is None
    assert transport.mentioned_user_ids == ("bob",)


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
def test_openmates_requires_and_replaces_with_full_attributed_history() -> None:
    transport = parse_team_message_transport(
        {
            "team_id": "team-1",
            "team_ai_invocation": {
                "history": [
                    {"role": "user", "content": "First", "sender_name": "Alice", "created_at": 100},
                    {"role": "user", "content": "@openmates summarize", "sender_name": "Bob", "created_at": 200},
                ]
            },
        },
        {
            "message_id": "message-2",
            "role": "user",
            "encrypted_content": CLIENT_CIPHERTEXT,
        },
    )

    assert transport.should_trigger_ai is True
    assert [(item.sender_name, item.content) for item in transport.inference_history or ()] == [
        ("Alice", "First"),
        ("Bob", "@openmates summarize"),
    ]


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
def test_team_transport_rejects_plaintext_without_explicit_ai_invocation() -> None:
    import pytest

    with pytest.raises(ValueError, match="ciphertext"):
        parse_team_message_transport(
            {"team_id": "team-1"},
            {"message_id": "message-1", "role": "user", "content": "private plaintext"},
        )

    with pytest.raises(ValueError, match="valid client-encrypted"):
        parse_team_message_transport(
            {"team_id": "team-1"},
            {"message_id": "message-1", "role": "user", "encrypted_content": "private plaintext"},
        )


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked,teams.collaboration.realtime-team-sync
def test_websocket_handler_enters_team_transport_before_plaintext_pipeline() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "core/api/app/routes/handlers/websocket_handlers/message_received_handler.py"
    ).read_text(encoding="utf-8")

    parse_index = source.index("parse_team_message_transport(")
    ordinary_return_index = source.index("if is_team_chat and not team_transport.should_trigger_ai:")
    plaintext_index = source.index('content_plain_raw = message_payload_from_client.get("content")')
    assert parse_index < ordinary_return_index < plaintext_index
    assert "broadcast_team_event(" in source[parse_index:plaintext_index]


# contract-test: supporting surface=cli assertions=teams.chat.encrypted-until-invoked
def test_ordinary_team_transport_confirms_origin_before_early_return() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "core/api/app/routes/handlers/websocket_handlers/message_received_handler.py"
    ).read_text(encoding="utf-8")
    ordinary_branch = source.split("if is_team_chat and not team_transport.should_trigger_ai:", 1)[1].split(
        'message_id = message_payload_from_client.get("message_id")', 1
    )[0]

    assert "await _send_origin_chat_message_confirmed(" in ordinary_branch
    assert ordinary_branch.index("await _send_origin_chat_message_confirmed(") < ordinary_branch.index("return")


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked,teams.context.full-switch-local
def test_sdk_team_chat_uses_split_ciphertext_and_inference_envelopes() -> None:
    source = (Path(__file__).resolve().parents[1] / "core/api/app/routes/sdk.py").read_text(encoding="utf-8")

    assert "team_ai_invocation: dict[str, Any] | None" in source
    assert '"team_plaintext_message_forbidden"' in source
    assert '"team_ai_history_required"' in source
    assert '"team_id_hash": hashlib.sha256(str(team_id).encode()).hexdigest()' in source


# contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked,teams.context.full-switch-local
def test_team_message_persistence_carries_canonical_team_scope() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    handler_source = (backend_root / "core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py").read_text(encoding="utf-8")
    persistence_source = (backend_root / "core/api/app/tasks/persistence_tasks.py").read_text(encoding="utf-8")

    assert 'kwargs={"hashed_team_id": hashed_team_id}' in handler_source
    assert '"hashed_team_id": hashed_team_id' in persistence_source
    assert "Chat {chat_id} does not belong to the selected Team" in persistence_source
