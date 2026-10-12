"""Ciphertext discovery indexes preserve fresh visibility and omit private bodies."""
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.encrypted_discovery_index import (
    list_encrypted_project_discovery,
    list_project_focus_discovery,
    list_team_memory_key_discovery,
)


class Cache:
    def __init__(self):
        self.entries = {}
        self.expired = []

    async def get_user_vault_key_id(self, user_id):
        return "vault-epoch-1"

    async def get(self, key):
        return self.entries.get(key)

    async def set(self, key, value, ttl):
        assert ttl == 7200
        self.entries[key] = value

    @property
    async def client(self):
        async def expire(key, ttl):
            self.expired.append((key, ttl))
        return SimpleNamespace(expire=expire)


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_project_index_rechecks_visibility_and_never_retains_wrapped_key():
    cache = Cache()
    project = {
        "project_id": "p1", "version": 1, "updated_at": "one", "archived": False,
        "encrypted_name": "ciphertext", "encrypted_project_key": "fresh-key",
    }
    class Directus:
        def __init__(self):
            self.rows = [project.copy()]
            self.project = SimpleNamespace(list_projects=self.list_projects)
        async def list_projects(self, user_id, team_id=None):
            return [row.copy() for row in self.rows]
        async def get_items(self, collection, params, **kwargs):
            assert collection == "projects"
            assert "filter[hashed_user_id][_eq]" in params
            return [row.copy() for row in self.rows]
    directus = Directus()
    assert (await list_encrypted_project_discovery(cache=cache, directus=directus, user_id="alice", team_id=None))[0]["encrypted_project_key"] == "fresh-key"
    entry = next(iter(cache.entries.values()))
    assert "encrypted_project_key" not in str(entry)
    directus.rows[0]["encrypted_project_key"] = "new-wrapper"
    assert (await list_encrypted_project_discovery(cache=cache, directus=directus, user_id="alice", team_id=None))[0]["encrypted_project_key"] == "new-wrapper"
    directus.rows.clear()
    assert await list_encrypted_project_discovery(cache=cache, directus=directus, user_id="alice", team_id=None) == []


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_focus_and_team_memory_indexes_contain_only_opaque_revisions():
    cache = Cache()
    class Directus:
        async def get_items(self, collection, params, **kwargs):
            if collection == "project_items":
                assert "filter[hashed_user_id][_eq]" in params
                return [{"project_item_id": "i1", "updated_at": "r1", "item_type": "chat", "encrypted_metadata": "private-focus"}]
            assert collection == "user_app_settings_and_memories"
            assert "hashed_team_id" in params["filter"]
            return [{"id": "m1", "app_id": "notes", "item_key": "tone", "item_type": "memory", "item_version": 2,
                     "updated_at": "r2", "encrypted_item_json": "private-memory"}]
    directus = Directus()
    focus = await list_project_focus_discovery(cache=cache, directus=directus, user_id="alice", team_id=None, project_id="p1")
    memory = await list_team_memory_key_discovery(cache=cache, directus=directus, user_id="alice", team_id="team")
    assert focus == [{"project_item_id": "i1", "revision": "r1", "item_type": "chat"}]
    assert memory == [{"id": "m1", "app_id": "notes", "item_key": "tone", "item_type": "memory", "item_version": 2, "updated_at": "r2"}]
    assert "private-focus" not in str(cache.entries)
    assert "private-memory" not in str(cache.entries)
