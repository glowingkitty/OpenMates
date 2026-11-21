# backend/tests/test_code_command_parent_embed.py
"""The parent "Run" card of a cloud terminal command leaves "processing" when the run ends."""
import sys
from types import ModuleType

import pytest
from toon_format import decode as toon_decode

from backend.apps.code.tasks import command_parent_embed
from backend.apps.code.tasks.command_parent_embed import build_command_parent_content, finalize_command_parent_embed


def _payload(parent: str | None = "parent-1") -> dict:
    return {
        "chat_id": "chat-1", "message_id": "msg-1", "user_id": "user-1", "user_id_hash": "hash-1",
        "target_embed_id": "term-1",
        "command_run": {"argv": ["npm", "install"], "cwd": "web-app", "parent_embed_id": parent},
    }


class _RecordingEmbedService:
    calls: list[dict] = []

    def __init__(self, **_kwargs) -> None:
        pass

    async def send_embed_data_to_client(self, **kwargs) -> bool:
        _RecordingEmbedService.calls.append(kwargs)
        return True


class _Encryption:
    def __init__(self, **_kwargs) -> None:
        pass

    async def initialize(self) -> None:
        return None


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    _RecordingEmbedService.calls = []
    for name, attrs in {
        "backend.core.api.app.services.embed_service": {"EmbedService": _RecordingEmbedService},
        "backend.core.api.app.services.directus": {"DirectusService": lambda **_kwargs: object()},
        "backend.core.api.app.utils.encryption": {"EncryptionService": _Encryption},
    }.items():
        module = ModuleType(name)
        for attr, value in attrs.items():
            setattr(module, attr, value)
        monkeypatch.setitem(sys.modules, name, module)
    return _RecordingEmbedService.calls


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_finished_command_card_carries_command_folder_and_exit_code() -> None:
    status, content = build_command_parent_content(_payload(), {"status": "finished", "exit_code": 0})
    assert status == "finished"
    assert content["argv"] == ["npm", "install"] and content["cwd"] == "web-app"
    assert content["exit_code"] == 0 and content["embed_ids"] == ["term-1"]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
@pytest.mark.asyncio
async def test_run_end_finishes_the_parent_card_with_the_terminal_card_as_result(recorded: list[dict]) -> None:
    assert await finalize_command_parent_embed(_payload(), {"status": "finished", "exit_code": 0}, cache_service=object())
    (call,) = recorded
    assert call["embed_id"] == "parent-1" and call["embed_type"] == "app_skill_use"
    assert call["status"] == "finished" and call["embed_ids"] == ["term-1"]
    assert toon_decode(call["content_toon"])["argv"] == ["npm", "install"]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
@pytest.mark.asyncio
async def test_failed_run_sets_the_parent_card_to_error(recorded: list[dict]) -> None:
    assert await finalize_command_parent_embed(
        _payload(), {"status": "failed", "exit_code": 1, "error": "exit 1"}, cache_service=object(),
    )
    assert recorded[0]["status"] == "error"
    assert toon_decode(recorded[0]["content_toon"])["exit_code"] == 1


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
@pytest.mark.asyncio
async def test_run_without_a_placeholder_touches_no_card(recorded: list[dict]) -> None:
    assert not await finalize_command_parent_embed(_payload(None), {"status": "finished"}, cache_service=object())
    assert recorded == []
    assert command_parent_embed.__doc__
