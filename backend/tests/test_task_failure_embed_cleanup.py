"""A skill card left on "processing" by a failed task always ends in an error state (TASK-2115).

The failed turn's cleanup used to pass a made-up Vault key name, so Vault
refused to encrypt the error content and the card kept spinning with its stop
button while the chat had already ended.
"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.tasks import ask_skill_task


TASK = "task-1"
CHAT = "chat-1"


class FakeRedis:
    def __init__(self, records):
        self.records = records

    async def scan(self, cursor, match, count):
        return 0, list(self.records)

    async def get(self, key):
        return json.dumps(self.records[key])


class FakeCache:
    def __init__(self, records, vault_key_id="vault-real"):
        self._redis = FakeRedis(records)
        self.vault_key_id = vault_key_id

    @property
    async def client(self):
        return self._redis

    async def get_user_vault_key_id(self, user_id):
        return self.vault_key_id


def _processing_record(embed_id, task_id=TASK):
    return {
        "embed_id": embed_id, "status": "processing",
        "hashed_chat_id": hashlib.sha256(CHAT.encode()).hexdigest(),
        "hashed_task_id": hashlib.sha256(task_id.encode()).hexdigest(),
    }


@pytest.fixture
def embed_service(monkeypatch):
    service = SimpleNamespace(
        update_embed_status_to_error=AsyncMock(return_value={"embed_id": "e", "status": "error"}),
        update_embed_status_to_cancelled=AsyncMock(return_value={"embed_id": "e", "status": "cancelled"}),
    )
    monkeypatch.setattr(ask_skill_task, "EmbedService", lambda *args: service)
    return service


async def _cleanup(cache, directus, **overrides):
    arguments = dict(
        task_id=TASK, chat_id=CHAT, message_id="message-1", user_id="user-1",
        user_id_hash="a" * 64, user_vault_key_id=None,
        error_message="Main processing stream execution failed",
        cache_service=cache, directus_service=directus, encryption_service=SimpleNamespace(),
    )
    arguments.update(overrides)
    return await ask_skill_task._cleanup_processing_embeds_on_task_failure(**arguments)


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=app-skills.media.parent-children-and-attribution,app-skills.assistant.bounded-private-failure
async def test_failed_task_marks_its_processing_card_as_error_with_the_users_real_vault_key(embed_service):
    cache = FakeCache({
        "embed:generate": _processing_record("generate"),
        "embed:other-task": _processing_record("other-task", task_id="task-2"),
    })
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock())

    assert await _cleanup(cache, directus) == 1

    call = embed_service.update_embed_status_to_error.await_args.kwargs
    assert call["embed_id"] == "generate"
    assert call["user_vault_key_id"] == "vault-real"
    directus.get_user_fields_direct.assert_not_awaited()


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=app-skills.media.parent-children-and-attribution
async def test_vault_key_cache_miss_falls_back_to_the_user_record(embed_service):
    cache = FakeCache({"embed:generate": _processing_record("generate")}, vault_key_id=None)
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(return_value={"vault_key_id": "vault-db"}))

    assert await _cleanup(cache, directus) == 1
    assert embed_service.update_embed_status_to_error.await_args.kwargs["user_vault_key_id"] == "vault-db"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=app-skills.media.parent-children-and-attribution
async def test_a_card_that_could_not_be_sealed_is_not_reported_as_cleaned(embed_service):
    embed_service.update_embed_status_to_error.return_value = None
    cache = FakeCache({"embed:generate": _processing_record("generate")})

    assert await _cleanup(cache, SimpleNamespace(get_user_fields_direct=AsyncMock())) == 0


# contract-test: supporting surface=rest_api assertions=app-skills.media.parent-children-and-attribution
def test_sync_failure_wrappers_never_guess_a_vault_key_name():
    import inspect

    assert 'f"user:{request_data.user_id}:encryption_key"' not in inspect.getsource(ask_skill_task)
