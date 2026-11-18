# backend/tests/test_orchestration_skill_gate.py
# contract-test-file: behavior
#
# Root-turn Code Runs (E2B or the user's machine) pass the async-skill
# orchestration gate, sub-chat Code Runs and other async skills stay refused, and
# a refused call's processing placeholder is settled to error.
# Spec: feature.app-skill.code-run code-run.cloud.commands.

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from backend.apps.ai.processing.orchestration_skill_gate import (
    BLOCKED_IN_ORCHESTRATION_MESSAGE,
    is_root_turn_code_run,
    settle_blocked_placeholders,
)


def _root(**overrides: Any) -> SimpleNamespace:
    values = {"user_id": "user-1", "is_sub_chat": False, "sub_chat_depth": 0, "orchestration_id": "orchestration-1"}
    values.update(overrides)
    return SimpleNamespace(**values)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_root_turn_code_run_passes_the_gate() -> None:
    assert is_root_turn_code_run(_root(), "code", "run") is True


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_sub_chat_code_run_stays_refused() -> None:
    assert is_root_turn_code_run(_root(is_sub_chat=True, sub_chat_depth=1), "code", "run") is False
    assert is_root_turn_code_run(_root(sub_chat_depth=2), "code", "run") is False


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_other_async_skills_stay_refused_at_the_root() -> None:
    assert is_root_turn_code_run(_root(), "images", "generate") is False


class _Embeds:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def update_embed_status_to_error(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_refused_call_settles_every_placeholder_to_error() -> None:
    embeds = _Embeds()
    request = SimpleNamespace(chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1")
    settled = asyncio.run(settle_blocked_placeholders(
        {"multiple": True, "placeholders": [{"embed_id": "embed-1"}, {"embed_id": "embed-2"}]},
        embed_service=embeds, app_id="code", skill_id="run", request_data=request,
        user_vault_key_id="vault-1", task_id="task-1", log_prefix="[test]",
    ))
    assert settled == ["embed-1", "embed-2"]
    assert [call["embed_id"] for call in embeds.calls] == ["embed-1", "embed-2"]
    assert all(call["error_message"] == BLOCKED_IN_ORCHESTRATION_MESSAGE for call in embeds.calls)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_no_placeholder_means_nothing_to_settle() -> None:
    embeds = _Embeds()
    request = SimpleNamespace(chat_id="c", message_id="m", user_id="u", user_id_hash="h")
    assert asyncio.run(settle_blocked_placeholders(
        None, embed_service=embeds, app_id="code", skill_id="run", request_data=request,
        user_vault_key_id="v", task_id="t", log_prefix="",
    )) == []
    assert embeds.calls == []
